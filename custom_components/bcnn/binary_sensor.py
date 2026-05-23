"""Binary sensors for Center-SBK."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    ENTITY_ID_FORMAT,
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_PAYMENT
from .coordinator import BCNNCoordinator
from .entity import BCNNBaseCoordinatorEntity
from .helpers import _to_float

_LOGGER = logging.getLogger(__name__)


class BCNNDebtBinarySensor(BCNNBaseCoordinatorEntity, BinarySensorEntity):
    """Whether there is an outstanding balance to be paid."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:cash-alert"

    def __init__(self, coordinator: BCNNCoordinator) -> None:
        super().__init__(
            coordinator,
            BinarySensorEntityDescription(key="has_debt", translation_key="has_debt"),
        )
        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT, self._attr_unique_id, hass=coordinator.hass
        )

    @property
    def available(self) -> bool:
        return (
            super().available
            and self.coordinator.data is not None
            and bool(self.coordinator.data.get(CONF_PAYMENT))
            and self._due() is not None
        )

    @callback
    def _due(self) -> float | None:
        data = self.coordinator.data or {}
        return _to_float((data.get(CONF_PAYMENT) or {}).get("due_payment"))

    @property
    def is_on(self) -> bool | None:
        due = self._due()
        if due is None:
            return None
        return due > 0

    @property
    def extra_state_attributes(self) -> dict[str, float | None]:
        return {"due_payment": self._due()}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: BCNNCoordinator = entry.runtime_data
    async_add_entities([BCNNDebtBinarySensor(coordinator)])
