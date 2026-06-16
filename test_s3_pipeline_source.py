"""
Tests S3 source reading end-to-end through StorageBackend.
Requires: valid AWS credentials in .env, S3 bucket with at least one file.
Run: python test_s3_pipeline_source.py
"""
import os, sys
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from backend.adapters.s3_source_adapter import S3SourceAdapter
from backend.adapters.storage_interface import S3StorageBackend, LocalStorageBackend

BUCKET   = os.getenv('S3_BUCKET', '')
USERNAME = 'user1'
JOB_ID   = 'test_job_1'

def test_1_local_backend():
    print('\n[1] LocalStorageBackend...')
    backend = LocalStorageBackend(config.INPUT_DIR)
    files = backend.list_files()
    print(f'    files found: {len(files)}')
    for f in files:
        buf = backend.read_file(f['key'])
        assert buf is not None, f'read_file returned None for {f["name"]}'
    print('    OK')

def test_2_s3_backend():
    print('\n[2] S3StorageBackend...')
    assert BUCKET, 'S3_BUCKET not set in .env'
    prefix  = config.s3_input_prefix(USERNAME, JOB_ID)
    s3      = S3SourceAdapter(BUCKET, prefix)
    backend = S3StorageBackend(s3)
    files   = backend.list_files()
    print(f'    files found at {prefix}: {len(files)}')
    for f in files:
        buf = backend.read_file(f['key'])
        assert buf is not None, f'read_file returned None for {f["name"]}'
        content = buf.read()
        assert len(content) > 0, f'empty content for {f["name"]}'
        print(f'    streamed {f["name"]}: {len(content)} bytes')
    print('    OK')

def test_3_missing_key_returns_none():
    print('\n[3] Missing S3 key returns None...')
    s3      = S3SourceAdapter(BUCKET, 'inputs/fake/path/')
    backend = S3StorageBackend(s3)
    result  = backend.read_file('inputs/fake/path/nonexistent.csv')
    assert result is None
    print('    OK')

def test_4_empty_prefix_returns_empty_list():
    print('\n[4] Empty S3 prefix returns empty list...')
    s3      = S3SourceAdapter(BUCKET, 'inputs/empty/prefix/')
    backend = S3StorageBackend(s3)
    files   = backend.list_files()
    assert files == []
    print('    OK')

if __name__ == '__main__':
    print('=' * 50)
    print('obq S3 source pipeline test')
    print('=' * 50)
    try:
        test_1_local_backend()
        test_2_s3_backend()
        test_3_missing_key_returns_none()
        test_4_empty_prefix_returns_empty_list()
        print('\nAll tests passed.')
    except Exception as e:
        print(f'\nFAILED: {e}')
        sys.exit(1)