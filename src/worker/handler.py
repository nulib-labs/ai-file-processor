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

