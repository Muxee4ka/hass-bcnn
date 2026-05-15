"""Constants for the Center-SBK integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

ATTRIBUTION: Final = "Данные получены от Центр-СБК"
DOMAIN: Final = "bcnn"
MANUFACTURER: Final = "Центр-СБК"

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON, Platform.NUMBER]

CONF_LOGIN: Final = "login"
CONF_PASSWORD: Final = "password"
CONF_ACCOUNT: Final = "account"
CONF_INFO: Final = "info"
CONF_PAYMENT: Final = "payment"
CONF_READINGS: Final = "readings"
ATTR_LAST_UPDATE_TIME: Final = "last_update_time"

DEVICE_NAME_FORMAT: Final = "ЛC №{}"
ATTR_MODEL_PU: Final = "ModelPU"

ATTR_READINGS: Final = "readings"
ATTR_DEVICE_NUMBER: Final = "device_number"
METER_SLOTS: Final = 4

CONFIGURATION_URL: Final = "https://lk.bcnn.ru/"
