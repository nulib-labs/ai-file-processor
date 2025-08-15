# AI File Processor

A serverless AWS application for batch processing files using Claude AI models. This is a quick and dirty solution designed for rapid analysis of individual files, perfect for generating datasets, extracting structured content from unstructured data, or performing bulk document analysis.

## Overview

The AI File Processor is a serverless system that processes files uploaded to S3 using AWS Bedrock's Claude models. It's designed for use cases like:

- **Dataset Generation**: Convert unstructured documents/images into structured JSON data
- **Content Analysis**: Extract key information from business documents, forms, or receipts
- **Object Recognition**: Identify and catalog objects in images (YMMV)
- **Document Transcription**: Convert handwritten or printed text to digital format
- **Translation**: Translate documents between languages
- **Quick Analysis**: Rapid processing of document batches for research or analysis

## Architecture

```
[S3 Input Bucket] → [Lambda Trigger] → [Step Functions] → [Worker Lambdas] → [S3 Output Bucket]
       ↓                    ↓                ↓                    ↓               ↓
   Upload files         Validates       Distributes         Processes      Results & Status
   + _prompt.json       structure       work in           each file           files
                                       parallel          with Claude
```

### Components

- **Input S3 Bucket**: Upload your files and prompt configuration
- **Trigger Lambda**: Validates structure, prevents duplicates, starts processing
- **Step Functions**: Orchestrates parallel processing of files
- **Worker Lambdas**: Process individual files using Claude via Bedrock
- **Output S3 Bucket**: Contains results and status tracking
- **Status Updates**: Real-time status tracking via JSON files

## Prerequisites

- AWS CLI configured with appropriate permissions
- AWS SAM CLI installed
- Python 3.11+
- Access to AWS Bedrock Claude models in your region

### Required AWS Permissions

Your deployment user needs:
- CloudFormation stack creation/update
- Lambda function creation/management
- S3 bucket creation/management
- Step Functions state machine creation
- IAM role/policy creation
- Bedrock model access

## Deployment

### 1. Clone and Configure

```bash
git clone <repository-url>
cd ai-file-processor
```

### 2. Configure Deployment

Copy and customize the SAM configuration:

```bash
cp samconfig.toml.example samconfig.your-env.toml
```

Edit `samconfig.your-env.toml`:

```toml
[default.deploy.parameters]
stack_name = "your-stack-name"
capabilities = "CAPABILITY_IAM CAPABILITY_NAMED_IAM"
confirm_changeset = true
resolve_s3 = true
parameter_overrides = "StackPrefix=your-prefix ModelId=arn:aws:bedrock:us-east-1:1234567890:inference-profile/us.anthropic.claude-3-5-sonnet-20241022-v2:0 MaxConcurrency=15"
tags = "Environment=production Team=ai-team Project=document-processing CostCenter=engineering"
```

**Deployment Parameters** (set in samconfig.toml):

**Required:**
- **`stack_name`** - (required) Name of CloudFormation stack in AWS
- **`StackPrefix`** - (required) Prefix for resource names in AWS (e.g., "my-company-dev")
- **`ParameterOverrides`** (required)
  - **`ModelId`** - (required)Bedrock model ARN (see "Available Models" below)
  - **`MaxConcurrency`** (optional)(default: 10) - Number of files to process simultaneously (1-1000)
- **`tags`** - (optional) Key-value pairs for AWS resource tagging:
  - Applied to all resources (Lambda functions, S3 buckets, Step Functions, IAM roles)
  - Useful for cost allocation, governance, and resource management
  - Common tags: Environment, Team, Project, CostCenter, Owner

**Available Models** (check Bedrock console for your region):
- You may need to request AWS enable models
- Use the "Inference profile ARN" for the appropriate Claude model located in AWS Console -> Amazon Bedrock -> Infer -> Cross-region inference -> Inference profiles

### 3. Deploy

