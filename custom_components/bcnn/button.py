"""Support for Center-SBK button."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import (
    ButtonEntityDescription,
    ButtonEntity,
    ENTITY_ID_FORMAT,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory, async_generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import slugify

from .const import DOMAIN
from .coordinator import BCNNCoordinator
from .entity import BCNNBaseCoordinatorEntity
from .services import SERVICE_REFRESH, SERVICE_GET_BILL


@dataclass
class BCNNButtonRequiredKeysMixin:
    """Mixin for required keys."""

    async_press: Callable[[BCNNCoordinator, str], Awaitable]


@dataclass
class BCNNButtonEntityDescription(ButtonEntityDescription, BCNNButtonRequiredKeysMixin):
    """Class describing Center-SBK button entities."""


BUTTON_DESCRIPTIONS: tuple[BCNNButtonEntityDescription, ...] = (
    BCNNButtonEntityDescription(
        key="refresh",
        icon="mdi:refresh",
        name="Обновить сведения",
        entity_category=EntityCategory.DIAGNOSTIC,
        async_press=lambda coordinator, device_id: coordinator.hass.services.async_call(
            DOMAIN, SERVICE_REFRESH, {ATTR_DEVICE_ID: device_id}, blocking=True
        ),
        translation_key="refresh",
    ),
    BCNNButtonEntityDescription(
        key="get_bill",
        icon="mdi:receipt-text-outline",
        name="Получить счет",
        entity_category=EntityCategory.DIAGNOSTIC,
        async_press=lambda coordinator, device_id: coordinator.hass.services.async_call(
            DOMAIN, SERVICE_GET_BILL, {ATTR_DEVICE_ID: device_id}, blocking=True
        ),
        translation_key="get_bill",
    ),
)


class BCNNButtonEntity(BCNNBaseCoordinatorEntity, ButtonEntity):
    """Representation of a Center-SBK button."""

    entity_description: BCNNButtonEntityDescription

    def __init__(
        self,
        coordinator: BCNNCoordinator,
        entity_description: BCNNButtonEntityDescription,
    ) -> None:
        """Initialize the Entity"""
        super().__init__(coordinator, entity_description)
        self._attr_unique_id = slugify(
            "_".join(
                [
                    DOMAIN,
                    coordinator.account,
                    self.entity_description.key,
                ]
            )
        )

        self.entity_id = async_generate_entity_id(
            ENTITY_ID_FORMAT, self._attr_unique_id, hass=coordinator.hass
        )

    async def async_press(self) -> None:
        """Press the button."""
        # self.entity_id
        if not self.registry_entry:
            return
        if device_id := self.registry_entry.device_id:
            await self.entity_description.async_press(self.coordinator, device_id)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a config entry."""

    coordinator: BCNNCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[BCNNButtonEntity] = [
        BCNNButtonEntity(coordinator, entity_description)
        for entity_description in BUTTON_DESCRIPTIONS
    ]

    async_add_entities(entities, True)
