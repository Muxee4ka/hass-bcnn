"""Pure parsing helpers for Center-SBK — no Home Assistant imports.

Kept separate so it can be unit-tested without spinning up HA.
"""

from __future__ import annotations

from datetime import date, datetime
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


_DATE_FORMATS = ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%y")


def parse_readings_date(value: str | None) -> date | None:
    """Parse the 'last reading' date from the readings table cell.

    Real cabinets serve 'DD.MM.YYYY'; tolerate a few more formats so we
    don't blow up if the rendering changes slightly.
    """
    if not value:
        return None
    value = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
