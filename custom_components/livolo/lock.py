"""Lock platform for Livolo lock devices (Status property)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAS_ENTITY_NAME, DOMAIN
from .coordinator import LivoloDataUpdateCoordinator
from .device_property_utils import get_property_label, should_create_lock
from .entity_helpers import find_device, get_property_value, normalize_on

_LOGGER = logging.getLogger(__name__)

_STATUS_PROP = "Status"


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

    entities: list[LivoloLockEntity] = []
    for device in devices:
        if not should_create_lock(device):
            continue
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue
        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        gateway_iot_id = device_to_gateway.get(iot_id) if not is_gateway else None
        device_name = device.get("nickName") or device.get("name") or iot_id
        entities.append(
            LivoloLockEntity(
                coordinator,
                iot_id,
                device_name,
                device_info=device,
                gateway_iot_id=gateway_iot_id,
            )
        )

    async_add_entities(entities)


class LivoloLockEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], LockEntity):
    """Lock state from Livolo Status (1 = locked in mock payloads)."""

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
        self._attr_unique_id = f"{iot_id}_lock"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        pk = device_info.get("productKey")
        self._attr_name = get_property_label(_STATUS_PROP, pk) or "Lock"

        is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or "Livolo Lock",
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
        )

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def is_locked(self) -> bool | None:
        raw = get_property_value(self._device(), _STATUS_PROP)
        if raw is None:
            return None
        return normalize_on(raw)

    async def async_lock(self, **kwargs: Any) -> None:
        await self.coordinator.set_device_property(self._iot_id, _STATUS_PROP, 1)

    async def async_unlock(self, **kwargs: Any) -> None:
        await self.coordinator.set_device_property(self._iot_id, _STATUS_PROP, 0)
