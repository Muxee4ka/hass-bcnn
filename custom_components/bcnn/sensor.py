"""Center-SBK Sensor definitions."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, date
from typing import Any
from transliterate import translit

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorDeviceClass,
    SensorStateClass,
    ENTITY_ID_FORMAT,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import (
    DOMAIN,
    CONF_INFO,
    CONF_PAYMENT,
    CONF_READINGS,
    CONF_ACCOUNT,
    ATTR_LAST_UPDATE_TIME,
)
from .coordinator import BCNNCoordinator
from .entity import BCNNBaseCoordinatorEntity
from .helpers import _to_str, _to_float

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class BCNNEntityDescriptionMixin:
    """Mixin for required Center-SBK base description keys."""

    value_fn: Callable[[dict[str, Any]], StateType | datetime | date]


@dataclass(frozen=True, kw_only=True)
class BCNNBaseSensorEntityDescription(SensorEntityDescription):
    """Describes Center-SBK sensor entity default overrides."""

    attr_fn: Callable[[dict[str, Any]], dict[str, StateType | datetime | date]] = (
        lambda _: {}
    )
    avabl_fn: Callable[[dict[str, Any]], bool] = lambda _: True
    icon_fn: Callable[[dict[str, Any]], str | None] = lambda _: None


@dataclass(frozen=True, kw_only=True)
class BCNNSensorEntityDescription(
    BCNNBaseSensorEntityDescription, BCNNEntityDescriptionMixin
):
    """Describes Center-SBK sensor entity."""


SENSOR_TYPES: tuple[BCNNSensorEntityDescription, ...] = (
    # Информация по счету
    BCNNSensorEntityDescription(
        key="account",
        name="Лицевой счет",
        icon="mdi:identifier",
        value_fn=lambda data: _to_str(data.get(CONF_ACCOUNT)),
        avabl_fn=lambda data: CONF_ACCOUNT in data,
        translation_key="account",
        entity_category=EntityCategory.DIAGNOSTIC,
        attr_fn=lambda data: {
            # Информация о помещении
            "Адрес": _to_str(data[CONF_INFO].get("data", {}).get("address", [])),
        },
    ),
    BCNNSensorEntityDescription(
        key="cost",
        name="Сумма к оплате",
        native_unit_of_measurement="RUB",
        device_class=SensorDeviceClass.MONETARY,
        value_fn=lambda data: _to_float(data[CONF_PAYMENT].get("due_payment")),
        avabl_fn=lambda data: CONF_PAYMENT in data,
        translation_key="cost",
        attr_fn=lambda data: {
            # get current payment
            "Период": data[CONF_PAYMENT].get("period"),
            "Входящее сальдо": _to_float(data[CONF_PAYMENT].get("opening_balance")),
            "Начислено": _to_float(data[CONF_PAYMENT].get("accrued")),
            "Оплачено": _to_float(data[CONF_PAYMENT].get("paid")),
            "К оплате": _to_float(data[CONF_PAYMENT].get("due_payment")),
            **{
                elem.get("period_or_service"): elem.get("due_payment")
                for elem in data[CONF_PAYMENT].get("services")
            },
        },
    ),
    BCNNSensorEntityDescription(
        key="cost_date",
        name="Дата начисления",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda data: data[CONF_PAYMENT].get("period"),
        avabl_fn=lambda data: CONF_PAYMENT in data,
        translation_key="cost_date",
    ),
    BCNNSensorEntityDescription(
        key="balance",
        name="Задолженность",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="RUB",
        value_fn=lambda data: _to_float(data[CONF_PAYMENT].get("due_payment")),
        avabl_fn=lambda data: CONF_PAYMENT in data,
        translation_key="balance",
    ),
    BCNNSensorEntityDescription(
        key="current_timestamp",
        name="Последнее обновление",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda data: data[ATTR_LAST_UPDATE_TIME],
        avabl_fn=lambda data: ATTR_LAST_UPDATE_TIME in data,
        entity_category=EntityCategory.DIAGNOSTIC,
        translation_key="current_timestamp",
    ),
)


class BCNNSensor(BCNNBaseCoordinatorEntity, SensorEntity):
    """Center-SBK Sensor."""

    entity_description: BCNNSensorEntityDescription
    coordinator: BCNNCoordinator

    def __init__(
        self,
        coordinator: BCNNCoordinator,
        entity_description: BCNNSensorEntityDescription,
    ) -> None:
        """Initialize the Sensor."""
        super().__init__(coordinator, entity_description)
        _LOGGER.debug("Start adding BCNNSensor")
        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT, self._attr_unique_id, hass=coordinator.hass
        )
        _LOGGER.debug(self.entity_id)

    def _get_data(self) -> dict[str, Any]:
        """Get data for Sensor"""
        return self.coordinator.data

    @property
    def available(self) -> bool:
        """Return True if sensor is available."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.entity_description.avabl_fn(self._get_data())
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self._attr_native_value = self.entity_description.value_fn(self._get_data())

        self._attr_extra_state_attributes = self.entity_description.attr_fn(
            self._get_data()
        )

        if self.entity_description.icon_fn is not None:
            self._attr_icon = self.entity_description.icon_fn(self._get_data())

        self.coordinator.logger.debug(
            "Entity ID: %s Value: %s", self.entity_id, self.native_value
        )

        self.async_write_ha_state()


