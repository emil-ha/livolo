"""Number platform for Livolo numeric TSL controls."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAS_ENTITY_NAME, DOMAIN
from .coordinator import LivoloDataUpdateCoordinator
from .device_property_utils import get_android_range_hint, get_property_label, iter_numeric_entities
from .entity_helpers import find_device, get_property_value

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

    entities: list[LivoloNumberEntity] = []
    for device in devices:
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue
        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        gateway_iot_id = device_to_gateway.get(iot_id) if not is_gateway else None
        device_name = device.get("nickName") or device.get("name") or iot_id
        pk = device.get("productKey")

        for prop_id in iter_numeric_entities(device):
            entities.append(
                LivoloNumberEntity(
                    coordinator,
                    iot_id,
                    prop_id,
                    device_name,
                    device_info=device,
                    gateway_iot_id=gateway_iot_id,
                    product_key=pk,
                )
            )

    async_add_entities(entities)


class LivoloNumberEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], NumberEntity):
    """Numeric Livolo property."""

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        property_id: str,
        device_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None,
        product_key: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._property_id = property_id
        self._product_key = product_key
        self._attr_unique_id = f"{iot_id}_num_{property_id}"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        self._attr_name = get_property_label(property_id, product_key) or property_id

        hint = get_android_range_hint(property_id, product_key) or {}
        self._attr_native_min_value = float(hint.get("min", 0))
        self._attr_native_max_value = float(hint.get("max", 100))
        self._attr_native_step = float(hint.get("step", 1))
        if hint.get("unit") == "°C":
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

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
    def native_value(self) -> float | None:
        raw = get_property_value(self._device(), self._property_id)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        v = value
        if self._attr_native_step >= 1:
            v = int(round(value))
        await self.coordinator.set_device_property(self._iot_id, self._property_id, v)
