import json
import logging
import os
import boto3
from datetime import datetime
from botocore.exceptions import ClientError

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
        model_input = record['modelInput']
        record_id = record['recordId']

        logger.info(f"Processing {record_id} from {file_key}")

        response = bedrock_runtime.converse(
            modelId=MODEL_ID,
            messages = model_input['messages'],
            inferenceConfig = model_input['inferenceConfig']
        )

        print(response['output']['message']['content'][0]['text'])

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        logger.error(f"AWS Error processing {record.get('recordId', 'unknown')}: {error_code} - {error_message}")
        
        error_result = {
            "file_key": record.get('file_key', 'unknown'),
            "record_id": record.get('recordId', 'unknown'),
            # "timestamp": datetime.datetime.now(datetime.timezone.utc),
            "status": "error",
            "error_code": error_code,
            "error_message": error_message
        }

