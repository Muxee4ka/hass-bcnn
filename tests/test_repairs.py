"""Tests for the parse-error Repairs issue."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.bcnn.const import DOMAIN
from custom_components.bcnn.exceptions import BCNNParseError


async def test_parse_error_raises_repair_issue(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """BCNNParseError from the API → an actionable repair issue is created."""
    mock_api.get_information_on_water_meters.side_effect = BCNNParseError(
        "Не найден input[onchange] — структура сайта изменилась"
    )
    mock_config_entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    registry = ir.async_get(hass)
    issue = registry.async_get_issue(DOMAIN, f"parse_error_{mock_config_entry.data['account']}")
    assert issue is not None
    assert issue.is_fixable
    assert issue.translation_key == "parse_error"
    assert issue.translation_placeholders["account"] == mock_config_entry.data["account"]


async def test_parse_error_issue_cleared_on_success(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_api, mock_config_entry
) -> None:
    """A successful refresh after a parse error should clear the issue."""
    from .conftest import MOCK_READINGS

    # First setup fails with parse error → entry not loaded, issue raised.
    mock_api.get_information_on_water_meters.side_effect = BCNNParseError("oops")
    mock_config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    issue_id = f"parse_error_{mock_config_entry.data['account']}"
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, issue_id) is not None

    # Recover and reload — the issue must clear on the next successful refresh.
    mock_api.get_information_on_water_meters.side_effect = None
    mock_api.get_information_on_water_meters.return_value = list(MOCK_READINGS)
    assert await hass.config_entries.async_reload(mock_config_entry.entry_id)
    await hass.async_block_till_done()

    assert registry.async_get_issue(DOMAIN, issue_id) is None
