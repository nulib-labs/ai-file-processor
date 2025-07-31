import json
import logging
import os
import boto3
from urllib.parse import unquote_plus
from datetime import datetime


logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")
bedrock_client = boto3.client("bedrock", region_name='us-east-1')
OUTPUT_BUCKET = os.environ.get('OUTPUT_BUCKET') 
BEDROCK_ROLE_ARN = os.environ.get('BEDROCK_ROLE_ARN')
MODEL_ID = os.environ.get('MODEL_ID')
SUPPORTED_EXTENSIONS = ['.png', '.jpg', '.jpeg']

def lambda_handler(event, context):
    logger.info("Received event: %s" % json.dumps(event, indent=2))
    
    # Validate required environment variables
    if not OUTPUT_BUCKET:
        logger.error("OUTPUT_BUCKET environment variable not set")
        return {"statusCode": 500, "body": "Configuration error"}
    if not BEDROCK_ROLE_ARN:
        logger.error("BEDROCK_ROLE_ARN environment variable not set") 
        return {"statusCode": 500, "body": "Configuration error"}
    if not MODEL_ID:
        logger.error("MODEL_ID environment variable not set")
        return {"statusCode": 500, "body": "Configuration error"}

    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        logger.info(f"Processing: bucket={bucket}, key={key}")

        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            file_content = response["Body"].read().decode("utf-8")
            prompt_config = json.loads(file_content)

            print(f"prompt config: {prompt_config}")

            if "prompt" not in prompt_config:
                raise ValueError("Missing required field: 'prompt'")
            
            ## TODO validate one level directory only
            
            directory_path = '/'.join(key.split('/')[:-1])
            if directory_path:
                directory_path += '/'

            files = list_files_in_directory(bucket, directory_path)
            logger.info(f"Found {len(files)} processable files")

            # Bedrock batch has 100 file minimum requirement
            if len(files) < 100:
                logger.error(f"Only {len(files)} files found. Bedrock batch requires minimum 100 records. Cannot proceed with batch job.")
                continue

            jsonl_content = create_batch_jsonl(files, prompt_config, bucket)

            if not jsonl_content:
                logger.error("Failed to create batch input data")
                continue
                
            batch_input_key = f"{directory_path}batch_input.jsonl"
            s3_client.put_object(
                Bucket=OUTPUT_BUCKET,
                Key=batch_input_key,
                Body=jsonl_content,
                ContentType='application/x-jsonlines'
            )

            logger.info(f"Batch input file created: {batch_input_key}")

            job_name = f"ai-processor-{directory_path.replace('/', '-')}-{int(datetime.now().timestamp())}"

            batch_response = bedrock_client.create_model_invocation_job(
                roleArn=BEDROCK_ROLE_ARN,
                modelId=MODEL_ID,
                jobName=job_name,
                inputDataConfig={
                    's3InputDataConfig': {
                        's3InputFormat': 'JSONL',
                        's3Uri': f's3://{OUTPUT_BUCKET}/{batch_input_key}'
                    }
                },
                outputDataConfig={
                    's3OutputDataConfig': {
                        's3Uri': f's3://{OUTPUT_BUCKET}/{directory_path}batch_output/'
                    }
                },
            )

            job_arn = batch_response['jobArn']
            logger.info(f"Batch job created: {job_arn}")


        except Exception as e:
            print(f"Error reading object: {key}: {e}")

    return {"statusCode": 200, "body": "success"}


def list_files_in_directory(bucket, directory_path):
    files = []

    try:
        response = s3_client.list_objects_v2(
            Bucket=bucket,
            Prefix=directory_path
        )
        if 'Contents' not in response:
            logger.info("No files in directory")

        for obj in response['Contents']:
            key = obj['Key']

            if (key.endswith('prompt.json') or 
                key.endswith('.json') or 
                key.endswith('/')):
                continue
        
            # TODO check if right file/mime type & get format/content type

            format, content_type = get_file_format_and_content_type(key)

            files.append({
                'key': key,
                'format': format,
                'content_type': content_type,
                'size': obj['Size']
            })

        
    except Exception as e:
        logger.error(f"Error listing files in directory {directory_path}: {e}")

    return files

def create_batch_jsonl(files, prompt_config, bucket):
    jsonl_lines = []

    for file_info in files:
        try:
            record = create_batch_input_record(file_info, prompt_config, bucket)
            jsonl_lines.append(json.dumps(record))
        except Exception as e:
            logger.error(f"Error creating record for {file_info['key']}: {e}")
    
    return '\n'.join(jsonl_lines)

def create_batch_input_record(file_info, prompt_config, bucket):
    record_id = f"{file_info['key'].replace('/','-').replace('.','-')}"

    content = [
        {"type": "text", "text": prompt_config['prompt']}
    ]

    if file_info['content_type'] == 'image':
        content.append({
            "type": "image", 
            "source": {
                "s3Location": {
                    "uri": f"s3://{bucket}/{file_info['key']}"
                }
            }
        })
    
    return {
        "recordId": record_id,
        "modelInput": {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1024,
            "messages": [
                {
                    "role": "user",
                    "content": content
                }
            ]
        }
    }

def get_file_format_and_content_type(file_key):
    _, ext = os.path.splitext(file_key)
    if ext.lower() in SUPPORTED_EXTENSIONS:
        return ext.lower()[1:], 'image'
    else:
        raise ValueError(f"Unsupported file format: {ext}")