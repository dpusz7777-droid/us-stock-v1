#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unified report-generation adapter over the project's real function APIs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ai_briefing import generate_morning_briefing
from briefing import (
    build_briefing_data,
    build_evening_briefing_result,
    build_evening_markdown,
    build_morning_markdown,
)
from core.data_layer import get_reports as _get_reports


@dataclass(frozen=True)
class Report:
    """Normalized report."""

    date: str
    type: str
    title: str
    content: str
    generated_at: str


@dataclass(frozen=True)
class ReportIndex:
    """Normalized report index."""

    reports: tuple[Report, ...]
    total: int


class ReportGenerator:
    """Bridge the Northstar report API to the existing function-based modules."""

    def daily_morning(self) -> Report:
        """Generate a morning report from real portfolio and market data."""
        now = datetime.now()
        data = build_briefing_data()
        result = generate_morning_briefing(data)
        content = build_morning_markdown(result, generated_at=now)
        return Report(
            date=now.strftime("%Y-%m-%d"),
            type="morning",
            title=f"Morning report {now:%Y-%m-%d}",
            content=content,
            generated_at=now.strftime("%Y-%m-%d %H:%M"),
        )

    def daily_evening(self) -> Report:
        """Generate an evening report from real portfolio and market data."""
        now = datetime.now()
        data = build_briefing_data()
        result = build_evening_briefing_result(data)
        content = build_evening_markdown(result, generated_at=now)
        return Report(
            date=now.strftime("%Y-%m-%d"),
            type="evening",
            title=f"Evening report {now:%Y-%m-%d}",
            content=content,
            generated_at=now.strftime("%Y-%m-%d %H:%M"),
        )

    def index(self, limit: int = 10) -> ReportIndex:
        """Read the existing report index."""
        reports = tuple(
            Report(
                date=row.date,
                type=row.type,
                title=f"{row.date} {row.type}",
                content=row.content or "",
                generated_at=row.date,
            )
            for row in _get_reports(limit=limit)
        )
        return ReportIndex(reports=reports, total=len(reports))
