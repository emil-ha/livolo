"""Climate platform for Livolo TRV and EC thermostat."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAS_ENTITY_NAME, DOMAIN
from .coordinator import LivoloDataUpdateCoordinator
from .device_property_utils import (
    get_property_label,
    is_ec_thermostat_climate,
    is_trv_climate,
)
from .entity_helpers import find_device, get_property_value, normalize_on

_LOGGER = logging.getLogger(__name__)


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

    entities: list[ClimateEntity] = []
    for device in devices:
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue
        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        gateway_iot_id = device_to_gateway.get(iot_id) if not is_gateway else None
        device_name = device.get("nickName") or device.get("name") or iot_id

        if is_trv_climate(device):
            entities.append(
                LivoloTrvClimateEntity(
                    coordinator,
                    iot_id,
                    device_name,
                    device_info=device,
                    gateway_iot_id=gateway_iot_id,
                )
            )
        elif is_ec_thermostat_climate(device):
            entities.append(
                LivoloEcThermostatClimateEntity(
                    coordinator,
                    iot_id,
                    device_name,
                    device_info=device,
                    gateway_iot_id=gateway_iot_id,
                )
            )

    async_add_entities(entities)


class LivoloTrvClimateEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], ClimateEntity):
    """Radiator valve (a1fVBnQNQZd): AnalogValue2 current, AnalogValue3 target, PowerSwitch_1 relay."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = 5.0
    _attr_max_temp = 30.0
    _attr_target_temperature_step = 1.0

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        device_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._attr_unique_id = f"{iot_id}_climate_trv"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        self._attr_name = get_property_label("AnalogValue3", "a1fVBnQNQZd")

        is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or "Livolo TRV",
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
        )

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def hvac_mode(self) -> HVACMode:
        if not normalize_on(get_property_value(self._device(), "PowerSwitch_1")):
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def current_temperature(self) -> float | None:
        raw = get_property_value(self._device(), "AnalogValue2")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @property
    def target_temperature(self) -> float | None:
        raw = get_property_value(self._device(), "AnalogValue3")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.set_device_property(self._iot_id, "PowerSwitch_1", 0)
        else:
            await self.coordinator.set_device_property(self._iot_id, "PowerSwitch_1", 1)
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        await self.coordinator.set_device_property(self._iot_id, "AnalogValue3", int(round(float(temp))))


class LivoloEcThermostatClimateEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], ClimateEntity):
    """EC thermostat: ScreenMode power, TargetTemperature, CurrentTemperature."""

    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE
    _attr_min_temp = 0.0
    _attr_max_temp = 50.0
    _attr_target_temperature_step = 0.5

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        device_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._attr_unique_id = f"{iot_id}_climate_ec"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        self._attr_name = device_name

        is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or "Livolo Thermostat",
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
        )

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def hvac_mode(self) -> HVACMode:
        if not normalize_on(get_property_value(self._device(), "ScreenMode")):
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def current_temperature(self) -> float | None:
        raw = get_property_value(self._device(), "CurrentTemperature")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    @property
    def target_temperature(self) -> float | None:
        raw = get_property_value(self._device(), "TargetTemperature")
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self.coordinator.set_device_property(self._iot_id, "ScreenMode", 0)
        else:
            await self.coordinator.set_device_property(self._iot_id, "ScreenMode", 1)
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        temp = kwargs.get("temperature")
        if temp is None:
            return
        await self.coordinator.set_device_property(
            self._iot_id, "TargetTemperature", int(round(float(temp)))
        )
