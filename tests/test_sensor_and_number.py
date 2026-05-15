"""Tests for sensor and number platforms."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.bcnn.const import DOMAIN


def _by_device_number(hass: HomeAssistant, domain: str, device_number: str) -> str:
    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if entry.platform != DOMAIN or entry.domain != domain:
            continue
        state = hass.states.get(entry.entity_id)
        if state and state.attributes.get("device_number") == device_number:
            return entry.entity_id
    raise AssertionError(f"{domain} for {device_number} not found")


async def test_sensors_have_state_immediately_after_setup(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """Regression: sensors used to show 'unknown' until first manual refresh.

    async_added_to_hass now pulls the value from the coordinator immediately.
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    # Top-level account sensor
    state = hass.states.get(f"sensor.bcnn_{mock_config_entry.data['account']}_account")
    assert state is not None
    assert state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
    assert state.state == mock_config_entry.data["account"]

    # Cost sensor — money value
    cost = hass.states.get(f"sensor.bcnn_{mock_config_entry.data['account']}_cost")
    assert cost is not None
    assert cost.state == "500.0"

    # Meter sensor — current value present
    cold = _by_device_number(hass, "sensor", "12345678")
    cold_state = hass.states.get(cold)
    assert cold_state is not None
    assert cold_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)


async def test_meter_sensor_disappears_when_api_drops_it(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """If the API stops returning a meter, that sensor becomes unavailable."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    cold_id = _by_device_number(hass, "sensor", "12345678")

    # Next refresh returns only the hot meter.
    mock_api.get_information_on_water_meters.return_value = [
        {
            "device_type": "Горячая вода",
            "device_number": "87654321",
            "prev_value": "50.000",
            "cur_value": "55.000",
            "amount_water": "5.000",
            "repr_number": "hw_87654321",
        }
    ]
    coordinator = mock_config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    cold_state = hass.states.get(cold_id)
    assert cold_state is not None
    assert cold_state.state == STATE_UNAVAILABLE


async def test_number_entity_starts_with_meter_current_value(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """The number entity is seeded with the meter's cur_value at setup."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    cold_input = _by_device_number(hass, "number", "12345678")
    state = hass.states.get(cold_input)
    assert state is not None
    assert state.state == "105.123"


async def test_number_set_value_writes_state(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """number.set_value updates the entity state without calling the API."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    cold_input = _by_device_number(hass, "number", "12345678")
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": cold_input, "value": 999.0},
        blocking=True,
    )
    assert hass.states.get(cold_input).state == "999.0"
    # Setting a number must not trigger an API call.
    mock_api.send_meter_readings.assert_not_called()
