"""Center-SBK Account Coordinator."""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    REQUEST_REFRESH_DEFAULT_COOLDOWN, UpdateFailed,
)
from homeassistant.util import dt

from custom_components.bcnn.bcnn_api import BCNNApi
from custom_components.bcnn.const import (
    CONF_ACCOUNT,
    DOMAIN,
    CONF_INFO,
    CONF_PAYMENT,
    CONF_READINGS,
    ATTR_LAST_UPDATE_TIME,
)

_LOGGER = logging.getLogger(__name__)


class BCNNCoordinator(DataUpdateCoordinator):
    """Coordinator is responsible for querying the device at a specified route."""

    _api: BCNNApi
    account: str

    def __init__(self, hass: HomeAssistant, *, bcnn_api: BCNNApi, account: str) -> None:
        """Initialise a custom coordinator."""
        self.account = str(account)
        self.data = {
            CONF_ACCOUNT: self.account,
            CONF_INFO: {},
            CONF_PAYMENT: {},
            CONF_READINGS: [],
            ATTR_LAST_UPDATE_TIME: None,
        }
        self._api = bcnn_api
        self.lock = asyncio.Lock()
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            request_refresh_debouncer=Debouncer(
                hass,
                _LOGGER,
                cooldown=REQUEST_REFRESH_DEFAULT_COOLDOWN,
                immediate=False,
            ),
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from Center-SBK"""
        self.logger.debug("Start updating Center-SBK data")

        new_data: dict[str, Any] = {
            CONF_ACCOUNT: self.account,
            CONF_INFO: {},
            CONF_PAYMENT: {},
            CONF_READINGS: [],
            ATTR_LAST_UPDATE_TIME: dt.now(),
        }
        try:
            self.logger.debug("Get general info for account %s", self.account)
            async with self.lock:
                new_data[CONF_READINGS] = await self.hass.async_add_executor_job(
                    partial(self._api.get_information_on_water_meters, self.account)
                )
                new_data[CONF_INFO] = await self.hass.async_add_executor_job(
                    partial(self._api.get_address, self.account)
                )
                new_data[CONF_PAYMENT] = await self.hass.async_add_executor_job(
                    partial(self._api.get_current_payment, self.account)
                )

            self.logger.debug("Center-SBK data updated successfully")
            self.logger.debug("%s", new_data)
            return new_data
        except Exception as error:  # pylint: disable=broad-except
            raise UpdateFailed(
                f"Error communicating with Center-SBK API: {error}"
            ) from error

    async def async_send_readings(self, meter_values):
        _LOGGER.debug(meter_values)
        response = await self.hass.async_add_executor_job(
            partial(self._api.send_meter_readings, self.account, meter_values)
        )
        if response:
            return response
        pass

    async def async_get_bill(self) -> bytes:
        response = await self.hass.async_add_executor_job(
            partial(self._api.get_bill, self.account)
        )
        if response:
            return response
