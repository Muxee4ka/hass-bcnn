"""Center-SBK Account Coordinator."""

from __future__ import annotations

import asyncio
from functools import partial
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.update_coordinator import (
    REQUEST_REFRESH_DEFAULT_COOLDOWN,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt

from .bcnn_api import BCNNApi
from .const import (
    ATTR_LAST_UPDATE_TIME,
    CONF_ACCOUNT,
    CONF_INFO,
    CONF_PAYMENT,
    CONF_READINGS,
    DOMAIN,
)
from .exceptions import BCNNAuthError, BCNNConnectionError

_LOGGER = logging.getLogger(__name__)

_RETRY_ATTEMPTS = 3
_RETRY_DELAYS = (5, 15)  # seconds between attempt 1→2 and 2→3


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
        _LOGGER.debug("Обновление данных Center-SBК для аккаунта %s", self.account)
        last_error: Exception | None = None

        for attempt in range(_RETRY_ATTEMPTS):
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
                break  # успех — выходим из цикла
            except BCNNAuthError as error:
                self.config_entry.async_start_reauth(self.hass)
                raise UpdateFailed(f"Ошибка аутентификации Center-SBK: {error}") from error
            except BCNNConnectionError as error:
                last_error = error
                if attempt < _RETRY_ATTEMPTS - 1:
                    delay = _RETRY_DELAYS[attempt]
                    _LOGGER.warning(
                        "Сетевая ошибка Center-SBK (попытка %d/%d), повтор через %ds: %s",
                        attempt + 1,
                        _RETRY_ATTEMPTS,
                        delay,
                        error,
                    )
                    await asyncio.sleep(delay)
            except Exception as error:
                raise UpdateFailed(f"Ошибка получения данных Center-SBK: {error}") from error
        else:
            raise UpdateFailed(
                f"Center-SBK недоступен после {_RETRY_ATTEMPTS} попыток: {last_error}"
            )

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
        return await self.hass.async_add_executor_job(partial(self._api.get_bill, self.account))