```bash
# Validate template
sam validate

# Build application
sam build

# Deploy with your configuration
sam deploy --config-file samconfig.your-env.toml

### 4. Note the S3 Bucket Names

After deployment, note the created bucket names:
- Input: `{StackPrefix}-ai-file-processor-input`
- Output: `{StackPrefix}-ai-file-processor-output`

## Usage

### Directory Structure Requirements

Files must be organized in exactly **one level deep** directories:

**✅ VALID:**
```
your-bucket/
├── project1/
│   ├── image1.jpg
│   ├── image2.png
│   └── _prompt.json
└── analysis-batch/
    ├── file1.jpg
    ├── file2.jpeg
    └── _prompt.json
```

**❌ INVALID:**
```
your-bucket/
├── _prompt.json              # Too shallow (root level)
└── project/
    └── subfolder/
        ├── image.jpg
        └── _prompt.json      # Too deep (nested)
```

### Supported File Types

- **Images**: `.png`, `.jpg`, `.jpeg`
- Future support planned for other file types
- **Image Size**: Image files must be under ~3MB each

### Prompt Configuration

Create a `_prompt.json` file:

#### Basic Configuration
```json
{
  "prompt": "Analyze this image and extract key information in JSON format with fields: title, description, objects_detected, and confidence_score."
}
```

#### Advanced Configuration (All Optional Parameters)
```json
{
  "prompt": "Your analysis prompt here",
  "max_tokens": 4096,
  "temperature": 0.2
}
```

**Configuration Parameters:**
- **`prompt`** (required): The instruction for Claude to analyze each file
- **`max_tokens`** (optional, default: 8192): Maximum tokens Claude can generate per response (check limits for your specific model)
- **`temperature`** (optional, default: 0.1): Controls randomness (0.0 = deterministic, 1.0 = very random)

**Example Prompts:**

```json
{
  "prompt": "Extract all text from this document and format as structured JSON with sections for headers, body text, and any numerical data."
}
```

```json
{
  "prompt": "Identify all objects in this image and return a JSON array with object_name, location, and confidence for each detected item."
}
```

```json
{
  "prompt": "Translate this document to English and return both the original text and translation in JSON format."
}
```

**More Advanced Prompts**
```json
{
  "prompt": "This is part of a handwritten correspondence. Please identify whether it is first page, last page, middle page, or single page. First page usually has a salutation and possibly a date, last pages would have a closing, middle pages would have neither, and single page letters would have both a salutation and a closing. Please output in normalized json format. Please include the trasciption of the full document and full english translation if not in english. Also include a short list of topical keywords\n\n```json\njson_data = {\n  \"page_type\": \"first_page\",\n  \"confidence\": \"[Z%]\",\n  \"reasoning\": \"This page contains a date and a line starting with Dear...\", \"transcription\": \"[transcribed text]\", \"english_translation\": \"[translation]\", \"topic_keywords\": [array of keywords] \n}```\n\nPlease include your confidence level and a brief explanation of why you identified the page type. Do not include any text outside of the json itself."
}
```
**Prompt with full custom configuration options**
```json
  {
    "prompt": "Analyze the uploaded document",
    "max_tokens": 4096,
    "temperature": 0.2
  }
```


### Processing Workflow

1. **Upload Files**: Upload your files to the input bucket in a folder
2. **Add Prompt**: Upload `_prompt.json` to trigger processing (**Note:** Upload `_prompt.json` __after__ the image files are uploaded as the `_prompt.json` file triggers the execution using whatever files are currently in the S3 directory.)
3. **Monitor Status**: Check the status file in the output bucket
4. **Retrieve Results**: Download processed results from output bucket

### Example Usage

Bash commands shown, but this can also be done via the AWS console.

```bash
# Upload files to input bucket
aws s3 cp image1.jpg s3://your-prefix-ai-file-processor-input/batch-001/
aws s3 cp image2.png s3://your-prefix-ai-file-processor-input/batch-001/
aws s3 cp document.pdf s3://your-prefix-ai-file-processor-input/batch-001/

# Create and upload prompt file (this triggers processing)
echo '{"prompt": "Extract all text and key information from this document"}' > _prompt.json
aws s3 cp _prompt.json s3://your-prefix-ai-file-processor-input/batch-001/

