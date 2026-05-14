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
    REQUEST_REFRESH_DEFAULT_COOLDOWN,
    UpdateFailed,
)
from homeassistant.util import dt

from .bcnn_api import BCNNApi
from .const import (
    CONF_ACCOUNT,
    DOMAIN,
    CONF_INFO,
    CONF_PAYMENT,
    CONF_READINGS,
    ATTR_LAST_UPDATE_TIME,
)

_LOGGER = logging.getLogger(__name__)


class BCNNCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator responsible for querying the Center-SBK site."""

    _api: BCNNApi
    account: str

    def __init__(self, hass: HomeAssistant, *, api: BCNNApi, account: str) -> None:
        self.account = str(account)
        self._api = api
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
        _LOGGER.debug("Обновление данных Center-SBK для аккаунта %s", self.account)
        try:
            async with self.lock:
                readings = await self.hass.async_add_executor_job(
                    partial(self._api.get_information_on_water_meters, self.account)
                )
                info = await self.hass.async_add_executor_job(
                    partial(self._api.get_address, self.account)
                )
                payment = await self.hass.async_add_executor_job(
                    partial(self._api.get_current_payment, self.account)
                )
        except Exception as error:
            raise UpdateFailed(
                f"Ошибка получения данных Center-SBK: {error}"
            ) from error

        _LOGGER.debug("Данные Center-SBK обновлены успешно")
        return {
            CONF_ACCOUNT: self.account,
            CONF_INFO: info,
            CONF_PAYMENT: payment,
            CONF_READINGS: readings,
            ATTR_LAST_UPDATE_TIME: dt.now(),
        }

    async def async_send_readings(self, meter_values: tuple[tuple[str, str], ...]) -> str | None:
        _LOGGER.debug("Отправка показаний: %s", meter_values)
        return await self.hass.async_add_executor_job(
            partial(self._api.send_meter_readings, self.account, meter_values)
        )

    async def async_get_bill(self) -> bytes | None:
        return await self.hass.async_add_executor_job(
            partial(self._api.get_bill, self.account)
        )
