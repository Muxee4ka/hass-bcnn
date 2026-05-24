"""Tests for sensor and number platforms."""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

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


async def test_payment_breakdown_sensors(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """opening_balance / accrued / paid sensors expose payment fields."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    account = mock_config_entry.data["account"]
    assert hass.states.get(f"sensor.bcnn_{account}_opening_balance").state == "0.0"
    assert hass.states.get(f"sensor.bcnn_{account}_accrued").state == "500.0"
    assert hass.states.get(f"sensor.bcnn_{account}_paid").state == "0.0"


async def test_amount_water_sensor_per_meter(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """A separate '<meter> — потребление' sensor is created per meter."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    amount_sensors = [
        e
        for e in registry.entities.values()
        if e.platform == DOMAIN and e.domain == "sensor" and e.unique_id.endswith("_amount")
    ]
    assert len(amount_sensors) == 2
    cold_amount = next(e for e in amount_sensors if "12345678" in e.unique_id)
    assert hass.states.get(cold_amount.entity_id).state == "5.123"


async def test_amount_water_unavailable_when_empty(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """Real cabinets return amount_water='' early in the period — sensor is unavailable."""
    mock_api.get_information_on_water_meters.return_value = [
        {
            "device_type": "ХВС",
            "device_number": "12345678",
            "prev_value": "00100.000",
            "cur_value": "",
            "amount_water": "",
            "repr_number": "cw_12345678",
        }
    ]
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    amount = next(
        e
        for e in registry.entities.values()
        if e.platform == DOMAIN and e.domain == "sensor" and e.unique_id.endswith("_amount")
    )
    assert hass.states.get(amount.entity_id).state == STATE_UNAVAILABLE


async def test_els_is_exposed_as_serial_number(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """The единый лицевой счёт (els) lives on DeviceInfo.serial_number."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_reg = dr.async_get(hass)
    device = device_reg.async_get_device(identifiers={(DOMAIN, mock_config_entry.data["account"])})
    assert device is not None
    assert device.serial_number == "80AB123456"


async def test_verification_date_sensor(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """A '<meter> — срок поверки' DATE sensor is created per meter.

    The cabinet renders verification due dates as 'MM/YY' in columns[2];
    we surface them as a DATE sensor pointing at the 1st of that month.
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    date_sensors = [
        e
        for e in registry.entities.values()
        if e.platform == DOMAIN
        and e.domain == "sensor"
        and e.unique_id.endswith("_verification_date")
    ]
    assert len(date_sensors) == 2
    cold = next(e for e in date_sensors if "12345678" in e.unique_id)
    state = hass.states.get(cold.entity_id)
    assert state.state == "2028-09-01"
    assert state.attributes["raw"] == "09/28"


async def test_number_step_from_meter_formatter(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """NumberEntity.step reflects the meter's own digits-after-the-dot.

    formatter=('12345','678') ⇒ 3 digits ⇒ step=0.001.
    """
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    cold_input = _by_device_number(hass, "number", "12345678")
    state = hass.states.get(cold_input)
    assert state is not None
    assert state.attributes["step"] == 0.001


async def test_number_step_for_four_digit_formatter(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """A 4-digit-after-the-dot meter should expose step=0.0001."""
    mock_api.get_information_on_water_meters.return_value = [
        {
            "device_type": "ХВС",
            "device_number": "12345678",
            "verification_date_raw": "09/30",
            "prev_value": "00100.0000",
            "cur_value": "00105.1234",
            "amount_water": "5.1234",
            "repr_number": "cw_12345678",
            "formatter": ("12345", "6789"),
        }
    ]
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    cold_input = _by_device_number(hass, "number", "12345678")
    state = hass.states.get(cold_input)
    assert state is not None
    assert state.attributes["step"] == 0.0001