# Check processing status
aws s3 cp s3://your-prefix-ai-file-processor-output/batch-001/_status.json ./status.json
cat status.json

# Download results when complete
aws s3 sync s3://your-prefix-ai-file-processor-output/batch-001/ ./results/
```

## Status Tracking

The system creates status files in the output bucket to track progress:

### Status File Format (`{directory}_status.json`)

**In Progress:**
```json
{
  "status": "in_progress",
  "message": "Processing 5 files",
  "total_files": 5,
  "completed_files": 0,
  "timestamp": "2025-01-15T10:30:00.123Z",
  "directory_path": "batch-001/",
  "execution_arn": "arn:aws:states:execution:..."
}
```

**Completed with Token Usage:**
```json
{
  "status": "completed",
  "message": "All files processed successfully",
  "total_files": 5,
  "completed_files": 5,
  "successful_files": 4,
  "failed_files": 1,
  "timestamp": "2025-01-15T10:35:00.123Z",
  "directory_path": "batch-001/",
  "execution_arn": "arn:aws:states:execution:...",
  "token_usage": {
    "input_tokens": 1250,
    "output_tokens": 3840,
    "total_tokens": 5090
  }
}
```

### Status Values

- **`in_progress`**: Files are being processed
- **`completed`**: All files processed successfully
- **`error`**: Processing failed (see message for details)

### Additional Fields (when completed)

- **`successful_files`**: Number of files that processed without errors
- **`failed_files`**: Number of files that failed during processing  
- **`token_usage`**: Aggregated token consumption across all successful files
  - **`input_tokens`**: Total tokens sent to Claude (prompts + image data)
  - **`output_tokens`**: Total tokens generated by Claude
  - **`total_tokens`**: Sum of input and output tokens (used for cost calculation)

**Note**: Token usage is aggregated from S3 object metadata, supporting unlimited batch sizes without Step Functions payload limits.

### Common Error Messages

- `"Invalid directory structure"`: Files not in exactly one-level-deep directory
- `"Job output already exists"`: Duplicate job prevention (delete output directory to retry)
- `"No processable files found"`: No supported file types in directory
- `"Processing failed"`: Step Functions execution error

## Output Format

Each processed file generates a `.json` result file:

**Input**: `batch-001/image1.jpg`
**Output**: `batch-001/image1.jpg.json`

### Successful Processing

Example successful result:
```json
{
  "title": "Product Catalog Page",
  "description": "Image showing various electronic devices with pricing",
  "objects_detected": [
    {"name": "smartphone", "confidence": 0.95},
    {"name": "laptop", "confidence": 0.87}
  ],
  "extracted_text": "$299.99, $1,499.99",
  "analysis_timestamp": "2025-01-15T10:35:22Z"
}
```

### Failed Processing

When individual files fail (e.g., file too large, unsupported format), an error file is created:

```json
{
"status": "error",
"error_code": "ValidationException",
"error_message": "messages.0.content.1.image.source.base64: image exceeds 5 MB maximum: 7021200 bytes > 5242880 bytes",
"file_key": "project1/too-big.png",
"record_id": "project1-too-big-png",
"timestamp": "2025-08-15T16:27:00.248755"
}
```

**Important**: Individual file failures don't stop the entire batch. Other files continue processing normally, and the overall status will show "completed" even if some files failed.

## Validation Rules

The system enforces several validation rules:

### ✅ Valid Scenarios

- Directory exactly one level deep: `folder/_prompt.json`
- Supported file types in directory
- Valid JSON in `_prompt.json` with `prompt` field
- No existing output for the directory

### ❌ Invalid Scenarios

- Root level prompt: `_prompt.json`
- Nested directories: `folder/sub/_prompt.json`
- Missing `prompt` field in JSON
- Output directory already exists (prevents duplicates)
- No processable files in directory

## Cost Considerations

- **Bedrock Charges**: Based on input/output tokens per file
- **Lambda Charges**: Minimal for processing orchestration
- **S3 Charges**: Storage and request costs
- **Step Functions**: Per state transition

**Estimated costs** (us-east-1, Claude 3.5 Sonnet):
- ~$0.01-0.05 per image depending on complexity and response length (you should verify this with your actual token usage and current AWS pricing.)

## Limitations

- **File Size**: 
  - Limited by Lambda memory (1GB) and timeout (5 minutes per file)
  - Claude/Bedrock has 5MB limit on images via API and base64 encoding (done in the worker lambda) adds about 33% to the file size, so keep images as small as possible
- **Concurrency**: Default 10 files processed simultaneously (configurable via `MaxConcurrency` deployment parameter)
- **File Types**: Currently jpg and png images only 
- **Region**: Must be deployed in region with Bedrock model access

## Troubleshooting

### Common Issues

1. **"Access Denied" errors**: Check Bedrock model permissions in your region
2. **Files not processing**: Verify directory structure and file types
3. **Status stuck on "in_progress"**: Check Step Functions execution in AWS Console
4. **"Job already exists"**: Delete output directory and retry
5. **Some files failed**: Individual files can fail while batch succeeds - check error files

### Identifying Failed Files

User-defined metadata keys are created on each S3 output file:
- `x-amz-meta-processing-status`: `success` or `error`
- `x-amz-meta-input-tokens`: Number of input tokens consumed
- `x-amz-meta-output-tokens`: Number of output tokens generated  
- `x-amz-meta-total-tokens`: Total tokens for cost calculation

```bash
# Find all error files in a batch - using jq 
# (you might need to install jq if you don't have it)
export BUCKET="your-prefix-ai-file-processor-output"
export PREFIX="batch001"