class BCNNMeterSensor(BCNNSensor):
    """Center-SBK Sensor."""

    device_number: str
    type: str
    entity_description: BCNNSensorEntityDescription

    def __init__(
        self,
        coordinator: BCNNCoordinator,
        entity_description: BCNNSensorEntityDescription,
        device_number: str,
        _type: str,
    ) -> None:
        """Initialize the Sensor."""
        self.device_number = device_number
        self.type = _type
        super().__init__(coordinator=coordinator, entity_description=entity_description)

    def _get_data(self) -> dict[str, Any] | None:
        """Get data for Sensor"""
        if CONF_READINGS in self.coordinator.data:
            _LOGGER.debug(self.device_number)
            _LOGGER.debug(self.coordinator.data)
            _data = list(
                filter(
                    lambda x: x.get("device_number") == self.device_number,
                    self.coordinator.data[CONF_READINGS],
                )
            ).pop()
        else:
            _data = None
        return _data


def _get_meter_slug(_type: str, number_meter: str) -> str:
    """Format tariff slug"""

    return f"{translit(_type.lower(), "ru", reversed=True)}_{number_meter}"


def _get_meter_name(_type: str, number_meter: str) -> str:
    """Format tariff name"""
    return " ".join([_type, number_meter])


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a config entry."""

    coordinator: BCNNCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BCNNSensor] = [
        BCNNSensor(coordinator, entity_description)
        for entity_description in SENSOR_TYPES
    ]

    if CONF_READINGS in coordinator.data:
        for meter in coordinator.data[CONF_READINGS]:
            _LOGGER.debug(meter)
            device_number = meter.get("device_number")
            _type = meter.get("device_type")
            entities.append(
                BCNNMeterSensor(
                    coordinator,
                    BCNNSensorEntityDescription(
                        key=_get_meter_slug(_type, device_number),
                        name=_get_meter_name(_type, device_number),
                        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
                        device_class=SensorDeviceClass.WATER,
                        state_class=SensorStateClass.TOTAL,
                        value_fn=lambda data: _to_float(data.get("cur_value") or data.get("prev_value")),
                        avabl_fn=lambda data: len(data) > 0,
                        translation_key=_get_meter_slug(_type, device_number),
                        attr_fn=lambda data: {
                            "device_number": data.get("device_number"),
                            "Услуга": data.get("device_type"),
                            "Номер счетчика": data.get("device_number"),
                            "Предыдущие показания": data.get("prev_value"),
                            "Текущие показания": data.get("cur_value"),
                            "Количество потреблённого ресурса": data.get("amount_water")
                        },
                    ),
                    device_number,
                    _type,
                )
            )

    async_add_entities(entities, True)
