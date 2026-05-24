"""Tests for the Center-SBK service handlers."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
import pytest

from custom_components.bcnn.const import DOMAIN


async def _setup_and_get_device_id(hass: HomeAssistant, mock_config_entry) -> str:
    """Bring the entry online and return the bcnn device_id for it."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    device_reg = dr.async_get(hass)
    device = device_reg.async_get_device(identifiers={(DOMAIN, mock_config_entry.data["account"])})
    assert device is not None
    return device.id


def _entity_id_by_device_number(hass: HomeAssistant, domain: str, device_number: str) -> str:
    """Find a bcnn entity (sensor or number) by its device_number attribute."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for entry in registry.entities.values():
        if entry.platform != DOMAIN or entry.domain != domain:
            continue
        state = hass.states.get(entry.entity_id)
        if state and state.attributes.get("device_number") == device_number:
            return entry.entity_id
    raise AssertionError(f"{domain} for {device_number} not found")


async def test_send_readings_via_slots_calls_api(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    device_id = await _setup_and_get_device_id(hass, mock_config_entry)
    cold_entity = _entity_id_by_device_number(hass, "sensor", "12345678")
    hot_entity = _entity_id_by_device_number(hass, "sensor", "87654321")

    await hass.services.async_call(
        DOMAIN,
        "send_readings",
        {
            ATTR_DEVICE_ID: device_id,
            "meter_1": cold_entity,
            "meter_1_value": 111.111,
            "meter_2": hot_entity,
            "meter_2_value": 54.0,
        },
        blocking=True,
    )

    mock_api.send_meter_readings.assert_called_once()
    sent_account, sent_readings = mock_api.send_meter_readings.call_args[0]
    assert sent_account == mock_config_entry.data["account"]
    assert dict(sent_readings) == {"12345678": "111.111", "87654321": "54.0"}


async def test_send_readings_rejects_meter_from_other_account(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    device_id = await _setup_and_get_device_id(hass, mock_config_entry)

    # Inject a fake state mimicking a meter sensor that belongs to a different ЛС.
    hass.states.async_set(
        "sensor.stranger_meter",
        "100.0",
        attributes={"device_number": "99999999"},
    )

    with pytest.raises(HomeAssistantError, match="не относится к ЛС"):
        await hass.services.async_call(
            DOMAIN,
            "send_readings",
            {
                ATTR_DEVICE_ID: device_id,
                "meter_1": "sensor.stranger_meter",
                "meter_1_value": 100.0,
            },
            blocking=True,
        )

    mock_api.send_meter_readings.assert_not_called()


async def test_send_readings_via_dict(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    device_id = await _setup_and_get_device_id(hass, mock_config_entry)

    await hass.services.async_call(
        DOMAIN,
        "send_readings",
        {
            ATTR_DEVICE_ID: device_id,
            "readings": {"12345678": 200.0, "87654321": 100.5},
        },
        blocking=True,
    )

    mock_api.send_meter_readings.assert_called_once()
    _, sent_readings = mock_api.send_meter_readings.call_args[0]
    assert dict(sent_readings) == {"12345678": "200.0", "87654321": "100.5"}


async def test_send_readings_dict_rejects_unknown_number(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    device_id = await _setup_and_get_device_id(hass, mock_config_entry)

    with pytest.raises(HomeAssistantError, match="не относятся к ЛС"):
        await hass.services.async_call(
            DOMAIN,
            "send_readings",
            {
                ATTR_DEVICE_ID: device_id,
                "readings": {"00000000": 1.0},
            },
            blocking=True,
        )

    mock_api.send_meter_readings.assert_not_called()


async def test_send_readings_falls_back_to_number_entities(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """No slots, no dict → values pulled from this ЛС's number entities."""
    device_id = await _setup_and_get_device_id(hass, mock_config_entry)

    cold_input = _entity_id_by_device_number(hass, "number", "12345678")
    hot_input = _entity_id_by_device_number(hass, "number", "87654321")

    await hass.services.async_call(
        "number", "set_value", {"entity_id": cold_input, "value": 222.0}, blocking=True
    )
    await hass.services.async_call(
        "number", "set_value", {"entity_id": hot_input, "value": 60.5}, blocking=True
    )

    await hass.services.async_call(
        DOMAIN,
        "send_readings",
        {ATTR_DEVICE_ID: device_id},
        blocking=True,
    )

    mock_api.send_meter_readings.assert_called_once()
    _, sent_readings = mock_api.send_meter_readings.call_args[0]
    assert dict(sent_readings) == {"12345678": "222.0", "87654321": "60.5"}


async def test_send_readings_partial_slot_raises(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    device_id = await _setup_and_get_device_id(hass, mock_config_entry)
    cold_entity = _entity_id_by_device_number(hass, "sensor", "12345678")

    with pytest.raises(HomeAssistantError, match="заполнен частично"):
        await hass.services.async_call(
            DOMAIN,
            "send_readings",
            {
                ATTR_DEVICE_ID: device_id,
                "meter_1": cold_entity,
            },
            blocking=True,
        )


async def test_refresh_invokes_coordinator(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    device_id = await _setup_and_get_device_id(hass, mock_config_entry)

    initial_calls = mock_api.get_information_on_water_meters.call_count
    await hass.services.async_call(DOMAIN, "refresh", {ATTR_DEVICE_ID: device_id}, blocking=True)
    assert mock_api.get_information_on_water_meters.call_count > initial_calls


async def test_get_bill_writes_pdf(
    hass: HomeAssistant,
    auto_enable_custom_integrations,
    mock_api,
    mock_config_entry,
    tmp_path,
) -> None:
    """get_bill writes the PDF body returned by the API to disk."""
    device_id = await _setup_and_get_device_id(hass, mock_config_entry)

    # Redirect hass.config.path("tmp") to a tmp_path so we don't write outside.
    with patch.object(
        hass.config, "path", side_effect=lambda *parts: str(tmp_path.joinpath(*parts))
    ):
        await hass.services.async_call(
            DOMAIN, "get_bill", {ATTR_DEVICE_ID: device_id}, blocking=True
        )

    pdf = tmp_path / "tmp" / f"bill_{mock_config_entry.data['account']}.pdf"
    assert pdf.exists()
    assert pdf.read_bytes() == b"%PDF-1.4 fake"