aws s3api list-objects-v2 \
  --bucket "$BUCKET" \
  --prefix "$PREFIX" \
  --output json | \
jq -r '.Contents[]? | select(.Key | endswith(".json")) | .Key' | \
while read -r key; do
  processing_status=$(aws s3api head-object \
    --bucket "$BUCKET" \
    --key "$key" \
    --query 'Metadata."processing-status"' \
    --output text 2>/dev/null)

  if [ "$processing_status" = "error" ]; then
    echo "$key"
  fi
done

# Download and examine error details
aws s3 cp s3://your-prefix-ai-file-processor-output/batch-001/failed-image.jpg.json ./
cat failed-image.jpg.json
```

### Debugging

```bash
# Check CloudWatch logs
aws logs describe-log-groups --log-group-name-prefix "/aws/lambda/your-prefix"

# View Step Functions execution
aws stepfunctions list-executions --state-machine-arn <your-state-machine-arn>

# Check S3 bucket contents
aws s3 ls s3://your-prefix-ai-file-processor-output/ --recursive
```

## Development

### Local Testing

```bash
# Run unit tests
python -m pytest tests/ -v

# Test individual Lambda functions locally
sam build

# Test trigger function with mock S3 event
# Note: Successful testing requires deployed AWS resources
sam local invoke TriggerFunction -e tests/fixtures/s3_event.json

# Test worker function with mock input
# Note: Successful testing requires deployed AWS resources
sam local invoke WorkerFunction -e tests/fixtures/worker_event.json

# Note: Full integration testing requires deployed AWS resources
# (S3 buckets, Step Functions, Bedrock) which cannot run locally
```

**Limitations of Local Testing:**
- S3 buckets, Step Functions, and Bedrock services must be mocked or deployed
- Full workflow testing requires actual AWS deployment
- Local testing is mainly useful for unit tests and individual function validation

### Configuration Files

- `template.yaml`: CloudFormation/SAM template
- `samconfig.toml`: Generic SAM configuration
- `samconfig.example.toml`: Example environment-specific config

## Security

- All S3 buckets have public access blocked
- IAM roles follow least-privilege principles
- Lambda functions run with minimal required permissions
- No secrets or credentials stored in code

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

This is a quick and dirty solution designed for rapid prototyping. For production use, consider:

- Enhanced error handling and retries
- Support for additional file types
- Batch cost optimization
- Advanced monitoring and alerting
- Input validation and sanitization

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.


