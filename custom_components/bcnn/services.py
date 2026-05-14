"""Center-SBK services."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Awaitable
from dataclasses import dataclass
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, CONF_URL, ATTR_DATE, CONF_ERROR
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv

from .const import (
    DOMAIN,
    CONF_READINGS,
    ATTR_CW_1,
    ATTR_CW_1_VAL,
    ATTR_HW_1,
    ATTR_HW_1_VAL,
    ATTR_HW_2,
    ATTR_HW_2_VAL,
    ATTR_CW_2,
    ATTR_CW_2_VAL,
    ATTR_READINGS,
)
from .coordinator import BCNNCoordinator
from .helpers import (
    get_float_value,
    async_get_coordinator,
    get_previous_month,
)

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH = "refresh"
SERVICE_SEND_READINGS = "send_readings"
SERVICE_GET_BILL = "get_bill"

SERVICE_BASE_SCHEMA = {vol.Required(ATTR_DEVICE_ID): cv.string}

SERVICE_REFRESH_SCHEMA = vol.Schema({**SERVICE_BASE_SCHEMA})

SERVICE_SEND_READINGS_SCHEMA = vol.Schema(
    {
        **SERVICE_BASE_SCHEMA,
        vol.Required(ATTR_CW_1): cv.entity_id,
        vol.Required(ATTR_CW_1_VAL): cv.entity_id,
        vol.Optional(ATTR_HW_1): cv.entity_id,
        vol.Optional(ATTR_HW_1_VAL): cv.entity_id,
        vol.Optional(ATTR_CW_2): cv.entity_id,
        vol.Optional(ATTR_CW_2_VAL): cv.entity_id,
        vol.Optional(ATTR_HW_2): cv.entity_id,
        vol.Optional(ATTR_HW_2_VAL): cv.entity_id,
    }
)

SERVICE_GET_BILL_SCHEMA = vol.Schema({**SERVICE_BASE_SCHEMA})


@dataclass
class ServiceDescription:
    name: str
    service_func: Callable[
        [HomeAssistant, ServiceCall, BCNNCoordinator], Awaitable[dict[str, Any]]
    ]
    schema: vol.Schema | None = None


async def _async_handle_refresh(
    hass: HomeAssistant, service_call: ServiceCall, coordinator: BCNNCoordinator
) -> dict[str, Any]:
    await coordinator.async_refresh()
    return {}


async def _async_handle_send_readings(
    hass: HomeAssistant, service_call: ServiceCall, coordinator: BCNNCoordinator
) -> dict[str, Any]:
    meters = (
        (ATTR_CW_1, ATTR_CW_1_VAL),
        (ATTR_HW_1, ATTR_HW_1_VAL),
        (ATTR_HW_2, ATTR_HW_2_VAL),
        (ATTR_CW_2, ATTR_CW_2_VAL),
    )
    readings: dict[str, str] = {}
    _LOGGER.debug("send_readings data: %s", service_call.data)

    for meter, meter_val in meters:
        meter_entity_id = service_call.data.get(meter)
        meter_value = get_float_value(hass, service_call.data.get(meter_val))
        if meter_entity_id is None or meter_value is None:
            continue
        meter_state = hass.states.get(meter_entity_id)
        if meter_state is None:
            continue
        device_number = meter_state.attributes.get("device_number")
        if device_number:
            readings[device_number] = str(float(meter_value))

    if len(coordinator.data[CONF_READINGS]) != len(readings):
        raise HomeAssistantError(
            f"{service_call.service}: несоответствие числа счётчиков для "
            f'"{coordinator.account}": получено {len(readings)}, '
            f"ожидается {len(coordinator.data[CONF_READINGS])}"
        )

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
            raise HomeAssistantError(
                f"Service call {service_call.service} failed: {exc}"
            ) from exc

    for service in SERVICES.values():
        if not hass.services.has_service(DOMAIN, service.name):
            hass.services.async_register(
                DOMAIN, service.name, _async_handle_service, service.schema
            )


async def async_unload_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove services only when the last Center-SBK entry is unloaded."""
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.entry_id != entry.entry_id and e.state.recoverable
    ]
    if remaining:
        return

    for service_name in SERVICES:
        hass.services.async_remove(domain=DOMAIN, service=service_name)
