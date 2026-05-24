import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.data_entry_flow import FlowResult
import voluptuous as vol

from custom_components.bcnn.bcnn_api import BCNNApi
from custom_components.bcnn.exceptions import BCNNAuthError, BCNNConnectionError

from .const import CONF_ACCOUNT, CONF_LOGIN, CONF_PASSWORD, DOMAIN

_LOGGER = logging.getLogger(__name__)

REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})


class BCNNConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            bcnn = BCNNApi(login=user_input[CONF_LOGIN], password=user_input[CONF_PASSWORD])
            try:
                try:
                    data = await bcnn.get_accounts()
                finally:
                    await bcnn.close()
                accounts = data.get("data", {}).get("accountInfo", {}).get("accounts", [])
                if not accounts:
                    errors["base"] = "no_accounts"
                else:
                    login = user_input[CONF_LOGIN]
                    password = user_input[CONF_PASSWORD]

                    configured = {
                        entry.data[CONF_ACCOUNT]
                        for entry in self._async_current_entries()
                        if entry.data.get(CONF_LOGIN) == login
                    }
                    unconfigured = [str(a) for a in accounts if str(a) not in configured]

                    if not unconfigured:
                        return self.async_abort(reason="all_accounts_configured")

                    for account in unconfigured[1:]:
                        self.hass.async_create_task(
                            self.hass.config_entries.flow.async_init(
                                DOMAIN,
                                context={"source": "import"},
                                data={
                                    CONF_LOGIN: login,
                                    CONF_PASSWORD: password,
                                    CONF_ACCOUNT: account,
                                },
                            )
                        )

                    first = unconfigured[0]
                    unique_id = f"{login}({first})".lower()
                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=unique_id,
                        data={
                            CONF_LOGIN: login,
                            CONF_PASSWORD: password,
                            CONF_ACCOUNT: first,
                        },
                    )
            except BCNNAuthError as exc:
                _LOGGER.warning("Ошибка аутентификации при настройке: %s", exc)
                errors["base"] = "invalid_auth"
            except BCNNConnectionError as exc:
                _LOGGER.warning("Ошибка подключения при настройке: %s", exc)
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Неожиданная ошибка при настройке Center-SBK")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> FlowResult:
        """Автоматическое создание записей для дополнительных ЛС."""
        account = import_data[CONF_ACCOUNT]
        unique_id = f"{import_data[CONF_LOGIN]}({account})".lower()
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=unique_id, data=import_data)

    async def async_step_reauth(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Повторная аутентификация при смене пароля."""
        errors: dict[str, str] = {}
        reauth_entry: ConfigEntry = self._get_reauth_entry()

        if user_input is not None:
            new_password = user_input[CONF_PASSWORD]
            bcnn = BCNNApi(
                login=reauth_entry.data[CONF_LOGIN],
                password=new_password,
            )
            try:
                try:
                    await bcnn.get_accounts()
                finally:
                    await bcnn.close()
            except BCNNAuthError:
                errors["base"] = "invalid_auth"
            except BCNNConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Неожиданная ошибка при повторной аутентификации Center-SBK")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={CONF_PASSWORD: new_password},
                )

        return self.async_show_form(
            step_id="reauth",
            description_placeholders={"login": reauth_entry.data[CONF_LOGIN]},
            data_schema=REAUTH_SCHEMA,
            errors=errors,
        )
