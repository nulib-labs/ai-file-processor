import json
import logging
import os
import boto3
from urllib.parse import unquote_plus
from datetime import datetime


logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")
bedrock_client = boto3.client("bedrock", region_name="us-east-1")
stepfunctions_client = boto3.client("stepfunctions", region_name="us-east-1")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET")
STATE_MACHINE_ARN = os.environ.get("STATE_MACHINE_ARN")
SUPPORTED_EXTENSIONS = [".png", ".jpg", ".jpeg"]


def lambda_handler(event, context):
    logger.info("Received event: %s" % json.dumps(event, indent=2))

    # Validate required environment variables
    if not OUTPUT_BUCKET:
        logger.error("OUTPUT_BUCKET environment variable not set")
        return {"statusCode": 500, "body": "Configuration error"}
    if not STATE_MACHINE_ARN:
        logger.error("STATE_MACHINE_ARN environment variable not set")
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

            directory_path = "/".join(key.split("/")[:-1])
            if directory_path:
                directory_path += "/"

            files = list_files_in_directory(bucket, directory_path)
            logger.info(f"Found {len(files)} processable files")

            if not files:
                logger.info("No processable files found in directory.")
                create_status_file(directory_path, "error", "No processable files found", 0, 0)
                continue

            batch_records = create_batch_records(files, prompt_config, bucket)
            batch_file_key = f"{directory_path}_batch_input.json"

            s3_client.put_object(
                Bucket=OUTPUT_BUCKET,
                Key=batch_file_key,
                Body=json.dumps(batch_records),
                ContentType='application/json'
            )

            logger.info(f"Created batch input file: s3://{OUTPUT_BUCKET}/{batch_file_key}")

            execution_name = f"ai-processor-{directory_path.replace('/', '-')}-{int(datetime.now().timestamp())}"

            step_functions_input = {
                "batch_file_key": batch_file_key,
                "directory_path": directory_path,
                "output_bucket": OUTPUT_BUCKET,
            }

            response = stepfunctions_client.start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                name=execution_name,
                input=json.dumps(step_functions_input)
            )

            execution_arn = response['executionArn']
            logger.info(f"Started Step Functions execution: {execution_arn}")

            create_status_file(directory_path, "in_progress", f"Processing {len(files)} files", len(files), 0, execution_arn)

        except Exception as e:
            logger.error(f"Error processing {key}: {e}")
            # Try to create error status file if we can determine directory path
            try:
                directory_path = "/".join(key.split("/")[:-1])
                if directory_path:
                    directory_path += "/"
                create_status_file(directory_path, "error", f"Processing failed: {str(e)}", 0, 0)
            except Exception:
                pass  # Don't fail if we can't create status file

    return {"statusCode": 200, "body": "success"}


def list_files_in_directory(bucket, directory_path):
    files = []

    try:
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=directory_path)
        if "Contents" not in response:
            logger.info("No files in directory")

        for obj in response["Contents"]:
            key = obj["Key"]

            if (
                key.endswith("prompt.json")
                or key.endswith(".json")
                or key.endswith("/")
            ):
                continue

            _, ext = os.path.splitext(key)
            if ext.lower() not in SUPPORTED_EXTENSIONS:
                logger.warning(f"Unsupported file format for {key}, skipping.")
                continue

            format, content_type = get_file_format_and_content_type(key)

            files.append(
                {
                    "key": key,
                    "format": format,
                    "content_type": content_type,
                    "size": obj["Size"],
                }
            )

    except Exception as e:
        logger.error(f"Error listing files in directory {directory_path}: {e}")

    return files


def get_file_format_and_content_type(file_key):
    _, ext = os.path.splitext(file_key)
    return ext.lower()[1:], "image"


def create_processing_record(file_info, prompt_config, bucket):
    record_id = f"{file_info['key'].replace('/', '-').replace('.', '-')}"

    return {
        "recordId": record_id,
        "file_key": file_info["key"],
        "bucket": bucket,
        "prompt": prompt_config["prompt"],
        "file_format": file_info["format"],
        "content_type": file_info["content_type"],
    }


def create_batch_records(files, prompt_config, bucket):
    records = []

    for file_info in files:
        try:
            record = create_processing_record(file_info, prompt_config, bucket)
            records.append(record)
        except Exception as e:
            logger.error(f"Error creating record for {file_info['key']}: {e}")

    return records


def create_status_file(directory_path, status, message, total_files, completed_files, execution_arn=None):
    """Create or update status file in output bucket"""
    status_key = f"{directory_path}_status.json"
    
    status_data = {
        "status": status,
        "message": message,
        "total_files": total_files,
        "completed_files": completed_files,
        "timestamp": datetime.now().isoformat(),
        "directory_path": directory_path
    }
    
    if execution_arn:
        status_data["execution_arn"] = execution_arn
    
    try:
        s3_client.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=status_key,
            Body=json.dumps(status_data, indent=2),
            ContentType='application/json'
        )
        logger.info(f"Created status file: s3://{OUTPUT_BUCKET}/{status_key}")
    except Exception as e:
        logger.error(f"Failed to create status file: {e}")
