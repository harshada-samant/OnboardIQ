"""
tests/test_agent.py
--------------------
Validation check utility to verify Bedrock connection works and returns responses.
"""

import os
import sys
import json
from pathlib import Path
import boto3

# Add parent workspace and backend directories to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import load_and_validate_env, get_bedrock_client

AWS_REGION = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
MODEL_ID = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")

# Validate environment
load_and_validate_env()
print("AWS credentials found.")

user_message = "Hello! This is a test message to check if we can connect and get a response."
SYSTEM_PROMPT = "you are a helpful assistant that responds with a JSON of India states and their capitals."

try:
    client = get_bedrock_client()
    
    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "messages": [
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.0
    }
    
    response = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps(payload),
        contentType="application/json",
        accept="application/json",
    )
    
    body = json.loads(response["body"].read())
    raw_response = body["content"][0]["text"]
    
    print("Bedrock Claude response:")
    print(raw_response)
    
except Exception as e:
    print(f"Failed to call AWS Bedrock: {e}")
    sys.exit(1)
