"""Center-SBK Account integration."""

from __future__ import annotations

from functools import partial
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from transliterate import translit

from .bcnn_api import BCNNApi
from .const import CONF_ACCOUNT, CONF_LOGIN, CONF_PASSWORD, PLATFORMS
from .coordinator import BCNNCoordinator
from .services import async_setup_services, async_unload_services

_LOGGER = logging.getLogger(__name__)

type BCNNConfigEntry = ConfigEntry[BCNNCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: BCNNConfigEntry) -> bool:
    """Set up Center-SBK from a config entry."""
    _LOGGER.debug(
        "async_setup_entry: entry_id=%s account=%s", entry.entry_id, entry.data[CONF_ACCOUNT]
    )

    api = BCNNApi(
        login=entry.data[CONF_LOGIN],
        password=entry.data[CONF_PASSWORD],
    )
    coordinator = BCNNCoordinator(hass, api=api, account=entry.data[CONF_ACCOUNT])
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator

    # Warm up transliterate off the event loop before any platform that needs
    # it (sensor / number / button) gets set up. The first call inside the
    # library does blocking os.listdir + import_module.
    await hass.async_add_executor_job(partial(translit, "прогрев", "ru", reversed=True))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await async_setup_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: BCNNConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: BCNNCoordinator | None = entry.runtime_data
        if coordinator is not None:
            await coordinator._api.close()
        await async_unload_services(hass, entry)
    return unload_ok
