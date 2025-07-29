import json
import logging
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")

def lambda_handler(event, context):
    logger.info("Received event: %s" % json.dumps(event, indent=2))

    for record in event["Records"]:
        bucket = record["s3"]["bucket"]["name"]
        key = record["s3"]["object"]["key"]

        print(f"bucket: {bucket}, key: {key}")

        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            file_content = response["Body"].read().decode("utf-8")
            json_data = json.loads(file_content)

            print(f"prompt: {json_data['prompt']}")
        except Exception as e:
            print(f"Error reading object: {key}: {e}")

    return {"statusCode": 200, "body": "success"}
