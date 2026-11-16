"""Binary sensor platform for Livolo: cloud connection of every device."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAS_ENTITY_NAME, DOMAIN
from .coordinator import LivoloDataUpdateCoordinator
from .device_property_utils import CLOUD_STATUS_ONLINE, get_cloud_status
from .entity_helpers import find_device, is_gateway


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[LivoloDataUpdateCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    devices = coordinator.data.get("devices", [])
    gateway_to_devices = coordinator.data.get("gateway_to_devices", {})

    device_to_gateway: dict[str, str] = {}
    for gateway_id, device_ids in gateway_to_devices.items():
        for device_id in device_ids:
            device_to_gateway[device_id] = gateway_id

    entities: list[LivoloCloudConnectivity] = []
    for device in devices:
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue
        gateway_iot_id = None if is_gateway(device) else device_to_gateway.get(iot_id)
        entities.append(LivoloCloudConnectivity(coordinator, iot_id, device, gateway_iot_id))
    async_add_entities(entities)


class LivoloCloudConnectivity(CoordinatorEntity[LivoloDataUpdateCoordinator], BinarySensorEntity):
    """On when the Livolo cloud reports the device as online (status 1).

    For gateways this reflects the gateway's session with the cloud. It does not prove
    that commands reach the sub-devices: a gateway can stay "online" while its link to
    the sub-devices is stuck.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        device: dict[str, Any],
        gateway_iot_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._attr_unique_id = f"{iot_id}_cloud_connectivity"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        device_name = device.get("nickName") or device.get("name") or iot_id
        self._attr_name = (
            "Cloud connection" if self._attr_has_entity_name else f"{device_name} Cloud connection"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device.get("categoryKey") or "Livolo",
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id else None,
        )

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def is_on(self) -> bool | None:
        status = get_cloud_status(self._device())
        if status is None:
            return None
        return status == CLOUD_STATUS_ONLINE
