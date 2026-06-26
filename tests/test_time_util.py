"""Time utilities: single source of truth (fixes legacy bug #11)."""

from __future__ import annotations

import pytest

from garden_core.infra.time_util import (
    format_ass_time,
    format_srt_time,
    ms_to_s,
    parse_ass_time,
    parse_time_heuristic,
    s_to_ms,
)


@pytest.mark.parametrize("seconds,expected", [
    (0.0, "0:00:00.00"),
    (1.5, "0:00:01.50"),
    (65.25, "0:01:05.25"),
    (3661.99, "1:01:01.99"),
])
def test_format_ass_time(seconds, expected):
    assert format_ass_time(seconds) == expected


@pytest.mark.parametrize("text,expected", [
    ("0:00:01.50", 1.5),
    ("1:01:01.99", 3661.99),
    ("0:01:05:25", 65.25),  # ':' centisecond separator tolerated
])
def test_parse_ass_time_roundtrip(text, expected):
    assert parse_ass_time(text) == pytest.approx(expected)


def test_ass_format_parse_roundtrip():
    for s in (0.0, 12.34, 75.0, 3600.5):
        assert parse_ass_time(format_ass_time(s)) == pytest.approx(s, abs=0.01)


def test_srt_time_format():
    assert format_srt_time(3661.5) == "01:01:01,500"
    assert format_srt_time(0.0) == "00:00:00,000"


def test_ms_s_conversion():
    assert ms_to_s(1500) == pytest.approx(1.5)
    assert s_to_ms(1.5) == pytest.approx(1500.0)


def test_parse_time_heuristic_seconds_vs_ms():
    # < 100000 treated as seconds
    assert parse_time_heuristic(65) == pytest.approx(65.0)
    # >= 100000 treated as milliseconds
    assert parse_time_heuristic(150000) == pytest.approx(150.0)
    # string tolerated
    assert parse_time_heuristic("42") == pytest.approx(42.0)
