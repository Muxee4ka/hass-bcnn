"""Tests for custom_components.bcnn.parsers."""

from __future__ import annotations

from datetime import date

import pytest

from custom_components.bcnn.parsers import MONTHS, convert_period_to_date


class TestConvertPeriodToDate:
    @pytest.mark.parametrize(
        ("period", "expected"),
        [
            ("январь 2026 г.", date(2026, 1, 1)),
            ("Декабрь 2024 г.", date(2024, 12, 1)),
            ("март 2026 г.", date(2026, 3, 1)),
        ],
    )
    def test_happy_path(self, period: str, expected: date) -> None:
        assert convert_period_to_date(period) == expected

    def test_year_with_glued_suffix(self) -> None:
        # Real responses use 'март 2026 г.' with a space; '2026г.' with no space
        # collapses to two tokens and falls through to today() sentinel.
        assert convert_period_to_date("март 2026 г.") == date(2026, 3, 1)

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "март",
            "март 2026",
            "март 2026г.",
            "марs 2026 г.",
            "месяц 2026 г.",
            "март abcd г.",
            "март 26 г.",
        ],
    )
    def test_invalid_returns_today_sentinel(self, bad: str) -> None:
        """get_current_payment relies on today() being returned for bad input."""
        assert convert_period_to_date(bad) == date.today()

    def test_none_safe(self) -> None:
        assert convert_period_to_date(None) == date.today()  # type: ignore[arg-type]


def test_months_table_complete() -> None:
    assert len(MONTHS) == 12
    assert MONTHS["январь"] == 1
    assert MONTHS["декабрь"] == 12


class TestParseReadingsDate:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("25.04.2026", date(2026, 4, 25)),
            ("2026-04-25", date(2026, 4, 25)),
            ("25/04/2026", date(2026, 4, 25)),
            ("25.04.26", date(2026, 4, 25)),
            ("  25.04.2026  ", date(2026, 4, 25)),
        ],
    )
    def test_supported_formats(self, value: str, expected: date) -> None:
        from custom_components.bcnn.parsers import parse_readings_date

        assert parse_readings_date(value) == expected

    @pytest.mark.parametrize("bad", ["", None, "abc", "2026", "25 апреля 2026"])
    def test_invalid_returns_none(self, bad: str | None) -> None:
        from custom_components.bcnn.parsers import parse_readings_date

        assert parse_readings_date(bad) is None
