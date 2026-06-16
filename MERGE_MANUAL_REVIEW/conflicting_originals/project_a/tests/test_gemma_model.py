import os
import sys
import json
import boto3
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding='utf-8')
load_dotenv()

aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
client = boto3.client(
    "bedrock-runtime",
    region_name=aws_region,
    aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
)

response = client.invoke_model(
    modelId="google.gemma-3-4b-it",
    body=json.dumps({
        "messages": [
            {"role": "user", "content": "Say hello!"}
        ]
    }),
    contentType="application/json",
    accept="application/json"
)

result = json.loads(response["body"].read())
print(result)
