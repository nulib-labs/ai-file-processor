import json
import logging
import os
import boto3
from datetime import datetime

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET")


def lambda_handler(event, context):
    """Update status file in output bucket"""
    logger.info(f"Received status update event: {json.dumps(event, indent=2)}")
    
    if not OUTPUT_BUCKET:
        logger.error("OUTPUT_BUCKET environment variable not set")
        return {"statusCode": 500, "body": "Configuration error"}
    
    try:
        directory_path = event["directory_path"]
        status = event["status"]
        message = event["message"]
        execution_arn = event.get("execution_arn")
        error = event.get("error")
        
        # Read current status to get total_files count
        status_key = f"{directory_path}_status.json"
        current_status = {}
        
        try:
            response = s3_client.get_object(Bucket=OUTPUT_BUCKET, Key=status_key)
            current_status = json.loads(response["Body"].read().decode("utf-8"))
        except Exception as e:
            logger.warning(f"Could not read current status file: {e}")
        
        # Update status data
        status_data = {
            "status": status,
            "message": message,
            "total_files": current_status.get("total_files", 0),
            "completed_files": current_status.get("total_files", 0) if status == "completed" else current_status.get("completed_files", 0),
            "timestamp": datetime.now().isoformat(),
            "directory_path": directory_path
        }
        
        if execution_arn:
            status_data["execution_arn"] = execution_arn
            
        if error:
            status_data["error"] = error
        
        # Write updated status file
        s3_client.put_object(
            Bucket=OUTPUT_BUCKET,
            Key=status_key,
            Body=json.dumps(status_data, indent=2),
            ContentType='application/json'
        )
        
        logger.info(f"Updated status file: s3://{OUTPUT_BUCKET}/{status_key} to {status}")
        
        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": f"Status updated to {status}",
                "status_key": status_key
            })
        }
        
    except Exception as e:
        logger.error(f"Error updating status: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }