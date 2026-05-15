"""Center-SBK services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
import logging
import os
from typing import Any

from homeassistant.components.number import DOMAIN as NUMBER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DATE, ATTR_DEVICE_ID, CONF_ERROR, CONF_URL
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er
import voluptuous as vol

from .const import ATTR_DEVICE_NUMBER, ATTR_READINGS, CONF_READINGS, DOMAIN, METER_SLOTS
from .coordinator import BCNNCoordinator
from .helpers import async_get_coordinator, get_previous_month

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH = "refresh"
SERVICE_SEND_READINGS = "send_readings"
SERVICE_GET_BILL = "get_bill"

SERVICE_BASE_SCHEMA = {vol.Required(ATTR_DEVICE_ID): cv.string}

SERVICE_REFRESH_SCHEMA = vol.Schema({**SERVICE_BASE_SCHEMA})

SERVICE_SEND_READINGS_SCHEMA = vol.Schema(
    {
        **SERVICE_BASE_SCHEMA,
        vol.Optional(ATTR_READINGS): vol.Schema({cv.string: vol.Coerce(float)}),
        **{
            key: validator
            for i in range(1, METER_SLOTS + 1)
            for key, validator in [
                (vol.Optional(f"meter_{i}"), cv.entity_id),
                (vol.Optional(f"meter_{i}_value"), vol.Coerce(float)),
            ]
        },
    }
)

SERVICE_GET_BILL_SCHEMA = vol.Schema({**SERVICE_BASE_SCHEMA})


@dataclass
class ServiceDescription:
    name: str
    service_func: Callable[[HomeAssistant, ServiceCall, BCNNCoordinator], Awaitable[dict[str, Any]]]
    schema: vol.Schema | None = None


async def _async_handle_refresh(
    hass: HomeAssistant, service_call: ServiceCall, coordinator: BCNNCoordinator
) -> dict[str, Any]:
    await coordinator.async_refresh()
    return {}


def _collect_readings_from_numbers(
    hass: HomeAssistant, device_id: str, valid_numbers: set[str]
) -> dict[str, str]:
    """Read current values from this ЛС's number entities."""
    registry = er.async_get(hass)
    readings: dict[str, str] = {}
    for entry in er.async_entries_for_device(registry, device_id):
        if entry.domain != NUMBER_DOMAIN or entry.platform != DOMAIN:
            continue
        state = hass.states.get(entry.entity_id)
        if state is None:
            continue
        device_number = state.attributes.get(ATTR_DEVICE_NUMBER)
        if device_number is None or device_number not in valid_numbers:
            continue
        try:
            value = float(state.state)
        except (TypeError, ValueError):
            _LOGGER.warning(
                "send_readings: значение %s в %s не приводится к числу",
                state.state,
                entry.entity_id,
            )
            continue
        readings[device_number] = str(value)
    return readings


def _collect_readings_from_slots(
    hass: HomeAssistant, service_call: ServiceCall, valid_numbers: set[str], account: str
) -> dict[str, str]:
    """Read meter_N + meter_N_value pairs, validating ownership of the meter."""
    readings: dict[str, str] = {}
    for i in range(1, METER_SLOTS + 1):
        entity_id = service_call.data.get(f"meter_{i}")
        value = service_call.data.get(f"meter_{i}_value")
        if entity_id is None and value is None:
            continue
        if entity_id is None or value is None:
            raise HomeAssistantError(
                f"send_readings: слот #{i} заполнен частично — " "укажите и счётчик, и значение."
            )
        state = hass.states.get(entity_id)
        if state is None:
            raise HomeAssistantError(f"send_readings: сенсор {entity_id} не найден.")
        device_number = state.attributes.get(ATTR_DEVICE_NUMBER)
        if device_number is None:
            raise HomeAssistantError(
                f"send_readings: у сенсора {entity_id} нет атрибута device_number."
            )
        if device_number not in valid_numbers:
            raise HomeAssistantError(
                f"send_readings: счётчик {entity_id} (№{device_number}) "
                f"не относится к ЛС {account}."
            )
        readings[device_number] = str(float(value))
    return readings


