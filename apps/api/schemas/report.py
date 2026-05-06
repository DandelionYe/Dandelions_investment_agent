"""Pydantic models for report download endpoints."""

from pydantic import BaseModel


class ReportInfo(BaseModel):
    task_id: str
    formats: list[str]  # e.g. ["json", "markdown", "html", "pdf"]
    json_path: str | None = None
    markdown_path: str | None = None
    html_path: str | None = None
    pdf_path: str | None = None
