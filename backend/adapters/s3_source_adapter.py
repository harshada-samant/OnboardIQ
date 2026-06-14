import boto3, io, os, logging
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)
SUPPORTED_EXTENSIONS = {'.csv', '.json', '.sql'}


class S3SourceAdapter:
    def __init__(self, bucket: str, prefix: str):
        self.bucket      = bucket
        self.prefix      = prefix.rstrip('/') + '/'
        self.s3          = boto3.client('s3')
        self.failed_keys = []

    def list_source_files(self) -> list[dict]:
        """
        Lists all supported files under self.prefix in the S3 bucket.
        Returns a list of dicts: {name, key, size, extension}.
        Returns empty list on any error — never raises.
        """
        try:
            paginator = self.s3.get_paginator('list_objects_v2')
            files = []
            for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    ext = os.path.splitext(key)[1].lower()
                    if ext in SUPPORTED_EXTENSIONS and obj['Size'] > 0:
                        files.append({'name': os.path.basename(key),
                                      'key':  key,
                                      'size': obj['Size'],
                                      'extension': ext})
            if not files:
                logger.warning('S3 prefix %s returned 0 supported files', self.prefix)
            return files
        except ClientError as e:
            logger.error('S3 list_source_files failed: %s', e)
            return []

    def stream_file(self, key: str) -> io.BytesIO | None:
        """
        Streams one S3 object into an in-memory BytesIO buffer.
        Returns None on failure — never raises.
        Caller must check for None before using the buffer.
        """
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=key)
            buf = io.BytesIO(response['Body'].read())
            buf.seek(0)
            return buf
        except ClientError as e:
            logger.error('S3 stream_file failed for %s: %s', key, e)
            self.failed_keys.append(key)
            return None

    def download_to_tmp(self, key: str) -> str | None:
        """
        Downloads an S3 object to a temp file in /tmp.
        Returns the local file path on success, None on failure.
        IMPORTANT: caller must delete the file in a finally block after use:
            path = adapter.download_to_tmp(key)
            try:
                # use path
            finally:
                if path: os.unlink(path)
        """
        import tempfile
        try:
            suffix = os.path.splitext(key)[1]
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                self.s3.download_fileobj(self.bucket, key, tmp)
                return tmp.name
        except ClientError as e:
            logger.error('S3 download_to_tmp failed for %s: %s', key, e)
            return None

    def generate_presigned_upload_url(self, key: str,
                                       expires_in: int = 300) -> str:
        """
        Generates a presigned S3 PUT URL valid for expires_in seconds (default 5 min).
        The frontend uses this URL to upload a file directly to S3 via HTTP PUT.
        No file bytes pass through the application server.
        """
        return self.s3.generate_presigned_url(
            'put_object',
            Params={
                'Bucket':      self.bucket,
                'Key':         key,
                'ContentType': 'application/octet-stream'
            },
            ExpiresIn=expires_in
        )
