"""
Quick connectivity test for S3SourceAdapter.
Tests real AWS connectivity — requires valid credentials in .env and an existing S3 bucket.
Run with: python tests/test_s3_adapter.py
"""

import os, sys
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from backend.adapters.s3_source_adapter import S3SourceAdapter

BUCKET = os.getenv('S3_BUCKET', '')
PREFIX = os.getenv('S3_TEST_PREFIX', 'inputs/test/')

def test_1_credentials_and_bucket():
    print("\n[1] Checking AWS credentials and bucket access...")
    assert BUCKET, "S3_BUCKET not set in .env"
    adapter = S3SourceAdapter(BUCKET, PREFIX)
    files = adapter.list_source_files()
    print(f"    ✅ Connected to bucket: {BUCKET}")
    print(f"    ✅ list_source_files() returned {len(files)} file(s) under prefix '{PREFIX}'")
    return adapter

def test_2_stream_file(adapter):
    print("\n[2] Checking stream_file()...")
    files = adapter.list_source_files()
    if not files:
        print("    ⚠️  No files found under prefix — skipping stream test.")
        print(f"    Upload a .csv/.json/.sql file to s3://{BUCKET}/{PREFIX} to test streaming.")
        return
    key = files[0]['key']
    buf = adapter.stream_file(key)
    assert buf is not None, f"stream_file returned None for {key}"
    content = buf.read()
    assert len(content) > 0, "stream_file returned empty buffer"
    print(f"    ✅ Streamed {len(content)} bytes from '{key}'")

def test_3_presigned_url(adapter):
    print("\n[3] Checking presigned URL generation...")
    test_key = f"{PREFIX}test_upload.csv"
    url = adapter.generate_presigned_upload_url(test_key, expires_in=60)
    assert url.startswith('https://'), "Presigned URL does not start with https"
    assert BUCKET in url, "Bucket name not in presigned URL"
    print(f"    ✅ Presigned URL generated successfully")
    print(f"    URL prefix: {url[:80]}...")

def test_4_missing_key_returns_none(adapter):
    print("\n[4] Checking stream_file() returns None for missing key...")
    result = adapter.stream_file('nonexistent/path/fake_file.csv')
    assert result is None, "Expected None for missing key but got a result"
    print("    ✅ Missing key correctly returned None — no exception raised")

if __name__ == '__main__':
    print("=" * 50)
    print("obq — S3SourceAdapter Connectivity Test")
    print("=" * 50)
    try:
        adapter = test_1_credentials_and_bucket()
        test_2_stream_file(adapter)
        test_3_presigned_url(adapter)
        test_4_missing_key_returns_none(adapter)
        print("\n✅ All tests passed — S3 adapter is working correctly.")
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        sys.exit(1)
