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
        
        # Aggregate token usage from S3 metadata if status is completed
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0
        successful_files = 0
        failed_files = 0
        
        if status == "completed":
            try:
                # List all JSON files in the directory
                response = s3_client.list_objects_v2(
                    Bucket=OUTPUT_BUCKET,
                    Prefix=directory_path
                )
                
                if 'Contents' in response:
                    for obj in response['Contents']:
                        if obj['Key'].endswith('.json') and not obj['Key'].endswith('_status.json'):
                            try:
                                # Get metadata for each output file
                                head_response = s3_client.head_object(
                                    Bucket=OUTPUT_BUCKET,
                                    Key=obj['Key']
                                )
                                
                                metadata = head_response.get('Metadata', {})
                                
                                # Aggregate token counts
                                total_input_tokens += int(metadata.get('input-tokens', 0))
                                total_output_tokens += int(metadata.get('output-tokens', 0))
                                total_tokens += int(metadata.get('total-tokens', 0))
                                
                                # Count success/failure
                                if metadata.get('processing-status') == 'success':
                                    successful_files += 1
                                elif metadata.get('processing-status') == 'error':
                                    failed_files += 1
                                    
                            except Exception as e:
                                logger.warning(f"Could not read metadata for {obj['Key']}: {e}")
                
                logger.info(f"Token usage aggregated - Input: {total_input_tokens}, Output: {total_output_tokens}, Total: {total_tokens}")
                logger.info(f"File processing results - Successful: {successful_files}, Failed: {failed_files}")
                
            except Exception as e:
                logger.error(f"Error aggregating token usage: {e}")
        
        # Update status data
        status_data = {
            "status": status,
            "message": message,
            "total_files": current_status.get("total_files", 0),
            "completed_files": current_status.get("total_files", 0) if status == "completed" else current_status.get("completed_files", 0),
            "timestamp": datetime.now().isoformat(),
            "directory_path": directory_path
        }
        
        # Add detailed results if we have them
        if status == "completed" and (successful_files > 0 or failed_files > 0):
            status_data["successful_files"] = successful_files
            status_data["failed_files"] = failed_files
            
            # Add token usage if we have any
            if total_tokens > 0:
                status_data["token_usage"] = {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_tokens
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