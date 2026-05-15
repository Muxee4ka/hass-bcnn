"""Shared pytest fixtures for hass-bcnn tests."""

from __future__ import annotations

from collections.abc import Generator
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from custom_components.bcnn.const import (
    CONF_ACCOUNT,
    CONF_LOGIN,
    CONF_PASSWORD,
    DOMAIN,
)

MOCK_ACCOUNT = "123456789"
MOCK_LOGIN = "user@example.com"
MOCK_PASSWORD = "correct horse"

MOCK_READINGS = [
    {
        "device_type": "Холодная вода",
        "device_number": "12345678",
        "prev_value": "100.000",
        "cur_value": "105.123",
        "amount_water": "5.123",
        "repr_number": "cw_12345678",
    },
    {
        "device_type": "Горячая вода",
        "device_number": "87654321",
        "prev_value": "50.000",
        "cur_value": "53.750",
        "amount_water": "3.750",
        "repr_number": "hw_87654321",
    },
]

MOCK_ADDRESS = {"data": {"address": "ул. Тестовая, д. 1, кв. 1"}}

MOCK_PAYMENT = {
    "period": date(2026, 4, 1),
    "opening_balance": "0.00",
    "accrued": "500.00",
    "paid": "0.00",
    "due_payment": "500.00",
    "services": [],
}


@pytest.fixture
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable the bcnn custom integration. Request from any HA-flavored test."""
    yield


@pytest.fixture
def mock_config_entry():
    """Provide a fresh MockConfigEntry for each test."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    return MockConfigEntry(
        domain=DOMAIN,
        title=f"({MOCK_ACCOUNT})",
        unique_id=f"{MOCK_LOGIN}({MOCK_ACCOUNT})".lower(),
        data={
            CONF_LOGIN: MOCK_LOGIN,
            CONF_PASSWORD: MOCK_PASSWORD,
            CONF_ACCOUNT: MOCK_ACCOUNT,
        },
    )


@pytest.fixture
def mock_api() -> Generator[MagicMock, None, None]:
    """Patch BCNNApi everywhere it is constructed and return the mock instance."""
    with patch("custom_components.bcnn.BCNNApi", autospec=True) as cls:
        instance = cls.return_value
        instance.get_information_on_water_meters.return_value = list(MOCK_READINGS)
        instance.get_address.return_value = MOCK_ADDRESS
        instance.get_current_payment.return_value = dict(MOCK_PAYMENT)
        instance.send_meter_readings.return_value = "Показания успешно переданы"
        instance.get_bill.return_value = b"%PDF-1.4 fake"
        instance.get_accounts.return_value = {
            "data": {"accountInfo": {"accounts": [int(MOCK_ACCOUNT)]}},
            "errors": [],
        }
        yield instance
