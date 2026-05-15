"""Center-SBK number entities — editable inputs for meter readings."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import (
    ENTITY_ID_FORMAT,
    NumberDeviceClass,
    NumberEntityDescription,
    NumberMode,
    RestoreNumber,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import ATTR_DEVICE_NUMBER, CONF_READINGS
from .coordinator import BCNNCoordinator
from .entity import BCNNBaseCoordinatorEntity
from .helpers import _to_float
from .sensor import _get_meter_name, _get_meter_slug

_LOGGER = logging.getLogger(__name__)


class BCNNMeterInputNumber(BCNNBaseCoordinatorEntity, RestoreNumber):
    """Editable number entity holding the next reading for one meter."""

    _attr_native_min_value = 0
    _attr_native_max_value = 99999
    _attr_native_step = 0.001
    _attr_native_unit_of_measurement = UnitOfVolume.CUBIC_METERS
    _attr_device_class = NumberDeviceClass.WATER
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:counter"

    device_number: str
    type: str

    def __init__(
        self,
        coordinator: BCNNCoordinator,
        device_number: str,
        device_type: str,
    ) -> None:
        self.device_number = device_number
        self.type = device_type
        description = NumberEntityDescription(
            key=f"input_{_get_meter_slug(device_type, device_number)}",
            name=f"{_get_meter_name(device_type, device_number)} — новое показание",
        )
        super().__init__(coordinator, description)
        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT, self._attr_unique_id, hass=coordinator.hass
        )
        self._attr_native_value = self._meter_value_from_coordinator()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {ATTR_DEVICE_NUMBER: self.device_number}

    def _meter_value_from_coordinator(self) -> float | None:
        readings = (self.coordinator.data or {}).get(CONF_READINGS) or []
        meter = next(
            (m for m in readings if m.get("device_number") == self.device_number),
            None,
        )
        if meter is None:
            return None
        return _to_float(meter.get("cur_value")) or _to_float(meter.get("prev_value"))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = float(last.native_value)
        elif self._attr_native_value is None:
            self._attr_native_value = self._meter_value_from_coordinator()

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one editable number per meter row."""

    coordinator: BCNNCoordinator = entry.runtime_data

    entities: list[BCNNMeterInputNumber] = []
    for meter in coordinator.data.get(CONF_READINGS, []) or []:
        device_number = meter.get("device_number")
        device_type = meter.get("device_type")
        if not device_number or not device_type:
            continue
        entities.append(BCNNMeterInputNumber(coordinator, device_number, device_type))

    async_add_entities(entities)
