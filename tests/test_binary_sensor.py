"""Tests for the 'has_debt' binary sensor."""

from __future__ import annotations

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant


async def _setup(hass: HomeAssistant, mock_config_entry) -> str:
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()
    return f"binary_sensor.bcnn_{mock_config_entry.data['account']}_has_debt"


async def test_has_debt_on_when_due_payment_positive(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """Default MOCK_PAYMENT.due_payment is '500.00' → sensor on."""
    entity_id = await _setup(hass, mock_config_entry)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_ON
    assert state.attributes["due_payment"] == 500.0


async def test_has_debt_off_when_due_payment_zero(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """due_payment == 0 → sensor off."""
    from datetime import date

    mock_api.get_current_payment.return_value = {
        "period": date(2026, 4, 1),
        "opening_balance": "1000.00",
        "accrued": "0.00",
        "paid": "1000.00",
        "due_payment": "0.00",
        "services": [],
    }
    entity_id = await _setup(hass, mock_config_entry)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_OFF
    assert state.attributes["due_payment"] == 0.0


async def test_has_debt_unavailable_without_payment(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """No payment data → unavailable."""
    mock_api.get_current_payment.return_value = {}
    entity_id = await _setup(hass, mock_config_entry)
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == STATE_UNAVAILABLE
