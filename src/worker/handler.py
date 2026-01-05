import json
import logging
import os
import boto3
from datetime import datetime
from botocore.exceptions import ClientError
from PIL import Image
import io

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_runtime = boto3.client('bedrock-runtime')
s3_client = boto3.client('s3')

MODEL_ID = os.environ.get('MODEL_ID')

# Tool configuration for transcription
TRANSCRIPTION_TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "provide_exact_transcription",
                "description": "Extract the text content and detected languages from the provided image with exact fidelity.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "transcribed_text": {
                                "type": "string",
                                "description": "The exact text transcribed from the image, preserving formatting and line breaks where possible."
                            },
                            "detected_languages": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Array of ISO 639 language codes detected in the text (e.g., ['en', 'es', 'fr'])."
                            }
                        },
                        "required": ["transcribed_text", "detected_languages"]
                    }
                }
            }
        }
    ],
    "toolChoice": {
        "tool": {
            "name": "provide_exact_transcription"
        }
    }
}

def get_image_format(filename):
    """
    Get image format for Converse API based on file extension.

    All images are converted to PNG. PDFs remain as documents.

    Args:
        filename: The file path/name

    Returns:
        str: Image/document format for Converse API ('png' or 'pdf')
    """
    extension = filename.lower().split('.')[-1]
    # PDFs stay as PDF, everything else becomes PNG
    return 'pdf' if extension == 'pdf' else 'png'

def sanitize_pdf_filename(filename):
    """
    Sanitize PDF filename to meet Bedrock requirements:
    - Only alphanumeric, whitespace, hyphens, parentheses, and square brackets
    - No consecutive whitespace characters
    - No periods/dots (removes file extension)

    Args:
        filename: Original filename (e.g., "document.pdf")

    Returns:
        str: Sanitized filename without extension (e.g., "document")
    """
    import re
    # Remove file extension (everything after last dot)
    name_without_ext = filename.rsplit('.', 1)[0] if '.' in filename else filename

    # Replace consecutive whitespace with single space
    sanitized = re.sub(r'\s+', ' ', name_without_ext)
    # Remove any characters that aren't alphanumeric, space, hyphen, parentheses, or square brackets
    sanitized = re.sub(r'[^a-zA-Z0-9 \-\(\)\[\]]', '_', sanitized)
    # Clean up any resulting consecutive spaces again
    sanitized = re.sub(r'\s+', ' ', sanitized)
    return sanitized.strip()

def convert_and_resize_image(file_data, filename, max_dimension=1000):
    """
    Convert any image to PNG and resize to max dimension of 1000px.

    Args:
        file_data: Raw image bytes
        filename: Original filename for logging
        max_dimension: Maximum width or height in pixels (default: 1000)

    Returns:
        bytes: PNG image data resized to max dimension
    """
    logger.info(f"Converting {filename} to PNG with max dimension {max_dimension}px")

    # Open image with Pillow
    img = Image.open(io.BytesIO(file_data))
    original_width, original_height = img.size

    # Calculate new dimensions maintaining aspect ratio
    if original_width > max_dimension or original_height > max_dimension:
        if original_width > original_height:
            new_width = max_dimension
            new_height = int(original_height * (max_dimension / original_width))
        else:
            new_height = max_dimension
            new_width = int(original_width * (max_dimension / original_height))

        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        logger.info(f"Resized from {original_width}x{original_height} to {new_width}x{new_height}")
    else:
        new_width, new_height = original_width, original_height
        logger.info(f"Image {original_width}x{original_height} is within max dimension, no resize needed")

    # Convert to RGB if needed (PNG supports RGBA, but this handles any edge cases)
    if img.mode in ('RGBA', 'LA'):
        # Keep transparency for PNG
        pass
    elif img.mode == 'P':
        img = img.convert('RGBA')
    elif img.mode not in ('RGB', 'RGBA'):
        img = img.convert('RGB')

    # Save as PNG
    output = io.BytesIO()
    img.save(output, format='PNG', optimize=True)
    output_data = output.getvalue()

    logger.info(f"Converted to PNG: {len(file_data)} bytes -> {len(output_data)} bytes")
    return output_data

def extract_tool_response(response, expected_tool_name):
    """
    Extract tool use data from Converse API response.
    """
    stop_reason = response.get('stopReason')

    if stop_reason != 'tool_use':
        raise ValueError(
            f"Expected stopReason 'tool_use', got '{stop_reason}'. "
            f"Model may not have used the tool."
        )

    try:
        message_content = response['output']['message']['content']
    except (KeyError, TypeError) as e:
        raise ValueError(f"Malformed response structure: {e}")

    for content_block in message_content:
        if 'toolUse' in content_block:
            tool_use = content_block['toolUse']

            if tool_use['name'] == expected_tool_name:
                tool_input = tool_use.get('input', {})
                if isinstance(tool_input, dict) and "transcribed_text" in tool_input and "detected_languages" not in tool_input:
                    tool_input["detected_languages"] = ["en"]
                return tool_input
            else:
                raise ValueError(
                    f"Expected tool '{expected_tool_name}', "
                    f"got '{tool_use['name']}'"
                )

    raise ValueError("No toolUse block found in response content")

def validate_transcription_data(data):
    """
    Validate that transcription data has required fields.

    Args:
        data: The transcription data dict

    Returns:
        bool: True if valid

    Raises:
        ValueError: If validation fails
    """
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict, got {type(data).__name__}")

    if 'transcribed_text' not in data:
        raise ValueError("Missing required field: transcribed_text")

    if 'detected_languages' not in data:
        raise ValueError("Missing required field: detected_languages")

    if not isinstance(data['detected_languages'], list):
        raise ValueError(
            f"detected_languages must be array, got {type(data['detected_languages']).__name__}"
        )

    return True

