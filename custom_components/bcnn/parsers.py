"""Pure parsing helpers for Center-SBK — no Home Assistant imports.

Kept separate so it can be unit-tested without spinning up HA.
"""

from __future__ import annotations

from datetime import date
import re

MONTHS: dict[str, int] = {
    "январь": 1,
    "февраль": 2,
    "март": 3,
    "апрель": 4,
    "май": 5,
    "июнь": 6,
    "июль": 7,
    "август": 8,
    "сентябрь": 9,
    "октябрь": 10,
    "ноябрь": 11,
    "декабрь": 12,
}


def convert_period_to_date(period_str: str) -> date:
    """Преобразует строку периода вида 'месяц год г.' в дату.

    Возвращает текущую дату при некорректном формате — это sentinel,
    на который опирается выбор «текущего» периода в get_current_payment.
    """
    parts = (period_str or "").split()
    if len(parts) != 3:
        return date.today()
    month_str, year_str, _ = parts

    match = re.search(r"\d{4}", year_str)
    if not match:
        return date.today()
    year = int(match.group())

    month_num = MONTHS.get(month_str.lower())
    if month_num is None:
        return date.today()

    return date(year, month_num, 1)


_VERIFICATION_RE = re.compile(r"^\s*(\d{1,2})\s*/\s*(\d{2,4})\s*$")


def parse_verification_date(value: str | None) -> date | None:
    """Parse the meter verification due-date cell ('MM/YY' or 'MM/YYYY').

    Real cabinets render this as 'MM/YY' (e.g. '09/28', '12/31'). The
    cabinet table column is the meter's calibration-expiry month. We
    return the first day of that month for a friendly DATE sensor.

    Returns None for empty / unparseable input.
    """
    if not value:
        return None
    match = _VERIFICATION_RE.match(value)
    if not match:
        return None
    month_s, year_s = match.groups()
    try:
        month = int(month_s)
        year = int(year_s)
    except ValueError:
        return None
    if not 1 <= month <= 12:
        return None
    if year < 100:
        year += 2000
    try:
        return date(year, month, 1)
    except ValueError:
        return None