async def _async_handle_send_readings(
    hass: HomeAssistant, service_call: ServiceCall, coordinator: BCNNCoordinator
) -> dict[str, Any]:
    valid_numbers = {
        m.get("device_number")
        for m in (coordinator.data.get(CONF_READINGS) or [])
        if m.get("device_number")
    }
    if not valid_numbers:
        raise HomeAssistantError(
            f"{service_call.service}: нет известных счётчиков — сначала обновите данные."
        )

    provided = service_call.data.get(ATTR_READINGS)
    slot_readings = _collect_readings_from_slots(
        hass, service_call, valid_numbers, coordinator.account
    )

    if provided:
        unknown = set(provided) - valid_numbers
        if unknown:
            raise HomeAssistantError(
                f"{service_call.service}: счётчики {sorted(unknown)} не относятся к ЛС {coordinator.account}."
            )
        readings = {device_number: str(float(v)) for device_number, v in provided.items()}
        readings.update(slot_readings)
    elif slot_readings:
        readings = slot_readings
    else:
        device_id = service_call.data[ATTR_DEVICE_ID]
        readings = _collect_readings_from_numbers(hass, device_id, valid_numbers)
        if not readings:
            raise HomeAssistantError(
                f"{service_call.service}: не задано ни одного значения "
                "(выберите счётчики, передайте readings или заполните number-сущности)."
            )

    _LOGGER.debug("send_readings: передаём показания %s", readings)
    result = await coordinator.async_send_readings(tuple(readings.items()))
    if result is None:
        raise HomeAssistantError(f"{service_call.service}: пустой ответ от API.")

    return {ATTR_READINGS: readings}


async def _async_handle_get_bill(
    hass: HomeAssistant, service_call: ServiceCall, coordinator: BCNNCoordinator
) -> dict[str, Any]:
    bill_date = get_previous_month()
    result = await coordinator.async_get_bill()
    if result is None:
        raise HomeAssistantError(f"{service_call.service}: пустой ответ от API.")

    bill_dir = hass.config.path("tmp")
    os.makedirs(bill_dir, exist_ok=True)
    path_file = os.path.join(bill_dir, f"bill_{coordinator.account}.pdf")

    def _write_pdf() -> None:
        with open(path_file, "wb") as fh:
            fh.write(result)

    await hass.async_add_executor_job(_write_pdf)

    return {
        ATTR_DATE: bill_date,
        CONF_URL: path_file,
    }


SERVICES: dict[str, ServiceDescription] = {
    SERVICE_REFRESH: ServiceDescription(
        SERVICE_REFRESH, _async_handle_refresh, SERVICE_REFRESH_SCHEMA
    ),
    SERVICE_SEND_READINGS: ServiceDescription(
        SERVICE_SEND_READINGS, _async_handle_send_readings, SERVICE_SEND_READINGS_SCHEMA
    ),
    SERVICE_GET_BILL: ServiceDescription(
        SERVICE_GET_BILL, _async_handle_get_bill, SERVICE_GET_BILL_SCHEMA
    ),
}


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register Center-SBK services (idempotent — safe to call per entry)."""

    async def _async_handle_service(service_call: ServiceCall) -> None:
        _LOGGER.debug("Service call: %s", service_call.service)
        try:
            device_id = service_call.data.get(ATTR_DEVICE_ID)
            coordinator = await async_get_coordinator(hass, device_id)
            result = await SERVICES[service_call.service].service_func(
                hass, service_call, coordinator
            )
            hass.bus.async_fire(
                event_type=f"{DOMAIN}_{service_call.service}_completed",
                event_data={ATTR_DEVICE_ID: device_id, **result},
                context=service_call.context,
            )
            _LOGGER.debug("Service call '%s' finished successfully", service_call.service)
        except HomeAssistantError:
            raise
        except Exception as exc:
            _LOGGER.error("Service call '%s' failed: %s", service_call.service, exc)
            hass.bus.async_fire(
                event_type=f"{DOMAIN}_{service_call.service}_failed",
                event_data={
                    ATTR_DEVICE_ID: service_call.data.get(ATTR_DEVICE_ID),
                    CONF_ERROR: str(exc),
                },
                context=service_call.context,
            )
            raise HomeAssistantError(f"Service call {service_call.service} failed: {exc}") from exc

    for service in SERVICES.values():
        if not hass.services.has_service(DOMAIN, service.name):
            hass.services.async_register(
                DOMAIN, service.name, _async_handle_service, service.schema
            )


async def async_unload_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove services only when the last Center-SBK entry is unloaded."""
    remaining = [
        e
        for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id and e.state.recoverable
    ]
    if remaining:
        return

    for service_name in SERVICES:
        hass.services.async_remove(domain=DOMAIN, service=service_name)
