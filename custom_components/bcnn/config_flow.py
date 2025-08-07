import logging
from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigFlow,
)

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from custom_components.bcnn.bcnn_api import BCNNApi
from .const import (
    DOMAIN,
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_ACCOUNT,
)

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    try:
        bcnn = BCNNApi(login=data[CONF_LOGIN], password=data[CONF_PASSWORD])

        _LOGGER.info("Connecting to Center-SBK")
        _data = await hass.async_add_executor_job(partial(bcnn.get_accounts))

        # извлекаем только цифры из введённого номера
        account_str = str(data[CONF_ACCOUNT])
        account_digits = "".join(ch for ch in account_str if ch.isdigit())
        if not account_digits:
            raise ValueError("Номер лицевого счёта должен содержать хотя бы одну цифру.")
        account_int = int(account_digits)

        # проверяем наличие номера в полученном списке
        accounts = _data.get("data", {}).get("accountInfo", {}).get("accounts", [])
        if account_int not in accounts:
            raise ValueError(f"Лицевой счёт {account_str} не найден среди доступных в личном кабинете")
    except Exception as exc:
        _LOGGER.warning("Failed to connect to Center-SBK with error %s", exc)
        raise exc

    return {"title": f"{data[CONF_LOGIN]}({str(data[CONF_ACCOUNT])})".lower()}


class BCNNConfigFlow(ConfigFlow, domain=DOMAIN):
    # The schema version of the entries that it creates
    # Home Assistant will call your migrate method if the version changes
    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        login = ""
        password = ""
        account = ""
        errors: dict[str, str] = {}
        if user_input is not None:

            _data = await validate_input(self.hass, user_input)
            await self.async_set_unique_id(_data["title"])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=_data["title"], data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN, default=login): str,
                    vol.Required(CONF_PASSWORD, default=password): str,
                    vol.Required(CONF_ACCOUNT, default=account): str,
                }
            ),
            errors={},
        )
