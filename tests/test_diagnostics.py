"""Tests for diagnostics output."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.bcnn.diagnostics import async_get_config_entry_diagnostics

from .conftest import MOCK_LOGIN, MOCK_PASSWORD


async def test_diagnostics_redacts_credentials(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    mock_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    data = diag["entry"]["data"]
    assert data["password"] == "**REDACTED**"
    assert data["login"] == "**REDACTED**"
    assert MOCK_PASSWORD not in str(diag)
    # Account number is not secret and stays visible.
    assert data["account"] == mock_config_entry.data["account"]
    # The unique_id still embeds the login — not in scope for redaction here,
    # but kept as a known-limitation note so a future change doesn't surprise us.
    assert MOCK_LOGIN in diag["entry"]["unique_id"]

    assert diag["last_update_success"] is True
    assert diag["coordinator_data"]["account"] == mock_config_entry.data["account"]
