import json
import logging
import os
import boto3
from datetime import datetime
from botocore.exceptions import ClientError
import base64

logger = logging.getLogger()
logger.setLevel(logging.INFO)

bedrock_runtime = boto3.client('bedrock-runtime')
s3_client = boto3.client('s3')

MODEL_ID = os.environ.get('MODEL_ID')

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
        temperature = record.get('temperature', 0.1)

        logger.info(f"Processing s3://{bucket}/{file_key}")

        response = s3_client.get_object(Bucket=bucket, Key=file_key)
        image_data = response['Body'].read()
        base64_encoded = base64.b64encode(image_data).decode('utf-8')

        request_body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt    
                        },                    
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": get_media_type(file_key),
                                "data": base64_encoded
                            }
                        }
                    ]
                }
            ]
        }

        response = bedrock_runtime.invoke_model(
            modelId=MODEL_ID,
            body=json.dumps(request_body)
        )

        response_body = json.loads(response.get('body').read().decode('utf-8'))
        response_text = response_body['content'][0]['text']
        
        usage = response_body.get('usage', {})
        input_tokens = usage.get('input_tokens', 0)
        output_tokens = usage.get('output_tokens', 0)
        
        logger.info(f"Response: {json.dumps(response_body, indent=2)}")
        logger.info(f"Token usage - Input: {input_tokens}, Output: {output_tokens}")

        # Write result to S3 as individual JSON file
        output_key = f"{file_key}.json"
        
        s3_client.put_object(
            Bucket=output_bucket,
            Key=output_key,
            Body=response_text,
            ContentType='application/json',
            Metadata={
                'record-id': record_id,
                'processing-status': 'success',
                'input-tokens': str(input_tokens),
                'output-tokens': str(output_tokens),
                'total-tokens': str(input_tokens + output_tokens)
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

def get_media_type(filename):
    """
    Get media type for Claude based on file extension
    """
    extension = filename.lower().split('.')[-1]
    media_types = {
        'pdf': 'application/pdf',
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'tiff': 'image/tiff',
        'tif': 'image/tiff'
    }
    return media_types.get(extension, 'image/jpeg')

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

