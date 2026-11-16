"""Binary sensor platform for Livolo: gateway health (cloud connection)."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_HAS_ENTITY_NAME, DOMAIN
from .coordinator import LivoloDataUpdateCoordinator
from .entity_helpers import (
    DEVICE_STATUS_LABELS,
    DEVICE_STATUS_ONLINE,
    device_cloud_status,
    find_device,
    get_property_value,
    is_gateway,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[LivoloDataUpdateCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    devices = coordinator.data.get("devices", [])
    gateway_to_devices = coordinator.data.get("gateway_to_devices", {})

    entities = [
        LivoloGatewayConnectivity(
            coordinator,
            iot_id,
            device,
            sub_device_count=len(gateway_to_devices.get(iot_id, [])),
        )
        for device in devices
        if is_gateway(device) and (iot_id := device.get("iotId") or device.get("elementId"))
    ]
    async_add_entities(entities)


class LivoloGatewayConnectivity(CoordinatorEntity[LivoloDataUpdateCoordinator], BinarySensorEntity):
    """On when the Livolo cloud reports the gateway as online.

    The gateway keeps an MQTT session to the Alibaba IoT cloud; when its firmware hangs
    or it drops off Wi-Fi the cloud marks it offline (status 3) after the keepalive
    expires. The device still answering ping on the LAN does not prove it is working.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        device: dict[str, Any],
        sub_device_count: int,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._sub_device_count = sub_device_count
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
        )

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def is_on(self) -> bool | None:
        status = device_cloud_status(self._device())
        if status is None:
            return None
        return status == DEVICE_STATUS_ONLINE

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        device = self._device()
        status = device_cloud_status(device)
        return {
            "cloud_status": DEVICE_STATUS_LABELS.get(status, status),
            "ip_address": get_property_value(device, "IPAddress"),
            "product_name": (device or {}).get("productName"),
            "sub_devices": self._sub_device_count,
        }
