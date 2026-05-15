"""Tests for BCNNCoordinator behavior (happy path, retries, reauth trigger)."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
import pytest

from custom_components.bcnn.exceptions import BCNNAuthError, BCNNConnectionError


async def test_first_refresh_populates_data(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """Successful setup → entry LOADED, coordinator.data populated."""
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.LOADED
    coordinator = mock_config_entry.runtime_data
    assert coordinator.data["account"] == mock_config_entry.data["account"]
    assert len(coordinator.data["readings"]) == 2


async def test_auth_error_starts_reauth(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """BCNNAuthError from the API should trigger a reauth flow."""
    mock_api.get_information_on_water_meters.side_effect = BCNNAuthError("bad creds")
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    flows = hass.config_entries.flow.async_progress()
    assert any(f["handler"] == "bcnn" and f["context"]["source"] == "reauth" for f in flows)


async def test_connection_error_retries_then_fails(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """Three consecutive connection errors → UpdateFailed / entry not loaded.

    The coordinator sleeps between retries; we patch asyncio.sleep to keep
    the test fast.
    """
    mock_api.get_information_on_water_meters.side_effect = BCNNConnectionError("down")
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.bcnn.coordinator.asyncio.sleep") as sleep:
        ok = await hass.config_entries.async_setup(mock_config_entry.entry_id)

    assert ok is False
    assert mock_api.get_information_on_water_meters.call_count == 3
    # 2 sleeps between 3 attempts
    assert sleep.call_count == 2
    assert mock_config_entry.state != ConfigEntryState.LOADED


@pytest.mark.parametrize("transient_attempts", [1, 2])
async def test_connection_error_recovers(
    hass: HomeAssistant,
    auto_enable_custom_integrations,
    mock_api,
    mock_config_entry,
    transient_attempts: int,
) -> None:
    """Transient BCNNConnectionError followed by success → entry LOADED."""
    from .conftest import MOCK_READINGS

    side_effects: list = [BCNNConnectionError("blip")] * transient_attempts + [list(MOCK_READINGS)]
    mock_api.get_information_on_water_meters.side_effect = side_effects
    mock_config_entry.add_to_hass(hass)

    with patch("custom_components.bcnn.coordinator.asyncio.sleep"):
        assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert mock_config_entry.state == ConfigEntryState.LOADED
