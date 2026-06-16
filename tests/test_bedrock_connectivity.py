"""
Quick connectivity test for OnboardIQ LLM setup.

Usage:
  python test_bedrock_connectivity.py

Exit codes:
  0 = Bedrock connectivity OK
  1 = Bedrock connectivity failed
  2 = Environment validation failed
"""

import sys
import json
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))


import config


def main() -> int:
    try:
        # Loads .env and configures provider selection logic.
        config.load_and_validate_env(verbose=True)
    except Exception as exc:
        print(f"[ERROR] Environment validation failed: {exc}")
        return 2

    print(f"[INFO] Active provider after validation: {config.get_provider_name()}")

    ok = config.check_bedrock_connectivity()
    if ok:
        print("[PASS] AWS Bedrock connectivity is working.")
        return 0

    print("[FAIL] AWS Bedrock connectivity failed.")
    print("[HINT] Verify AWS_BEARER_TOKEN_BEDROCK (or AWS_BEARER_TOKEN), AWS region, and model access.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
