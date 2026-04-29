"""Light platform for Livolo (dimmers and smart lights)."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
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
    iter_dimmer_light_channels,
    iter_power_switch_light_identifiers,
    should_create_smart_light,
    smart_light_brightness_property,
    smart_light_color_temp_property,
    smart_light_has_hsv,
)
from .entity_helpers import (
    find_device,
    get_property_value,
    hs_color_tuple_from_hsv_property,
    normalize_on,
    parse_livolo_hsv_struct,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[LivoloDataUpdateCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Livolo light entities."""
    coordinator = entry.runtime_data

    entities: list[LightEntity] = []
    devices = coordinator.data.get("devices", [])
    gateway_to_devices = coordinator.data.get("gateway_to_devices", {})

    if not devices:
        _LOGGER.warning("No devices found, entities will be added after first update")
        return

    device_to_gateway: dict[str, str] = {}
    for gateway_id, device_ids in gateway_to_devices.items():
        for device_id in device_ids:
            device_to_gateway[device_id] = gateway_id

    from homeassistant.helpers import device_registry as dr

    device_registry = dr.async_get(hass)

    for device in devices:
        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        if is_gateway:
            gateway_element_id = device.get("iotId") or device.get("elementId")
            if gateway_element_id:
                device_registry.async_get_or_create(
                    config_entry_id=entry.entry_id,
                    identifiers={(DOMAIN, gateway_element_id)},
                    name=device.get("nickName") or device.get("name") or "Livolo Gateway",
                    manufacturer="Livolo",
                    model=device.get("categoryKey") or "Livolo Gateway",
                )

    for device in devices:
        iot_id = device.get("iotId") or device.get("elementId")
        if not iot_id:
            continue

        is_gateway = device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"
        gateway_iot_id = device_to_gateway.get(iot_id) if not is_gateway else None
        device_name = device.get("nickName") or device.get("name") or iot_id

        for prop_id in iter_power_switch_light_identifiers(device):
            entities.append(
                LivoloOnOffLightEntity(
                    coordinator,
                    iot_id,
                    prop_id,
                    device_name,
                    device_info=device,
                    gateway_iot_id=gateway_iot_id,
                )
            )

        for power_id, bri_id in iter_dimmer_light_channels(device):
            entities.append(
                LivoloDimmerLightEntity(
                    coordinator,
                    iot_id,
                    power_id,
                    bri_id,
                    device_name,
                    device_info=device,
                    gateway_iot_id=gateway_iot_id,
                )
            )

        if should_create_smart_light(device):
            bri_prop = smart_light_brightness_property(device)
            ct_prop = smart_light_color_temp_property(device)
            entities.append(
                LivoloSmartLightEntity(
                    coordinator,
                    iot_id,
                    device_name,
                    device_info=device,
                    gateway_iot_id=gateway_iot_id,
                    brightness_property=bri_prop,
                    color_temp_property=ct_prop,
                    hsv_enabled=smart_light_has_hsv(device),
                )
            )

    async_add_entities(entities)


class LivoloOnOffLightEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], LightEntity):
    """On/off light for PowerSwitch / PowerSwitch_* (wall channels)."""

    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_color_mode = ColorMode.ONOFF

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        property_id: str,
        device_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._property_id = property_id
        self._attr_unique_id = f"{iot_id}_{property_id}"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        self._attr_name = _display_name_for_property(device_info, property_id, property_id)

        is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or ("Livolo Gateway" if is_gateway else "Livolo"),
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
        )

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def is_on(self) -> bool:
        return normalize_on(get_property_value(self._device(), self._property_id))

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.set_device_property(self._iot_id, self._property_id, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_device_property(self._iot_id, self._property_id, 0)


def _display_name_for_property(
    device_info: dict[str, Any], property_id: str, fallback: str
) -> str:
    switch_details = device_info.get("switchDetails", {}).get(property_id, {})
    name = switch_details.get("buttonName") or ""
    if name and "电" not in name and name != property_id:
        return name
    return get_property_label(property_id, device_info.get("productKey")) or fallback


class LivoloDimmerLightEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], LightEntity):
    """Dimmer channel: power + optional brightness (0–100 in Livolo)."""

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        power_property_id: str,
        brightness_property_id: str | None,
        device_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._power_property_id = power_property_id
        self._brightness_property_id = brightness_property_id
        self._attr_unique_id = f"{iot_id}_dimmer_{power_property_id}_{brightness_property_id or 'none'}"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        label = _display_name_for_property(device_info, power_property_id, power_property_id)
        self._attr_name = label

        is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or ("Livolo Gateway" if is_gateway else "Livolo"),
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
        )

        if brightness_property_id:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.ONOFF}
            self._attr_color_mode = ColorMode.ONOFF

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def is_on(self) -> bool:
        return normalize_on(get_property_value(self._device(), self._power_property_id))

    @property
    def brightness(self) -> int | None:
        if not self._brightness_property_id:
            return None
        raw = get_property_value(self._device(), self._brightness_property_id)
        try:
            pct = float(raw)
        except (TypeError, ValueError):
            return None
        return max(0, min(255, int(round(pct * 255 / 100))))

    async def async_turn_on(self, **kwargs: Any) -> None:
        if self._brightness_property_id and ATTR_BRIGHTNESS in kwargs:
            pct = max(0, min(100, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)))
            await self.coordinator.set_device_property(
                self._iot_id, self._brightness_property_id, int(pct)
            )
            if self._power_property_id == "on":
                await self.coordinator.set_device_property(
                    self._iot_id, "on", 1 if pct > 0 else 0
                )
                return
        await self.coordinator.set_device_property(self._iot_id, self._power_property_id, 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_device_property(self._iot_id, self._power_property_id, 0)
        if self._brightness_property_id and self._power_property_id == "on":
            await self.coordinator.set_device_property(
                self._iot_id, self._brightness_property_id, 0
            )


class LivoloSmartLightEntity(CoordinatorEntity[LivoloDataUpdateCoordinator], LightEntity):
    """Smart light: powerstate + optional brightness, color temp, HSV (matches DeviceCard)."""

    def __init__(
        self,
        coordinator: LivoloDataUpdateCoordinator,
        iot_id: str,
        device_name: str,
        device_info: dict[str, Any],
        gateway_iot_id: str | None,
        brightness_property: str | None,
        color_temp_property: str | None,
        hsv_enabled: bool,
    ) -> None:
        super().__init__(coordinator)
        self._iot_id = iot_id
        self._bri_prop = brightness_property
        self._ct_prop = color_temp_property
        self._hsv = hsv_enabled
        self._attr_unique_id = f"{iot_id}_smartlight"
        self._attr_has_entity_name = bool(
            coordinator.entry.options.get(CONF_HAS_ENTITY_NAME, False)
        )
        self._attr_name = device_name

        is_gateway = device_info.get("nodeType") == "GATEWAY" or device_info.get("categoryKey") == "GeneralGateway"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, iot_id)},
            name=device_name,
            manufacturer="Livolo",
            model=device_info.get("categoryKey") or "Livolo Light",
            via_device=(DOMAIN, gateway_iot_id) if gateway_iot_id and not is_gateway else None,
        )

        # Home Assistant validates supported_color_modes strictly:
        # - HS implies brightness, so don't also declare BRIGHTNESS.
        # - COLOR_TEMP implies brightness, so don't also declare BRIGHTNESS.
        # - ONOFF must not be combined with other modes.
        modes: set[ColorMode] = set()
        if self._hsv:
            modes.add(ColorMode.HS)
        if self._ct_prop:
            modes.add(ColorMode.COLOR_TEMP)
        if not modes and self._bri_prop:
            modes.add(ColorMode.BRIGHTNESS)
        self._attr_supported_color_modes = modes or {ColorMode.ONOFF}

    def _device(self) -> dict[str, Any] | None:
        return find_device(self.coordinator.data.get("devices", []), self._iot_id)

    @property
    def color_mode(self) -> ColorMode:
        if not self.is_on:
            return ColorMode.ONOFF
        if self._ct_prop and ColorMode.COLOR_TEMP in self.supported_color_modes:
            return ColorMode.COLOR_TEMP
        if self._hsv and ColorMode.HS in self.supported_color_modes:
            return ColorMode.HS
        if self._bri_prop and ColorMode.BRIGHTNESS in self.supported_color_modes:
            return ColorMode.BRIGHTNESS
        if ColorMode.BRIGHTNESS in self.supported_color_modes:
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def is_on(self) -> bool:
        return normalize_on(get_property_value(self._device(), "powerstate"))

    @property
    def brightness(self) -> int | None:
        if self._bri_prop:
            raw = get_property_value(self._device(), self._bri_prop)
        elif self._hsv:
            d = parse_livolo_hsv_struct(get_property_value(self._device(), "HSVColor"))
            if not d:
                return None
            raw = d["Value"]
        else:
            return None
        try:
            pct = float(raw)
        except (TypeError, ValueError):
            return None
        return max(0, min(255, int(round(pct * 255 / 100))))

    @property
    def hs_color(self) -> tuple[float, float] | None:
        if not self._hsv:
            return None
        return hs_color_tuple_from_hsv_property(get_property_value(self._device(), "HSVColor"))

    @property
    def color_temp_kelvin(self) -> int | None:
        if not self._ct_prop:
            return None
        raw = get_property_value(self._device(), self._ct_prop)
        try:
            k = int(float(raw))
        except (TypeError, ValueError):
            return None
        return max(2000, min(10000, k))

    @property
    def min_color_temp_kelvin(self) -> int:
        return 2000

    @property
    def max_color_temp_kelvin(self) -> int:
        return 6500

    async def async_turn_on(self, **kwargs: Any) -> None:
        dev = self._device()
        hsv_raw = get_property_value(dev, "HSVColor") if self._hsv else None
        cur_hsv = parse_livolo_hsv_struct(hsv_raw) or {}

        if self._hsv and ATTR_HS_COLOR in kwargs:
            hs = kwargs[ATTR_HS_COLOR]
            v = float(cur_hsv.get("Value", 100.0))
            if ATTR_BRIGHTNESS in kwargs:
                v = max(0.0, min(100.0, kwargs[ATTR_BRIGHTNESS] * 100.0 / 255.0))
            payload = {
                "Hue": float(hs[0]),
                "Saturation": float(hs[1]),
                "Value": v,
            }
            await self.coordinator.set_device_property(self._iot_id, "HSVColor", payload)
        elif self._hsv and ATTR_BRIGHTNESS in kwargs and not self._bri_prop:
            v = max(0.0, min(100.0, kwargs[ATTR_BRIGHTNESS] * 100.0 / 255.0))
            payload = {
                "Hue": float(cur_hsv.get("Hue", 0.0)),
                "Saturation": float(cur_hsv.get("Saturation", 0.0)),
                "Value": v,
            }
            await self.coordinator.set_device_property(self._iot_id, "HSVColor", payload)
        elif self._bri_prop and ATTR_BRIGHTNESS in kwargs:
            pct = max(0, min(100, round(kwargs[ATTR_BRIGHTNESS] * 100 / 255)))
            await self.coordinator.set_device_property(self._iot_id, self._bri_prop, int(pct))
        if self._ct_prop and ATTR_COLOR_TEMP_KELVIN in kwargs:
            await self.coordinator.set_device_property(
                self._iot_id, self._ct_prop, int(kwargs[ATTR_COLOR_TEMP_KELVIN])
            )
        await self.coordinator.set_device_property(self._iot_id, "powerstate", 1)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.set_device_property(self._iot_id, "powerstate", 0)
