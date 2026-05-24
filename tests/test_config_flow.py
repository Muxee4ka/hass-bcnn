"""Tests for the Center-SBK config flow."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest

from custom_components.bcnn.const import CONF_ACCOUNT, CONF_LOGIN, CONF_PASSWORD, DOMAIN
from custom_components.bcnn.exceptions import BCNNAuthError, BCNNConnectionError

from .conftest import MOCK_ACCOUNT, MOCK_LOGIN, MOCK_PASSWORD

USER_INPUT = {CONF_LOGIN: MOCK_LOGIN, CONF_PASSWORD: MOCK_PASSWORD}


def _patch_api():
    return patch("custom_components.bcnn.config_flow.BCNNApi", autospec=True)


async def test_user_happy_path_creates_entry(
    hass: HomeAssistant, auto_enable_custom_integrations
) -> None:
    """Successful login → entry created with the first account from the cabinet."""
    with _patch_api() as cls, patch("custom_components.bcnn.BCNNApi", autospec=True) as setup_cls:
        cls.return_value.get_accounts.return_value = {
            "data": {"accountInfo": {"accounts": [int(MOCK_ACCOUNT)]}},
            "errors": [],
        }
        # When async_setup_entry runs after entry creation, the coordinator's
        # first refresh must not blow up.
        setup_cls.return_value.get_information_on_water_meters.return_value = []
        setup_cls.return_value.get_address.return_value = {"data": {}}
        setup_cls.return_value.get_current_payment.return_value = {}

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "user"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_ACCOUNT] == MOCK_ACCOUNT
    assert result["data"][CONF_LOGIN] == MOCK_LOGIN


@pytest.mark.parametrize(
    ("side_effect", "expected_error"),
    [
        (BCNNAuthError("wrong password"), "invalid_auth"),
        (BCNNConnectionError("site down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_errors_surface_in_form(
    hass: HomeAssistant,
    auto_enable_custom_integrations,
    side_effect: Exception,
    expected_error: str,
) -> None:
    """Auth/connection/unknown errors stay on the user step with the right key."""
    with _patch_api() as cls:
        cls.return_value.get_accounts.side_effect = side_effect

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": expected_error}


async def test_user_no_accounts(hass: HomeAssistant, auto_enable_custom_integrations) -> None:
    """If the cabinet returns zero accounts, surface no_accounts error."""
    with _patch_api() as cls:
        cls.return_value.get_accounts.return_value = {
            "data": {"accountInfo": {"accounts": []}},
            "errors": [],
        }

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "no_accounts"}


async def test_user_all_accounts_already_configured(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_config_entry
) -> None:
    """If every cabinet account is already configured under this login → abort."""
    mock_config_entry.add_to_hass(hass)

    with _patch_api() as cls:
        cls.return_value.get_accounts.return_value = {
            "data": {"accountInfo": {"accounts": [int(MOCK_ACCOUNT)]}},
            "errors": [],
        }

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "all_accounts_configured"


async def test_reauth_happy_path_updates_password(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_config_entry
) -> None:
    """Reauth with the right password updates entry data and aborts."""
    mock_config_entry.add_to_hass(hass)
    new_password = "fresh-password"

    # The reauth flow also triggers a reload via async_update_reload_and_abort,
    # so async_setup_entry runs again and needs a stub BCNNApi.
    with (
        _patch_api() as flow_cls,
        patch("custom_components.bcnn.BCNNApi", autospec=True) as setup_cls,
    ):
        flow_cls.return_value.get_accounts.return_value = {
            "data": {"accountInfo": {"accounts": [int(MOCK_ACCOUNT)]}},
            "errors": [],
        }
        setup_cls.return_value.get_information_on_water_meters.return_value = []
        setup_cls.return_value.get_address.return_value = {"data": {}}
        setup_cls.return_value.get_current_payment.return_value = {}

        # start_reauth_flow passes entry.data as initial user_input, so handing
        # in the new password here skips the FORM step and goes straight to
        # async_step_reauth's submission path.
        result = await mock_config_entry.start_reauth_flow(hass, data={CONF_PASSWORD: new_password})
        await hass.async_block_till_done(wait_background_tasks=True)

        assert result["type"] == FlowResultType.ABORT, result
        assert result["reason"] == "reauth_successful"
        assert mock_config_entry.data[CONF_PASSWORD] == new_password


async def test_reauth_invalid_auth_keeps_form(
    hass: HomeAssistant, auto_enable_custom_integrations, mock_config_entry
) -> None:
    """Wrong password on reauth → form with invalid_auth, password unchanged."""
    mock_config_entry.add_to_hass(hass)

    with _patch_api() as cls:
        cls.return_value.get_accounts.side_effect = BCNNAuthError("nope")

        result = await mock_config_entry.start_reauth_flow(hass, data={CONF_PASSWORD: "wrong"})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_PASSWORD] == MOCK_PASSWORD
