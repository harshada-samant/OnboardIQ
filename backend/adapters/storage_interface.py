import io, os, logging
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {'.csv', '.json', '.sql'}


class StorageBackend(ABC):

    @abstractmethod
    def list_files(self) -> list[dict]:
        """Returns [{name, key, size, extension}]. Never raises — returns [] on error."""

    @abstractmethod
    def read_file(self, key: str) -> io.BytesIO | None:
        """Returns BytesIO of file content. Returns None on failure. Never raises."""

    @abstractmethod
    def read_text_file(self, key: str) -> str | None:
        """Returns file content as string. Returns None on failure. Never raises."""


class LocalStorageBackend(StorageBackend):

    def __init__(self, directory: str):
        self.directory = directory

    def list_files(self) -> list[dict]:
        try:
            results = []
            for name in os.listdir(self.directory):
                ext = os.path.splitext(name)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                path = os.path.join(self.directory, name)
                size = os.path.getsize(path)
                if size == 0:
                    logger.warning('Skipping zero-byte file: %s', name)
                    continue
                results.append({'name': name, 'key': path,
                                 'size': size, 'extension': ext})
            return results
        except Exception as e:
            logger.error('LocalStorageBackend.list_files failed: %s', e)
            return []

    def read_file(self, key: str) -> io.BytesIO | None:
        try:
            with open(key, 'rb') as f:
                buf = io.BytesIO(f.read())
                buf.seek(0)
                return buf
        except Exception as e:
            logger.error('LocalStorageBackend.read_file failed for %s: %s', key, e)
            return None

    def read_text_file(self, key: str) -> str | None:
        try:
            with open(key, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception as e:
            logger.error('LocalStorageBackend.read_text_file failed for %s: %s', key, e)
            return None


class S3StorageBackend(StorageBackend):

    def __init__(self, s3_adapter):
        self.adapter = s3_adapter

    def list_files(self) -> list[dict]:
        files = self.adapter.list_source_files()
        valid = [f for f in files if f.get('size', 0) > 0]
        skipped = len(files) - len(valid)
        if skipped:
            logger.warning('Skipped %d zero-byte S3 objects', skipped)
        return valid

    def read_file(self, key: str) -> io.BytesIO | None:
        return self.adapter.stream_file(key)

    def read_text_file(self, key: str) -> str | None:
        buf = self.adapter.stream_file(key)
        if buf is None:
            return None
        try:
            return buf.read().decode('utf-8', errors='replace')
        except Exception as e:
            logger.error('S3StorageBackend.read_text_file decode failed for %s: %s', key, e)
            return None
