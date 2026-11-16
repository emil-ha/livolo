"""Shared helpers for Livolo entity platforms."""
from __future__ import annotations

import json
from typing import Any

from .device_property_utils import extract_property_value


def find_device(devices: list[dict[str, Any]], iot_id: str) -> dict[str, Any] | None:
    """Return device dict matching iotId/elementId."""
    for d in devices:
        if (d.get("iotId") or d.get("elementId")) == iot_id:
            return d
    return None


def get_property_value(device: dict[str, Any] | None, prop_id: str) -> Any:
    """Resolved property value (unwraps nested Livolo struct shape)."""
    if not device:
        return None
    for p in device.get("propertyList") or []:
        if p.get("identifier") == prop_id:
            return extract_property_value(p)
    return None


def is_gateway(device: dict[str, Any]) -> bool:
    """True for Livolo gateways (hubs that own sub-devices)."""
    return device.get("nodeType") == "GATEWAY" or device.get("categoryKey") == "GeneralGateway"


# Alibaba IoT device status codes returned in the device list ("status" field).
DEVICE_STATUS_ONLINE = 1
DEVICE_STATUS_LABELS = {0: "inactive", 1: "online", 3: "offline", 8: "disabled"}


def device_cloud_status(device: dict[str, Any] | None) -> int | None:
    """Cloud connection status code of a device, or None when unknown."""
    if not device:
        return None
    raw = device.get("status")
    if isinstance(raw, dict):
        raw = raw.get("value")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def normalize_on(value: Any) -> bool:
    return value in (1, True, "1")


def parse_livolo_hsv_struct(raw: Any) -> dict[str, float] | None:
    """Parse Livolo HSVColor (JSON string or dict) to Hue/Saturation/Value."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        d = raw
    elif isinstance(raw, str):
        try:
            d = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        return None
    if not isinstance(d, dict):
        return None
    return {
        "Hue": float(d.get("Hue", 0)),
        "Saturation": float(d.get("Saturation", 0)),
        "Value": float(d.get("Value", 0)),
    }


def hs_color_tuple_from_hsv_property(raw: Any) -> tuple[float, float] | None:
    """HA hs_color: hue 0–360, saturation 0–100 (Livolo uses same scale in mocks)."""
    d = parse_livolo_hsv_struct(raw)
    if not d:
        return None
    return (d["Hue"], d["Saturation"])
