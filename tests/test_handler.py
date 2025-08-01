import json
import pytest
from unittest.mock import patch, MagicMock
import sys
import os

# Set environment variables before importing handler
os.environ['OUTPUT_BUCKET'] = "output-bucket-test" 
os.environ['BEDROCK_ROLE_ARN'] = 'arn:1234567'
os.environ['MODEL_ID'] = 'model_id'

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'trigger'))
from handler import lambda_handler

class TestLambdaHandler:
    
    def load_fixture(self, filename):
        fixture_path = os.path.join(os.path.dirname(__file__), 'fixtures', filename)
        with open(fixture_path, 'r') as f:
            return json.load(f)
    
    def test_lambda_handler_success(self):
        event = self.load_fixture('s3_event.json')
        sample_prompt = self.load_fixture('sample_prompt.json')
        
        mock_response = {
            'Body': MagicMock()
        }
        mock_response['Body'].read.return_value = json.dumps(sample_prompt).encode('utf-8')
        
        with patch('handler.s3_client.get_object') as mock_get_object:
            mock_get_object.return_value = mock_response
            
            result = lambda_handler(event, {})
            
            assert result['statusCode'] == 200
            assert result['body'] == 'success'
            mock_get_object.assert_called_once_with(
                Bucket='test-ai-file-processor-input',
                Key='prompt.json'
            )
    
    def test_lambda_handler_invalid_json(self):
        """Test handling of invalid JSON in S3 object"""
        event = self.load_fixture('s3_event.json')
        
        mock_response = {
            'Body': MagicMock()
        }
        mock_response['Body'].read.return_value = b'invalid json content'
        
        with patch('handler.s3_client.get_object') as mock_get_object:
            mock_get_object.return_value = mock_response
            
            result = lambda_handler(event, {})
            
            assert result['statusCode'] == 200
            assert result['body'] == 'success'
    
    def test_lambda_handler_s3_error(self):
        """Test handling of S3 access errors"""
        event = self.load_fixture('s3_event.json')
        
        with patch('handler.s3_client.get_object') as mock_get_object:
            mock_get_object.side_effect = Exception('S3 access denied')
            
            result = lambda_handler(event, {})
            
            assert result['statusCode'] == 200
            assert result['body'] == 'success'
    
    def test_lambda_handler_missing_prompt_field(self):
        """Test handling of JSON without prompt field"""
        event = self.load_fixture('s3_event.json')
        
        invalid_prompt = {"model": "claude-3-sonnet"}
        mock_response = {
            'Body': MagicMock()
        }
        mock_response['Body'].read.return_value = json.dumps(invalid_prompt).encode('utf-8')
        
        with patch('handler.s3_client.get_object') as mock_get_object:
            mock_get_object.return_value = mock_response
            
            result = lambda_handler(event, {})
            
            assert result['statusCode'] == 200
            assert result['body'] == 'success'


if __name__ == '__main__':
    pytest.main([__file__])