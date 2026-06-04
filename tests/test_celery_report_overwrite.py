"""Verify _generate_and_store_reports behavior on retry and edge cases.

Tests cover:
- Always overwrites existing destination files (retry correctness)
- Skips missing source files with a warning (defensive guard)
- PDF None return handled gracefully
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from apps.api.task_manager.celery_tasks import PROJECT_ROOT, _generate_and_store_reports


@pytest.fixture()
def reports_dir(tmp_path, monkeypatch):
    """Point storage/reports/<task_id> to a temp directory."""
    monkeypatch.setattr(
        "apps.api.task_manager.celery_tasks.PROJECT_ROOT", tmp_path
    )
    return tmp_path / "storage" / "reports" / "test-task-001"


@pytest.fixture()
def mock_builders(tmp_path):
    """Create minimal temp files that the builders would produce."""
    json_file = tmp_path / "result.json"
    md_file = tmp_path / "report.md"
    html_file = tmp_path / "report.html"
    pdf_file = tmp_path / "report.pdf"

    json_file.write_text(json.dumps({"score": 80}))
    md_file.write_text("# Report")
    html_file.write_text("<html>report</html>")
    pdf_file.write_bytes(b"%PDF-1.4 fake")

    return json_file, md_file, html_file, pdf_file


def _patch_builders(mock_builders):
    """Return a dict of patches for the four builder functions."""
    json_file, md_file, html_file, pdf_file = mock_builders

    return {
        "save_json_result": lambda result: str(json_file),
        "save_markdown_report": lambda result, template_config=None: str(md_file),
        "save_html_report": lambda md_path, theme=None: str(html_file),
        "save_pdf_report_with_playwright": lambda html_path: str(pdf_file),
    }


class TestReportOverwrite:
    """Reports must always be overwritten on retry, not guarded by dst.exists()."""

    def test_overwrites_existing_json_md_html(self, reports_dir, mock_builders, monkeypatch):
        """Pre-existing JSON/MD/HTML files are overwritten with fresh content."""
        reports_dir.mkdir(parents=True, exist_ok=True)

        # Write stale/corrupt content
        stale_json = reports_dir / "result.json"
        stale_json.write_text("CORRUPT JSON")

        stale_md = reports_dir / "report.md"
        stale_md.write_text("CORRUPT MD")

        stale_html = reports_dir / "report.html"
        stale_html.write_text("CORRUPT HTML")

        patches = _patch_builders(mock_builders)
        with (
            patch("services.report.json_builder.save_json_result", patches["save_json_result"]),
            patch("services.report.markdown_builder.save_markdown_report", patches["save_markdown_report"]),
            patch("services.report.html_builder.save_html_report", patches["save_html_report"]),
            patch("services.report.pdf_builder_playwright.save_pdf_report_with_playwright", patches["save_pdf_report_with_playwright"]),
        ):
            result = _generate_and_store_reports({"score": 80}, "test-task-001")

        # Files should contain fresh content, not stale
        assert json.loads((reports_dir / "result.json").read_text()) == {"score": 80}
        assert (reports_dir / "report.md").read_text() == "# Report"
        assert (reports_dir / "report.html").read_text() == "<html>report</html>"
        # report_paths contains all 4 keys
        assert set(result.keys()) == {"json", "markdown", "html", "pdf"}

    def test_overwrites_existing_pdf(self, reports_dir, mock_builders, monkeypatch):
        """Pre-existing PDF is overwritten with fresh content."""
        reports_dir.mkdir(parents=True, exist_ok=True)

        stale_pdf = reports_dir / "report.pdf"
        stale_pdf.write_bytes(b"CORRUPT PDF")

        patches = _patch_builders(mock_builders)
        with (
            patch("services.report.json_builder.save_json_result", patches["save_json_result"]),
            patch("services.report.markdown_builder.save_markdown_report", patches["save_markdown_report"]),
            patch("services.report.html_builder.save_html_report", patches["save_html_report"]),
            patch("services.report.pdf_builder_playwright.save_pdf_report_with_playwright", patches["save_pdf_report_with_playwright"]),
        ):
            _generate_and_store_reports({"score": 80}, "test-task-001")

        assert (reports_dir / "report.pdf").read_bytes() == b"%PDF-1.4 fake"

    def test_creates_reports_when_none_exist(self, reports_dir, mock_builders, monkeypatch):
        """Normal case: reports are created when directory is empty."""
        patches = _patch_builders(mock_builders)
        with (
            patch("services.report.json_builder.save_json_result", patches["save_json_result"]),
            patch("services.report.markdown_builder.save_markdown_report", patches["save_markdown_report"]),
            patch("services.report.html_builder.save_html_report", patches["save_html_report"]),
            patch("services.report.pdf_builder_playwright.save_pdf_report_with_playwright", patches["save_pdf_report_with_playwright"]),
        ):
            result = _generate_and_store_reports({"score": 80}, "test-task-001")

        assert (reports_dir / "result.json").exists()
        assert (reports_dir / "report.md").exists()
        assert (reports_dir / "report.html").exists()
        assert result["pdf"] is not None

    def test_missing_source_file_skipped_with_warning(self, reports_dir, tmp_path, monkeypatch, caplog):
        """When a builder returns a path but the file doesn't exist, skip with warning."""
        import logging
        reports_dir.mkdir(parents=True, exist_ok=True)

        # Existing stale file should NOT be overwritten when source is missing
        stale_json = reports_dir / "result.json"
        stale_json.write_text("STALE BUT VALID")

        # Create only md and html source files; json source is missing
        md_file = tmp_path / "report.md"
        html_file = tmp_path / "report.html"
        pdf_file = tmp_path / "report.pdf"
        md_file.write_text("# Report")
        html_file.write_text("<html></html>")
        pdf_file.write_bytes(b"%PDF")

        with (
            patch("services.report.json_builder.save_json_result",
                  lambda result: str(tmp_path / "nonexistent_result.json")),
            patch("services.report.markdown_builder.save_markdown_report",
                  lambda result, template_config=None: str(md_file)),
            patch("services.report.html_builder.save_html_report",
                  lambda md_path, theme=None: str(html_file)),
            patch("services.report.pdf_builder_playwright.save_pdf_report_with_playwright",
                  lambda html_path: str(pdf_file)),
        ):
            with caplog.at_level(logging.WARNING):
                result = _generate_and_store_reports({"score": 80}, "test-task-001")

        # Warning was logged for missing source
        assert any("报告源文件缺失" in r.message for r in caplog.records)
        # Stale file preserved (source was missing, so copy was skipped)
        assert stale_json.read_text() == "STALE BUT VALID"
        # json key omitted from report_paths (phantom path fix)
        assert "json" not in result
        # Other files were copied normally
        assert (reports_dir / "report.md").exists()
        assert result["pdf"] is not None

    def test_pdf_none_return_degrades_gracefully(self, reports_dir, mock_builders, monkeypatch):
        """When Playwright returns None, PDF path is None but other formats succeed."""
        json_file, md_file, html_file, _ = mock_builders

        with (
            patch("services.report.json_builder.save_json_result",
                  lambda result: str(json_file)),
            patch("services.report.markdown_builder.save_markdown_report",
                  lambda result, template_config=None: str(md_file)),
            patch("services.report.html_builder.save_html_report",
                  lambda md_path, theme=None: str(html_file)),
            patch("services.report.pdf_builder_playwright.save_pdf_report_with_playwright",
                  lambda html_path: None),  # Playwright failure
        ):
            result = _generate_and_store_reports({"score": 80}, "test-task-001")

        # PDF degrades to None
        assert result["pdf"] is None
        # Other formats still succeed
        assert result["json"].endswith("result.json")
        assert result["markdown"].endswith("report.md")
        assert result["html"].endswith("report.html")
