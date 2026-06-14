"""
S3 smoke test for the source-reading path through the full agent chain.

This test:
- uses USE_S3_SOURCE=true
- reads files from s3://<bucket>/inputs/user1/test_job_1/
- injects context['_storage'] with S3StorageBackend
- verifies payload_builder does not perform direct file reads via open()
- runs payload_builder, then discovery, profiling, mapping, specification,
  readiness, and planning in order
- stops on the first failure and prints a final summary
"""

import builtins
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
os.environ["USE_S3_SOURCE"] = "true"

root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

import config
from backend.adapters.s3_source_adapter import S3SourceAdapter
from backend.adapters.storage_interface import S3StorageBackend
from backend.agents.discovery_agent import run_discovery_agent
from backend.agents.profiling_agent import run_profiling_agent
from backend.agents.mapping_agent import run_mapping_agent
from backend.agents.specification_agent import run_specification_agent
from backend.agents.readiness_agent import run_readiness_agent
from backend.agents.planning_agent import run_planning_agent
from backend.agents import payload_builder


USERNAME = "user1"
JOB_ID = "test_job_1"


def _guarded_open(file, mode="r", *args, **kwargs):
    """
    Allow writes to outputs, but fail if payload_builder tries to read source files directly.
    """
    path = Path(file)
    if "r" in mode and config.OUTPUT_DIR not in path.parents:
        raise AssertionError(f"Direct file read detected via open(): {path}")
    return _ORIGINAL_OPEN(file, mode, *args, **kwargs)


_ORIGINAL_OPEN = builtins.open
payload_builder.open = _guarded_open


def main() -> int:
    passed = []
    failed = []

    print("=" * 60)
    print("[agent] payload_builder")
    print("=" * 60)

    bucket = os.getenv("S3_BUCKET", "")
    if not bucket:
        raise ValueError("S3_BUCKET is not set in .env")

    prefix = config.s3_input_prefix(USERNAME, JOB_ID)
    s3_adapter = S3SourceAdapter(bucket, prefix)
    storage = S3StorageBackend(s3_adapter)
    files = storage.list_files()

    print(f"Source prefix: s3://{bucket}/{prefix}")
    print(f"Files found: {len(files)}")
    if files:
        print("Keys:")
        for entry in files:
            print(f"  - {entry['key']}")

    if not files:
        raise ValueError(f"No source files found under s3://{bucket}/{prefix}")

    context = {
        "_storage": storage,
        "source_files": [entry["key"] for entry in files],
    }

    print(f"Running payload_builder with {len(context['source_files'])} source key(s)...")
    try:
        payload = payload_builder.build_context_payload(context["source_files"], context=context)
        print(f"[agent] payload_builder succeeded: {len(payload.get('files', []))} logical file(s)")
        print("[check] Source files were read through context['_storage'] only.")
        print(f"[check] context.get('_storage') after payload_builder: {context.get('_storage')}")
    except Exception as e:
        print(f"[agent] payload_builder FAILED: {e}")
        failed.append(("payload_builder", str(e)))
        print("\nSummary")
        print("Passed: []")
        print(f"Failed: {[name for name, _ in failed]}")
        return 1

    passed.append("payload_builder")

    agent_steps = [
        ("discovery", run_discovery_agent, (context["source_files"], context), {"verbose": True}),
        ("profiling", run_profiling_agent, (context,), {"verbose": True}),
        ("mapping", run_mapping_agent, (context,), {"verbose": True}),
        ("specification", run_specification_agent, (context,), {"verbose": True}),
        ("readiness", run_readiness_agent, (context,), {"verbose": True}),
        ("planning", run_planning_agent, (context,), {"verbose": True}),
    ]

    for name, func, args, kwargs in agent_steps:
        print(f"\n[agent] {name}")
        print(f"[check] type(context['_storage']) before {name}: {type(context.get('_storage'))}")
        try:
            result = func(*args, **kwargs)
            print(f"[agent] {name} succeeded")
            passed.append(name)
        except Exception as e:
            print(f"[agent] {name} FAILED: {e}")
            failed.append((name, str(e)))
            break

    print("\nSummary")
    print(f"Passed: {passed}")
    print(f"Failed: {[name for name, _ in failed]}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
