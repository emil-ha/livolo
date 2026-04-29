"""Cover platform for Livolo curtains."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAS_ENTITY_NAME, DOMAIN
from .coordinator import LivoloDataUpdateCoordinator
from .device_property_utils import (
    get_property_label,
    has_curtain_cover,
    has_curtain_operation_only,
    has_curtain_position,
)
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

    entities: list[LivoloCoverEntity] = []
    for device in devices:
        if not has_curtain_cover(device):
            continue
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue
        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        gateway_iot_id = device_to_gateway.get(iot_id) if not is_gateway else None
        device_name = device.get("nickName") or device.get("name") or iot_id
        pl = device.get("propertyList") or []
        has_pos = has_curtain_position(device)
        has_op = any(p.get("identifier") == "CurtainOperation" for p in pl)
        entities.append(
            LivoloCoverEntity(
                coordinator,
                iot_id,
                device_name,
                device_info=device,
                gateway_iot_id=gateway_iot_id,
                has_position=has_pos,
                has_operation=has_op and (has_pos or has_curtain_operation_only(device)),
            )
        )

    async_add_entities(entities)


class LivoloCoverEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], CoverEntity):
    """Curtain: position and/or CurtainOperation (open/close/stop)."""

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        device_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None,
        has_position: bool,
        has_operation: bool,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._has_position = has_position
        self._has_operation = has_operation
        self._attr_unique_id = f"{iot_id}_cover"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        self._attr_name = (
            get_property_label("CurtainPosition", device_info.get("productKey")) or "Curtain"
        )

        is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or "Livolo Curtain",
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
        )

        if has_position:
            feat = CoverEntityFeature.SET_POSITION
            if has_operation:
                feat |= CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
            self._attr_supported_features = feat
        elif has_operation:
            self._attr_supported_features = (
                CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
            )
        else:
            self._attr_supported_features = CoverEntityFeature(0)

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def current_cover_position(self) -> int | None:
        if not self._has_position:
            return None
        raw = get_property_value(self._device(), "CurtainPosition")
        try:
            pos = int(float(raw))
        except (TypeError, ValueError):
            return None
        return max(0, min(100, pos))

    @property
    def is_closed(self) -> bool | None:
        pos = self.current_cover_position
        if pos is None:
            return None
        return pos <= 2

    async def async_open_cover(self, **kwargs: Any) -> None:
        if self._has_operation:
            await self.coordinator.set_device_property(self._iot_id, "CurtainOperation", 1)
        elif self._has_position:
            await self.coordinator.set_device_property(self._iot_id, "CurtainPosition", 100)

    async def async_close_cover(self, **kwargs: Any) -> None:
        if self._has_operation:
            await self.coordinator.set_device_property(self._iot_id, "CurtainOperation", 0)
        elif self._has_position:
            await self.coordinator.set_device_property(self._iot_id, "CurtainPosition", 0)

    async def async_stop_cover(self, **kwargs: Any) -> None:
        if self._has_operation:
            await self.coordinator.set_device_property(self._iot_id, "CurtainOperation", 2)

    async def async_set_cover_position(self, **kwargs: Any) -> None:
        if not self._has_position:
            return
        pos = kwargs.get(ATTR_POSITION)
        if pos is None:
            return
        await self.coordinator.set_device_property(
            self._iot_id, "CurtainPosition", int(max(0, min(100, pos)))
        )
