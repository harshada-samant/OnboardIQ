import importlib.util
import tempfile
import uuid
from pathlib import Path
from unittest import mock

import pytest


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "workspaces" / "users" / "user1" / "outputs" / "migration" / "duckdb" / "user" / "migrate_user.py"
ROOT_DIR = Path("d:/obq_git/_tmp")


def _make_test_dir(prefix: str) -> Path:
    temp_dir = ROOT_DIR / f"{prefix}_{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True, exist_ok=False)
    return temp_dir


def _load_script_module():
    spec = importlib.util.spec_from_file_location("migrate_user_script", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class FakeDuckDBConnection:
    def __init__(self, fail_on_insert: bool = False, fail_on_rollback: bool = False):
        self.fail_on_insert = fail_on_insert
        self.fail_on_rollback = fail_on_rollback
        self.executed = []
        self.closed = False

    def execute(self, sql, params=None):
        self.executed.append(sql)
        sql_text = str(sql)
        if sql_text == "ROLLBACK" and self.fail_on_rollback:
            raise RuntimeError("cannot rollback - no transaction is active")
        if "INSERT INTO Users" in sql_text and self.fail_on_insert:
            raise RuntimeError("original write failure")
        if "SELECT COUNT(*) FROM staging" in sql_text:
            return FakeResult((0,))
        if "SELECT COUNT(*) FROM Users" in sql_text:
            return FakeResult((0,))
        return self

    def close(self):
        self.closed = True


class FakeResult:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


def test_user_script_fails_fast_before_connect(monkeypatch):
    module = _load_script_module()

    temp_dir = _make_test_dir("fail_fast")
    (temp_dir / "users.csv").write_text("user_id,name\nU1,Ada", encoding="utf-8")

    monkeypatch.setenv("DUCKDB_PATH", str(temp_dir / "test.duckdb"))
    monkeypatch.delenv("SOURCE_DATA_DIR", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_PREFIX", raising=False)

    connect_mock = mock.Mock(side_effect=AssertionError("duckdb.connect should not be called"))
    monkeypatch.setattr(module.duckdb, "connect", connect_mock)

    with pytest.raises(RuntimeError, match="Missing SOURCE_DATA_DIR and S3_BUCKET/S3_PREFIX"):
        module.main()

    connect_mock.assert_not_called()


def test_user_script_preserves_original_error_when_rollback_fails(monkeypatch):
    module = _load_script_module()

    temp_dir = _make_test_dir("rollback")
    (temp_dir / "users.csv").write_text("user_id,name\nU1,Ada", encoding="utf-8")

    monkeypatch.setenv("DUCKDB_PATH", str(temp_dir / "test.duckdb"))
    monkeypatch.setenv("SOURCE_DATA_DIR", str(temp_dir))
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_PREFIX", raising=False)

    fake_conn = FakeDuckDBConnection(fail_on_insert=True, fail_on_rollback=True)
    monkeypatch.setattr(module.duckdb, "connect", mock.Mock(return_value=fake_conn))

    with pytest.raises(RuntimeError, match="original write failure"):
        module.main()

    assert "ROLLBACK" in fake_conn.executed
    assert fake_conn.closed is True
