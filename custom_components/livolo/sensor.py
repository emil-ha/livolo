"""Sensor platform for Livolo read-only properties."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAS_ENTITY_NAME, DOMAIN
from .coordinator import LivoloDataUpdateCoordinator
from .device_property_utils import format_readonly_value, get_property_label, iter_readonly_sensor_properties
from .entity_helpers import find_device, get_property_value

_LOGGER = logging.getLogger(__name__)


def _sensor_meta(prop_id: str) -> tuple[str | None, str | None, SensorStateClass | None]:
    if prop_id == "BatteryPercentage":
        return SensorDeviceClass.BATTERY, PERCENTAGE, SensorStateClass.MEASUREMENT
    if prop_id in ("CurrentTemperature",):
        return SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, SensorStateClass.MEASUREMENT
    if prop_id == "CurrentFahrenheit":
        return SensorDeviceClass.TEMPERATURE, UnitOfTemperature.FAHRENHEIT, SensorStateClass.MEASUREMENT
    if prop_id == "CurrentHumidity":
        return SensorDeviceClass.HUMIDITY, PERCENTAGE, SensorStateClass.MEASUREMENT
    if prop_id in ("MeasuredIlluminance", "Level"):
        return SensorDeviceClass.ILLUMINANCE, "lx", SensorStateClass.MEASUREMENT
    if prop_id == "MeasuredVoice":
        return None, None, SensorStateClass.MEASUREMENT
    if prop_id == "RealTimePower":
        return SensorDeviceClass.POWER, UnitOfPower.WATT, SensorStateClass.MEASUREMENT
    if prop_id == "CurrentVoltage":
        return SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, SensorStateClass.MEASUREMENT
    if prop_id == "Current":
        return SensorDeviceClass.CURRENT, UnitOfElectricCurrent.AMPERE, SensorStateClass.MEASUREMENT
    return None, None, None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[LivoloDataUpdateCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    devices = coordinator.data.get("devices", [])
    gateway_to_devices = coordinator.data.get("gateway_to_devices", {})

    if not devices:
        return

    device_to_gateway: dict[str, str] = {}
    for gateway_id, device_ids in gateway_to_devices.items():
        for device_id in device_ids:
            device_to_gateway[device_id] = gateway_id

    entities: list[LivoloSensorEntity] = []
    for device in devices:
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue
        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        gateway_iot_id = device_to_gateway.get(iot_id) if not is_gateway else None
        device_name = device.get("nickName") or device.get("name") or iot_id
        pk = device.get("productKey")

        for prop_id in iter_readonly_sensor_properties(device):
            dc, unit, state_class = _sensor_meta(prop_id)
            entities.append(
                LivoloSensorEntity(
                    coordinator,
                    iot_id,
                    prop_id,
                    device_name,
                    device_info=device,
                    gateway_iot_id=gateway_iot_id,
                    product_key=pk,
                    device_class=dc,
                    native_unit=unit,
                    state_class=state_class,
                )
            )

    async_add_entities(entities)


class LivoloSensorEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], SensorEntity):
    """Read-only Livolo property."""

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        property_id: str,
        device_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None,
        product_key: str | None,
        device_class: str | None,
        native_unit: str | None,
        state_class: SensorStateClass | None,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._property_id = property_id
        self._attr_unique_id = f"{iot_id}_sensor_{property_id}"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        self._attr_name = get_property_label(property_id, product_key) or property_id
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = native_unit
        self._attr_state_class = state_class

        is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or "Livolo",
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
        )

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def native_value(self) -> str | float | int | None:
        raw = get_property_value(self._device(), self._property_id)
        if self._attr_device_class in (
            SensorDeviceClass.TEMPERATURE,
            SensorDeviceClass.HUMIDITY,
            SensorDeviceClass.BATTERY,
            SensorDeviceClass.POWER,
            SensorDeviceClass.VOLTAGE,
            SensorDeviceClass.CURRENT,
            SensorDeviceClass.ILLUMINANCE,
        ):
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return raw
        return format_readonly_value(raw)
