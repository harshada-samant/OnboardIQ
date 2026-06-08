"""
config.py
---------
Centralized configuration, paths, and environment management for OnboardIQ.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Base project paths (absolute)
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "outputs"
INPUT_DIR = DATA_DIR / "sample"
SCHEMAS_DIR = BASE_DIR / "schemas"
DB_PATH = DATA_DIR / "onboardiq.db"
WORKSPACES_DIR = BASE_DIR / "workspaces"

# Specific file paths
TARGET_SCHEMA_PATH = SCHEMAS_DIR / "target_schema.json"
FILE_REGISTRY_PATH = OUTPUT_DIR / "file_registry.json"
CONTEXT_SNAPSHOT_PATH = OUTPUT_DIR / "context_snapshot.json"
QUALITY_REPORT_PATH = OUTPUT_DIR / "quality_report.json"
MAPPING_DOCUMENT_PATH = OUTPUT_DIR / "mapping_document.json"
MIGRATION_SPEC_PATH = OUTPUT_DIR / "migration_spec.json"
MIGRATION_SPEC_MD_PATH = OUTPUT_DIR / "migration_spec.md"
READINESS_REPORT_PATH = OUTPUT_DIR / "readiness_report.json"
READINESS_REPORT_MD_PATH = OUTPUT_DIR / "readiness_report.md"
ONBOARDING_PLAN_PATH = OUTPUT_DIR / "onboarding_plan.json"
ONBOARDING_PLAN_MD_PATH = OUTPUT_DIR / "onboarding_plan.md"

LLM_PROVIDER = "bedrock"

def get_provider_name() -> str:
    return "Groq" if LLM_PROVIDER == "groq" else "Bedrock"


def set_user_workspace(username: str) -> None:
    """
    Dynamically configures active paths (INPUT_DIR, OUTPUT_DIR, and all specific report paths)
    for the specified user's workspace.
    """
    global INPUT_DIR, OUTPUT_DIR, FILE_REGISTRY_PATH, CONTEXT_SNAPSHOT_PATH
    global QUALITY_REPORT_PATH, MAPPING_DOCUMENT_PATH, MIGRATION_SPEC_PATH
    global MIGRATION_SPEC_MD_PATH, READINESS_REPORT_PATH, READINESS_REPORT_MD_PATH
    global ONBOARDING_PLAN_PATH, ONBOARDING_PLAN_MD_PATH
    global SCHEMAS_DIR, TARGET_SCHEMA_PATH
    
    user_workspace_dir = WORKSPACES_DIR / "users" / username
    INPUT_DIR = user_workspace_dir / "uploads"
    OUTPUT_DIR = user_workspace_dir / "outputs"
    SCHEMAS_DIR = user_workspace_dir / "schemas"
    
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    
    TARGET_SCHEMA_PATH = SCHEMAS_DIR / "target_schema.json"
    
    FILE_REGISTRY_PATH = OUTPUT_DIR / "file_registry.json"
    CONTEXT_SNAPSHOT_PATH = OUTPUT_DIR / "context_snapshot.json"
    QUALITY_REPORT_PATH = OUTPUT_DIR / "quality_report.json"
    MAPPING_DOCUMENT_PATH = OUTPUT_DIR / "mapping_document.json"
    MIGRATION_SPEC_PATH = OUTPUT_DIR / "migration_spec.json"
    MIGRATION_SPEC_MD_PATH = OUTPUT_DIR / "migration_spec.md"
    READINESS_REPORT_PATH = OUTPUT_DIR / "readiness_report.json"
    READINESS_REPORT_MD_PATH = OUTPUT_DIR / "readiness_report.md"
    ONBOARDING_PLAN_PATH = OUTPUT_DIR / "onboarding_plan.json"
    ONBOARDING_PLAN_MD_PATH = OUTPUT_DIR / "onboarding_plan.md"


def check_bedrock_connectivity() -> bool:
    """
    Performs a lightweight Bedrock call to verify if credentials/token are fully active.
    """
    import os
    has_keys = os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")
    has_bearer = os.getenv("AWS_BEARER_TOKEN_BEDROCK")
    if not has_keys and not has_bearer:
        return False
        
    try:
        import boto3
        import json
        aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        model_id = os.getenv("AWS_BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        
        kwargs = {
            "service_name": "bedrock-runtime",
            "region_name": aws_region,
        }
        if not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
            if os.getenv("AWS_ACCESS_KEY_ID"):
                kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID")
            if os.getenv("AWS_SECRET_ACCESS_KEY"):
                kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY")
                
        client = boto3.client(**kwargs)
        
        # Make a fast, minimal invocation call (max_tokens=1)
        payload = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1,
            "messages": [{"role": "user", "content": "ping"}]
        }
        client.invoke_model(
            modelId=model_id,
            body=json.dumps(payload),
            contentType="application/json",
            accept="application/json"
        )
        return True
    except Exception as e:
        print(f"[config] AWS Bedrock connectivity check failed: {e}")
        return False


def load_and_validate_env(verbose: bool = False) -> None:
    """
    Loads environment variables from .env and validates required AWS/Bedrock or Groq credentials.
    """
    global LLM_PROVIDER
    env_path = BASE_DIR / ".env"
    loaded = load_dotenv(dotenv_path=env_path)
    if not loaded and verbose:
        print(f"[Warning] .env file not found at: {env_path}")
        
    # Map AWS_BEARER_TOKEN to AWS_BEARER_TOKEN_BEDROCK if present
    bearer_token = os.getenv("AWS_BEARER_TOKEN")
    if bearer_token:
        os.environ["AWS_BEARER_TOKEN_BEDROCK"] = bearer_token

    has_bearer = os.getenv("AWS_BEARER_TOKEN_BEDROCK")

    # If bearer token is present, clear the quarantined/blocked keys from the active environment
    # to force boto3 to use bearer token auth.
    if has_bearer:
        os.environ.pop("AWS_ACCESS_KEY_ID", None)
        os.environ.pop("AWS_SECRET_ACCESS_KEY", None)

    has_keys = os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")
    has_groq = os.getenv("GROQ_API_KEY")

    if not has_keys and not has_bearer and not has_groq:
        raise EnvironmentError(
            "AWS or Groq credentials missing. Provide either AWS_ACCESS_KEY_ID & AWS_SECRET_ACCESS_KEY, AWS_BEARER_TOKEN, or GROQ_API_KEY in environment/.env."
        )

    # Perform connectivity check once at startup
    if has_keys or has_bearer:
        print("[config] Testing AWS Bedrock connectivity...")
        if check_bedrock_connectivity():
            LLM_PROVIDER = "bedrock"
            print("[config] AWS Bedrock connectivity test passed. Using Bedrock.")
        else:
            if has_groq:
                LLM_PROVIDER = "groq"
                print("[config] AWS Bedrock connectivity test failed. Switching LLM_PROVIDER directly to Groq.")
            else:
                LLM_PROVIDER = "bedrock"
                print("[config] AWS Bedrock connectivity test failed and no GROQ_API_KEY available. Keeping Bedrock.")
    else:
        if has_groq:
            LLM_PROVIDER = "groq"
            print("[config] No AWS credentials. Using Groq.")


class BedrockOrGroqClientWrapper:
    """
    Wrapper for Bedrock Runtime client that automatically falls back to Groq
    if Bedrock execution fails (e.g. AccessDeniedException / quarantine locks).
    Supports direct Groq completions bypassing Bedrock when LLM_PROVIDER is set to 'groq'.
    """
    def __init__(self, bedrock_client):
        self.bedrock_client = bedrock_client

    def invoke_model(self, modelId, body, contentType="application/json", accept="application/json"):
        import os

        # Check if we should directly use Groq
        if LLM_PROVIDER == "groq":
            groq_key = os.getenv("GROQ_API_KEY")
            if groq_key:
                return self._invoke_groq(body, modelId, groq_key)

        # 1. Try standard AWS Bedrock
        try:
            if self.bedrock_client is None:
                raise ValueError("AWS Bedrock client is not initialized.")
            return self.bedrock_client.invoke_model(
                modelId=modelId,
                body=body,
                contentType=contentType,
                accept=accept
            )
        except Exception as e:
            print(f"[LLM_FALLBACK] AWS Bedrock call failed: {e}")
            groq_key = os.getenv("GROQ_API_KEY")
            if not groq_key:
                print("[LLM_FALLBACK] No GROQ_API_KEY found in environment. Raising original Bedrock error.")
                raise e

            print("[LLM_FALLBACK] Falling back to Groq completions...")
            return self._invoke_groq(body, modelId, groq_key)

    def _invoke_groq(self, body, modelId, groq_key):
        import json
        import os

        # 1. Parse the Bedrock Anthropic payload
        try:
            payload = json.loads(body) if isinstance(body, str) else json.loads(body.decode('utf-8'))
        except Exception as parse_err:
            print(f"[LLM_FALLBACK] Failed to parse Bedrock payload: {parse_err}")
            raise parse_err

        system_prompt = payload.get("system")
        messages_list = payload.get("messages", [])
        temperature = payload.get("temperature", 0.0)
        max_tokens = payload.get("max_tokens", 4096)

        # Map system prompt & messages to Groq structure
        groq_messages = []
        if system_prompt:
            groq_messages.append({"role": "system", "content": system_prompt})
        for msg in messages_list:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            groq_messages.append({"role": role, "content": content})

        # Use Llama 3.3 70b as the default, or another configured model
        groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

        # 2. Call Groq Completion API
        try:
            from groq import Groq
            groq_client = Groq(api_key=groq_key)
            completion = groq_client.chat.completions.create(
                messages=groq_messages,
                model=groq_model,
                temperature=temperature,
                max_tokens=max_tokens
            )
            response_text = completion.choices[0].message.content
            print(f"[LLM_FALLBACK] Groq completed successfully. Model: {groq_model}")
        except Exception as groq_err:
            print(f"[LLM_FALLBACK] Groq call also failed: {groq_err}")
            raise groq_err

        # 3. Mock the Bedrock response structure
        class MockBytesIO:
            def __init__(self, data_bytes):
                self.data_bytes = data_bytes
            def read(self):
                return self.data_bytes

        mock_response = {
            "body": MockBytesIO(json.dumps({
                "content": [
                    {
                        "text": response_text
                    }
                ]
            }).encode('utf-8'))
        }
        return mock_response


def get_bedrock_client():
    """
    Returns an initialized BedrockOrGroqClientWrapper based on loaded credentials.
    """
    bedrock_client = None
    has_keys = os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY")
    has_bearer = os.getenv("AWS_BEARER_TOKEN_BEDROCK")

    if has_keys or has_bearer:
        try:
            import boto3
            aws_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
            kwargs = {
                "service_name": "bedrock-runtime",
                "region_name": aws_region,
            }
            # If Bedrock bearer token is present, let boto3 handle it from environment
            if not os.getenv("AWS_BEARER_TOKEN_BEDROCK"):
                if os.getenv("AWS_ACCESS_KEY_ID"):
                    kwargs["aws_access_key_id"] = os.getenv("AWS_ACCESS_KEY_ID")
                if os.getenv("AWS_SECRET_ACCESS_KEY"):
                    kwargs["aws_secret_access_key"] = os.getenv("AWS_SECRET_ACCESS_KEY")

            bedrock_client = boto3.client(**kwargs)
        except Exception as e:
            print(f"[config] Warning: Failed to initialize standard Bedrock client: {e}")

    return BedrockOrGroqClientWrapper(bedrock_client)