def lambda_handler(event, context):
    logger.info(f"Processing file: {json.dumps(event, indent=2)}")

    try: 
        record = event['record']
        output_bucket = event['output_bucket']

        file_key = record['file_key']
        bucket = record['bucket']
        record_id = record['recordId']
        prompt = record['prompt']
        max_tokens = record.get('max_tokens', 8192)
        temperature = 0

        logger.info(f"Processing s3://{bucket}/{file_key}")

        # Get file data
        response = s3_client.get_object(Bucket=bucket, Key=file_key)
        file_data = response['Body'].read()

        # Determine format for Converse API
        file_format = get_image_format(file_key)

        # Build content block - PDFs use "document", others use "image"
        # Boto3 SDK handles base64 encoding automatically
        if file_format == 'pdf':
            # Sanitize PDF filename to meet Bedrock requirements
            pdf_filename = sanitize_pdf_filename(file_key.split('/')[-1])
            media_content = {
                "document": {
                    "format": file_format,
                    "name": pdf_filename,
                    "source": {
                        "bytes": file_data
                    }
                }
            }
        else:
            # Convert all images to PNG with max 1000px dimension
            file_data = convert_and_resize_image(file_data, file_key)

            media_content = {
                "image": {
                    "format": file_format,
                    "source": {
                        "bytes": file_data
                    }
                }
            }

        # Call Bedrock Converse API with tool definition
        response = bedrock_runtime.converse(
            modelId=MODEL_ID,
            messages=[
                {
                    "role": "user",
                    "content": [
                        media_content,
                        {
                            "text": prompt
                        }
                    ]
                }
            ],
            toolConfig=TRANSCRIPTION_TOOL_CONFIG,
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": temperature
            }
        )

        # Extract token usage
        usage = response.get('usage', {})
        input_tokens = usage.get('inputTokens', 0)
        output_tokens = usage.get('outputTokens', 0)

        logger.info(f"Token usage - Input: {input_tokens}, Output: {output_tokens}")

        # Extract and validate tool response
        transcription_data = extract_tool_response(response, 'provide_exact_transcription')
        validate_transcription_data(transcription_data)

        # Write structured result to S3 as individual JSON file
        output_key = f"{file_key}.json"

        s3_client.put_object(
            Bucket=output_bucket,
            Key=output_key,
            Body=json.dumps(transcription_data, indent=2, ensure_ascii=False),
            ContentType='application/json',
            Metadata={
                'record-id': record_id,
                'processing-status': 'success',
                'input-tokens': str(input_tokens),
                'output-tokens': str(output_tokens),
                'total-tokens': str(input_tokens + output_tokens),
                'tool-name': 'provide_exact_transcription'
            }
        )

        return {
            "statusCode": 200,
            "recordId": record_id,
            "file_key": file_key,
            "output_key": output_key,
            # "tokens_used": response['usage']['totalTokens'],
            "status": "success"
        }

    except ValueError as e:
        # Tool response validation failed
        file_key = record.get('file_key', 'unknown')
        record_id = record.get('recordId', 'unknown')
        error_message = str(e)

        logger.error(f"Tool response validation failed for {record_id}: {error_message}")

        output_key = write_error_file(
            s3_client, output_bucket, file_key, record_id,
            "ToolResponseValidationError", error_message
        )
        return create_error_response(
            record_id, file_key, output_key,
            "ToolResponseValidationError", error_message
        )

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        file_key = record.get('file_key', 'unknown')
        record_id = record.get('recordId', 'unknown')
        
        logger.error(f"AWS Error processing {record_id}: {error_code} - {error_message}")
        
        output_key = write_error_file(s3_client, output_bucket, file_key, record_id, error_code, error_message)
        return create_error_response(record_id, file_key, output_key, error_code, error_message)
        
    except Exception as e:
        file_key = record.get('file_key', 'unknown')
        record_id = record.get('recordId', 'unknown')
        error_message = str(e)
        
        logger.error(f"Unexpected error processing {record_id}: {error_message}")
        
        output_key = write_error_file(s3_client, output_bucket, file_key, record_id, "UnexpectedError", error_message)
        return create_error_response(record_id, file_key, output_key, "UnexpectedError", error_message)

def write_error_file(s3_client, output_bucket, file_key, record_id, error_code, error_message):
    """Write error details to S3 output file"""
    output_key = f"{file_key}.json"
    
    error_result = {
        "status": "error",
        "error_code": error_code,
        "error_message": error_message,
        "file_key": file_key,
        "record_id": record_id,
        "timestamp": datetime.now().isoformat()
    }
    
    try:
        s3_client.put_object(
            Bucket=output_bucket,
            Key=output_key,
            Body=json.dumps(error_result, indent=2),
            ContentType='application/json',
            Metadata={
                'record-id': record_id,
                'processing-status': 'error',
                'error-code': error_code,
                'input-tokens': '0',
                'output-tokens': '0',
                'total-tokens': '0'
            }
        )
        logger.info(f"Wrote error file: {output_key}")
    except Exception as s3_error:
        logger.error(f"Failed to write error file {output_key}: {s3_error}")
    
    return output_key

def create_error_response(record_id, file_key, output_key, error_code, error_message, status_code=500):
    """Create standardized error response"""
    return {
        "statusCode": status_code,
        "recordId": record_id,
        "file_key": file_key,
        "output_key": output_key,
        "status": "error",
        "error_code": error_code,
        "error_message": error_message
    }
