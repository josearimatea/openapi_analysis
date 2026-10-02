"""Render the reports from schemas/ for people: text (CLI, saved .txt), HTML later.

JSON needs no renderer — a report is a Pydantic model (report.model_dump_json()).
Rendering never computes: every number shown comes from the report.
"""

from openapi_analysis.reporting.text import render_openapi, render_rulesbank

__all__ = ["render_openapi", "render_rulesbank"]
