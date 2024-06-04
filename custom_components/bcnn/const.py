"""Constants for the Center-SBK integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

ATTRIBUTION: Final = "Данные получены от Центр-СБК"
DOMAIN: Final = "bcnn"
MANUFACTURER: Final = "Центр-СБК"


PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

CONF_LOGIN: Final = "login"
CONF_PASSWORD: Final = "password"
CONF_ACCOUNT: Final = "account"
CONF_DATA: Final = "data"
CONF_LINK: Final = "link"
CONF_INFO: Final = "info"
CONF_PAYMENT: Final = "payment"
CONF_READINGS: Final = "readings"
ATTR_LAST_UPDATE_TIME: Final = "last_update_time"

DEVICE_NAME_FORMAT: Final = "ЛC №{}"
ATTR_MODEL_PU: Final = "ModelPU"

ATTR_CW_1: Final = "cw1"
ATTR_CW_1_VAL: Final = "cw1val"
ATTR_HW_1: Final = "hw1"
ATTR_HW_1_VAL: Final = "hw1val"
ATTR_CW_2: Final = "cw2"
ATTR_CW_2_VAL: Final = "cw2val"
ATTR_HW_2: Final = "hw2"
ATTR_HW_2_VAL: Final = "hw2val"
ATTR_COORDINATOR: Final = "coordinator"
ATTR_READINGS = "readings"
ATTR_BALANCE = "balance"

CONFIGURATION_URL: Final = "https://lk.bcnn.ru/"
