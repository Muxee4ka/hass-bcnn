"""Center-SBK Account integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .bcnn_api import BCNNApi
from .const import DOMAIN, PLATFORMS, CONF_LOGIN, CONF_PASSWORD, CONF_ACCOUNT
from .coordinator import BCNNCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

OPTIONS_SCHEMA = {
    vol.Required(CONF_LOGIN, msg="Login"): str,
    vol.Required(CONF_PASSWORD, msg="Password"): str,
    vol.Required(CONF_ACCOUNT, msg="Account"): str,
}


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Set up Center-SBK from a config entry."""

    _LOGGER.info(["async_setup_entry", config_entry.data, config_entry.options])
    bcnn_api = BCNNApi(
        str(config_entry.data.get(CONF_LOGIN)),
        str(config_entry.data.get(CONF_PASSWORD)),
    )
    _coordinator = BCNNCoordinator(
        hass, bcnn_api=bcnn_api, account=str(config_entry.data.get(CONF_ACCOUNT))
    )

    await _coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = _coordinator

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    await async_setup_services(hass)

    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    ):
        hass.data[DOMAIN].pop(config_entry.entry_id)

        await async_unload_services(hass)

    return unload_ok
