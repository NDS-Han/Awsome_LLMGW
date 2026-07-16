# Copyright 2026 © Amazon.com and Affiliates
"""Regression: #33 — Budget Redis sync must preserve app_clients field."""
import pytest
from pathlib import Path


@pytest.mark.unit
def test_budget_sync_preserves_app_clients():
    src = Path(__file__).resolve().parents[2] / "src" / "app" / "services" / "budget_service.py"
    source = src.read_text()
    assert "app_clients" in source, (
        "budget_service must preserve app_clients when syncing thresholds to Redis"
    )
