"""Tests for apps/dashboard/settings_config.py."""

import shutil
import tempfile
from pathlib import Path

import pytest

from apps.dashboard.settings_config import (
    PROJECT_MARKERS,
    read_env,
    resolve_project_root,
    write_env,
)


class TestResolveProjectRoot:

    def test_from_apps_dashboard_pages(self):
        project_root = Path(__file__).resolve().parents[1]
        start = project_root / "apps" / "dashboard" / "pages"
        root = resolve_project_root(start)
        assert any((root / m).exists() for m in PROJECT_MARKERS)

    def test_from_apps_dir(self):
        project_root = Path(__file__).resolve().parents[1]
        start = project_root / "apps"
        root = resolve_project_root(start)
        assert any((root / m).exists() for m in PROJECT_MARKERS)

    def test_raises_on_no_marker(self):
        tmpdir = tempfile.mkdtemp()
        try:
            nested = Path(tmpdir) / "a" / "b" / "c"
            nested.mkdir(parents=True)
            with pytest.raises(FileNotFoundError):
                resolve_project_root(nested)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestReadEnv:

    def test_reads_simple_kv(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("FOO=bar\nBAZ=123\n", encoding="utf-8")
            assert read_env(f) == {"FOO": "bar", "BAZ": "123"}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_skips_comments_and_blanks(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("# comment\n\nFOO=bar\n", encoding="utf-8")
            assert read_env(f) == {"FOO": "bar"}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_empty_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("", encoding="utf-8")
            assert read_env(f) == {}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_nonexistent_file(self):
        tmpdir = tempfile.mkdtemp()
        try:
            assert read_env(Path(tmpdir) / "nope.env") == {}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_value_with_equals(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("URL=http://x.com?a=b\n", encoding="utf-8")
            assert read_env(f)["URL"] == "http://x.com?a=b"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestWriteEnv:

    def test_updates_existing_key(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("FOO=old\nBAR=keep\n", encoding="utf-8")
            write_env(f, {"FOO": "new"}, set())
            r = read_env(f)
            assert r["FOO"] == "new"
            assert r["BAR"] == "keep"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_appends_new_key(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("FOO=1\n", encoding="utf-8")
            write_env(f, {"NEW_KEY": "hello"}, set())
            r = read_env(f)
            assert r["NEW_KEY"] == "hello"
            assert r["FOO"] == "1"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_sensitive_mask_not_overwritten(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("SECRET=real_value\n", encoding="utf-8")
            write_env(f, {"SECRET": "****"}, {"SECRET"})
            assert read_env(f)["SECRET"] == "real_value"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_sensitive_empty_not_overwritten(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("SECRET=real_value\n", encoding="utf-8")
            write_env(f, {"SECRET": ""}, {"SECRET"})
            assert read_env(f)["SECRET"] == "real_value"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_sensitive_real_value_is_written(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("SECRET=old\n", encoding="utf-8")
            write_env(f, {"SECRET": "new_secret"}, {"SECRET"})
            assert read_env(f)["SECRET"] == "new_secret"
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_preserves_comments_and_blanks(self):
        tmpdir = tempfile.mkdtemp()
        try:
            f = Path(tmpdir) / ".env"
            f.write_text("# header\n\nFOO=1\n# middle\nBAR=2\n", encoding="utf-8")
            write_env(f, {"FOO": "updated"}, set())
            content = f.read_text(encoding="utf-8")
            assert "# header" in content
            assert "# middle" in content
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_no_op_when_file_missing(self):
        tmpdir = tempfile.mkdtemp()
        try:
            write_env(Path(tmpdir) / "nope.env", {"X": "1"}, set())
            assert not (Path(tmpdir) / "nope.env").exists()
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
