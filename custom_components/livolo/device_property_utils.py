"""Livolo TSL property helpers — aligned with livolo-frontend devicePropertyUtils.js."""
from __future__ import annotations

import json
from typing import Any

SMART_LIGHT_PRODUCT_KEYS = frozenset({"a1pPiEXahAk", "a1eqRoAMvAE", "a1tZKOdSDZ6"})

# categoryKey: wall-style devices use PowerSwitch* as lights; Socket uses SocketSwitch* (and Power* on some socket SKUs) as switches.
WALL_SWITCH_LIGHT_CATEGORIES = frozenset({"WallSwitch", "Dimmer"})
SOCKET_CATEGORY = "Socket"

# productKey -> list of control identifiers (mirrors Android ProductTool)
_PRODUCT_CONTROL_PROPERTIES: dict[str, list[str]] = {
    "ecswitch": [],
    "a2dajwFdCKY": ["PowerSwitch_1"],
    "a2eVlMRRgcG": ["PowerSwitch_1", "PowerSwitch_2"],
    "a2PTqMw3fJs": ["PowerSwitch_1", "PowerSwitch_2", "PowerSwitch_3"],
    "a29rkRBKMOR": ["PowerSwitch_1", "PowerSwitch_2", "PowerSwitch_3", "PowerSwitch_4"],
    "a24T6EXbXVi": [
        "PowerSwitch_1",
        "PowerSwitch_2",
        "PowerSwitch_3",
        "PowerSwitch_4",
        "PowerSwitch_5",
    ],
    "a2M4ZB6cL0z": [
        "PowerSwitch_1",
        "PowerSwitch_2",
        "PowerSwitch_3",
        "PowerSwitch_4",
        "PowerSwitch_5",
        "PowerSwitch_6",
    ],
    "a1GsAkk2Uc7": ["PowerSwitch_1", "PowerSwitch_2"],
    "a1qw374FdPw": ["PowerSwitch_1"],
    "a1DBHZJmarL": ["PowerSwitch_1", "PowerSwitch_2"],
    "a1MjmtrCvol": ["PowerSwitch_1", "PowerSwitch_2", "PowerSwitch_3"],
    "a1dcPD3IoCz": ["PowerSwitch_1"],
    "a2c6jLBqZNy": ["SocketSwitch_1"],
    "a1hsvy3mOfN": ["SocketSwitch_1"],
    "a1QTxJRCVK1": ["SocketSwitch_1"],
    "a184nv0z7Wz": ["SocketSwitch_1"],
    "a1x6t9A4A7i": ["SocketSwitch_1"],
    "a2qMZQYlh6V": ["SocketSwitch_1", "SocketSwitch_2"],
    "a2qMZQYlh6V_2": ["SocketSwitch_1", "SocketSwitch_2"],
    "a2eqOWErcAa": ["SocketSwitch_1", "SocketSwitch_2", "SocketSwitch_3"],
    "a1KlmsrNIVn": ["PowerSwitch"],
    "a1yJAmJczNk": ["SocketPowerState", "AutoSocketSta"],
    "a26AA7c5o6j": ["on", "bri"],
    "a2VWl4Ko6DY": ["PowerSwitch_1", "bri", "PowerSwitch_2", "bri_2"],
    "a2R4zYk3g0l": ["PowerSwitch_1", "PowerSwitch_2", "PowerSwitch_3", "bri"],
    "a2RG9UH6R3R": ["CurtainPosition", "CurtainOperation"],
    "a1IPvAvBSNl": ["CurtainPosition", "CurtainOperation", "ChangeDirection"],
    "a1qrHHEEgTO": ["CurtainPosition", "ModeSettings", "Speed"],
    "a1hf0pqoGhe": ["CurtainOperation"],
    "a1q0MMwUAy0": ["MotionTrackStatus", "StatusLightSwitch"],
    "a1pJyZvG7O7": ["MotionAlarmState", "DelayTime"],
    "a1X9X7v18Il": ["AlarmState", "DelayTime"],
    "a1Mx8l8jUlR": ["MotionAlarmState", "DelayTime"],
    "a2na33Z5FED": ["MeasuredIlluminance", "MeasuredVoice", "VoiceMode"],
    "a2NmZb9T8e9": ["CurrentTemperature", "CurrentFahrenheit", "CurrentHumidity", "DevConfig"],
    "a1fVBnQNQZd": [
        "PowerSwitch_1",
        "AnalogValue2",
        "AnalogValue1",
        "AnalogValue3",
        "AnalogValue4",
        "AnalogValue5",
    ],
    "a1R8f46KuB1": [
        "ScreenMode",
        "TargetTemperature",
        "CurrentTemperature",
        "DevConfig",
        "Speed",
        "StatusReminder",
        "TemperatureCalibrate",
        "bri",
        "SwitchStatus",
    ],
    "a1pPiEXahAk": ["powerstate", "HSVColor", "RGBMode"],
    "a1eqRoAMvAE": [
        "powerstate",
        "HSVColor",
        "brightness",
        "colorTemperature",
        "LightMode",
        "RGBMode",
    ],
    "a1tZKOdSDZ6": [
        "powerstate",
        "HSVColor",
        "brightness",
        "colorTemperature",
        "LightMode",
        "RGBMode",
    ],
    "a1apXR6h05T": [
        "AnalogValue1",
        "AnalogValue2",
        "AnalogValue3",
        "AnalogValue4",
        "AnalogValue5",
        "AnalogValue6",
    ],
    "a1wdgdLi1kN": ["PowerSwitch_1"],
    "a1zezmZf3xT": ["PowerSwitch_1", "PowerSwitch_2"],
    "a2AJLJl9IMI": ["AnalogValue1"],
    "a1JXLgXFcim": ["AnalogValue1", "BinaryValue1"],
    "a1PRNMs7ABY": ["AnalogValue1"],
    "a1lpBX0VQwA": ["powerstate"],
    "a1JAbEZVSUj": ["AnalogValue1", "AnalogValue2", "AnalogValue3", "AnalogValue4"],
    "a1AR2jJcTu1": ["alarm"],
}


def extract_property_value(prop: dict[str, Any] | None) -> Any:
    """Return raw value from a propertyList entry."""
    if not prop:
        return None
    v = prop.get("value")
    if v is not None and isinstance(v, dict) and "value" in v:
        return v.get("value")
    return v


def is_power_or_socket_switch(identifier: str | None) -> bool:
    if not identifier:
        return False
    return identifier.startswith("PowerSwitch_") or identifier.startswith("SocketSwitch_")


def is_wall_power_switch_property(identifier: str | None) -> bool:
    """Wall/relay power channels exposed as HA lights (not switches)."""
    if not identifier:
        return False
    return identifier == "PowerSwitch" or identifier.startswith("PowerSwitch_")


def is_curtain_operation(identifier: str | None) -> bool:
    return identifier == "CurtainOperation"


def is_curtain_position(identifier: str | None) -> bool:
    return identifier == "CurtainPosition"


def is_dimmer_on(identifier: str | None) -> bool:
    return identifier == "on"


def is_brightness_property(identifier: str | None) -> bool:
    if not identifier:
        return False
    return identifier in {
        "bri",
        "bri_1",
        "bri_2",
        "bri_3",
        "Brightness",
        "brightness",
    }


def is_color_temperature_property(identifier: str | None) -> bool:
    if not identifier:
        return False
    return identifier in {"ColorTemperature", "colorTemperature"}


def is_target_temperature_property(identifier: str | None) -> bool:
    return identifier == "TargetTemperature"


def is_numeric_control_property(identifier: str | None) -> bool:
    if not identifier:
        return False
    if identifier.startswith("AnalogValue"):
        return True
    return identifier in {
        "Speed",
        "DevConfig",
        "StatusReminder",
        "TemperatureCalibrate",
        "ChangeDirection",
        "ModeSettings",
        "SwitchStatus",
        "VoiceMode",
        "RGBMode",
        "LightMode",
        "AlarmState",
        "MotionAlarmState",
        "DelayTime",
    }


def get_product_control_properties(
    product_key: str | None, property_list: list[dict[str, Any]] | None = None
) -> set[str] | None:
    """Known products: set of control identifiers. Unknown: None."""
    if not product_key:
        return None
    if product_key == "a1WzhL5Rvtv":
        ids = {p.get("identifier") for p in (property_list or []) if p.get("identifier")}
        looks_speed = "AnalogValue1" in ids or "BinaryValue1" in ids
        return {"AnalogValue1", "BinaryValue1"} if looks_speed else {"on", "bri"}
    props = _PRODUCT_CONTROL_PROPERTIES.get(product_key)
    if props is None:
        return None
    return set(props)


def use_product_schema_filter(product_key: str | None, property_list: list[dict[str, Any]]) -> bool:
    """When True, only expose properties listed in the product schema (non-empty)."""
    allowed = get_product_control_properties(product_key, property_list)
    return allowed is not None and len(allowed) > 0


def _identifiers_on_device(property_list: list[dict[str, Any]]) -> set[str]:
    return {p.get("identifier") for p in property_list if p.get("identifier")}


def is_binary_control_property(identifier: str | None) -> bool:
    if not identifier:
        return False
    if is_power_or_socket_switch(identifier):
        return True
    return identifier in {
        "on",
        "powerstate",
        "LightSwitch",
        "WorkSwitch",
        "PowerSwitch",
        "ScreenMode",
        "AlarmSwitch",
        "StatusLightSwitch",
        "DeviceSwitch",
        "SocketPowerState",
        "AutoSocketSta",
        "alarm",
        "Alarm",
    }


def is_binary_value_toggle(identifier: str | None) -> bool:
    return identifier == "BinaryValue1"


def is_readonly_display_property(identifier: str | None) -> bool:
    if not identifier:
        return False
    if is_binary_control_property(identifier):
        return False
    if is_brightness_property(identifier):
        return False
    if is_color_temperature_property(identifier):
        return False
    if is_target_temperature_property(identifier):
        return False
    if is_numeric_control_property(identifier):
        return False
    if is_curtain_operation(identifier) or is_curtain_position(identifier):
        return False
    if is_binary_value_toggle(identifier):
        return False

    readonly = {
        "CurrentTemperature",
        "CurrentFahrenheit",
        "CurrentHumidity",
        "MeasuredIlluminance",
        "MeasuredVoice",
        "BatteryPercentage",
        "RealTimePower",
        "CurrentVoltage",
        "Current",
        "SoftwareInfo",
        "Version",
        "MacAddress",
        "WifiName",
        "IPAddress",
        "DelayTime",
        "InitDelay",
        "SecondDelayTime",
        "VoiceMode",
        "AlarmState",
        "MotionAlarmState",
        "MotionTrackStatus",
        "Level",
        "DevConfig",
        "StatusReminder",
        "TemperatureCalibrate",
        "HSVColor",
        "RGBMode",
        "LoadCurrent",
        "BaselineCurrent",
        "PositionCalibrate",
        "PositionLimited",
        "Group",
        "Protocol",
        "Status",
        "Range",
        "Alarm",
        "Sensitivity1",
        "Sensitivity2",
        "Sensitivity3",
        "Sensitivity4",
        "Sensitivity5",
        "Sensitivity6",
        "Sensitivity7",
        "Sensitivity8",
    }
    if identifier in readonly:
        return True
    if identifier.startswith("Sensitivity"):
        return True
    return False


def get_property_label(identifier: str | None, product_key: str | None = None) -> str:
    if not identifier:
        return ""
    simple = {
        "on": "On",
        "powerstate": "Power switch",
        "bri": "Brightness",
        "Brightness": "Brightness",
        "brightness": "Brightness",
        "CurtainPosition": "Curtain position",
        "CurtainOperation": "Curtain operation",
        "TargetTemperature": "Set temperature",
        "CurrentTemperature": "Current temperature (C)",
        "CurrentHumidity": "Current humidity",
        "MeasuredIlluminance": "Illuminance",
        "MeasuredVoice": "Sound level",
        "BatteryPercentage": "Battery",
        "Speed": "Speed",
        "ModeSettings": "Temperature unit",
        "ScreenMode": "Power switch",
    }
    if identifier in simple:
        return simple[identifier]
    if identifier.startswith("PowerSwitch_"):
        if identifier == "PowerSwitch_1" and product_key == "a1fVBnQNQZd":
            return "Power switch"
        n = identifier.replace("PowerSwitch_", "", 1)
        return f"Power switch {n}"
    if identifier.startswith("SocketSwitch_"):
        n = identifier.replace("SocketSwitch_", "", 1)
        return f"Socket switch {n}"
    if identifier.startswith("AnalogValue"):
        if identifier == "AnalogValue2" and product_key == "a1fVBnQNQZd":
            return "Temperature"
        if identifier == "AnalogValue3" and product_key == "a1fVBnQNQZd":
            return "Set temperature"
        return identifier.replace("_", " ")
    return identifier.replace("_", " ")


def get_android_range_hint(property_id: str | None, product_key: str | None) -> dict[str, Any] | None:
    if not property_id:
        return None
    if property_id == "TargetTemperature":
        return {"min": 0, "max": 50, "step": 0.5}
    if property_id == "TemperatureCalibrate":
        return {"min": -10, "max": 10, "step": 1}
    if property_id == "ChangeDirection":
        return {"min": 0, "max": 1, "step": 1}
    if property_id == "StatusReminder":
        return {"min": 0, "max": 1, "step": 1}
    if property_id == "DelayTime":
        return {"min": 0, "max": 100, "step": 1}
    if property_id == "AnalogValue2" and product_key == "a1fVBnQNQZd":
        return {"min": 5, "max": 30, "step": 1}
    if property_id == "AnalogValue1" and product_key == "a1JAbEZVSUj":
        return {"min": 1, "max": 44, "step": 1}
    return None


def iter_dimmer_light_channels(
    device: dict[str, Any],
) -> list[tuple[str, str | None]]:
    """(power_property_id, brightness_property_id or None) for light entities."""
    pk = device.get("productKey") or ""
    pl = device.get("propertyList") or []
    ids_on = _identifiers_on_device(pl)

    def _first_brightness_id() -> str | None:
        # Prefer the common dimmer keys first.
        for cand in ("bri", "Brightness", "brightness", "bri_1", "bri_2", "bri_3"):
            if cand in ids_on:
                return cand
        return None

    if pk == "a26AA7c5o6j" and "on" in ids_on:
        bri_id = _first_brightness_id()
        if bri_id:
            return [("on", bri_id)]
    if pk == "a2VWl4Ko6DY":
        out: list[tuple[str, str | None]] = []
        # Channel 1 brightness is commonly "bri" (sometimes "Brightness"/"brightness" on some firmwares).
        if "PowerSwitch_1" in ids_on:
            bri1 = "bri" if "bri" in ids_on else ("Brightness" if "Brightness" in ids_on else ("brightness" if "brightness" in ids_on else None))
            if bri1:
                out.append(("PowerSwitch_1", bri1))
        # Channel 2 brightness is commonly "bri_2".
        if "PowerSwitch_2" in ids_on and "bri_2" in ids_on:
            out.append(("PowerSwitch_2", "bri_2"))
        return out
    if pk == "a2R4zYk3g0l":
        # 3-gang dimmer: relays PowerSwitch_1..3 with a shared brightness ("bri" in app schema).
        bri_id = _first_brightness_id()
        if bri_id and "PowerSwitch_1" in ids_on:
            return [("PowerSwitch_1", bri_id)]
    if pk == "a1WzhL5Rvtv":
        allowed = get_product_control_properties(pk, pl)
        if allowed and "on" in allowed and "bri" in allowed and "on" in ids_on:
            bri_id = _first_brightness_id()
            if bri_id:
                return [("on", bri_id)]
    return []


def should_create_smart_light(device: dict[str, Any]) -> bool:
    pk = device.get("productKey") or ""
    ids_on = _identifiers_on_device(device.get("propertyList") or [])
    return pk in SMART_LIGHT_PRODUCT_KEYS and "powerstate" in ids_on


def iter_power_switch_light_identifiers(device: dict[str, Any]) -> list[str]:
    """PowerSwitch / PowerSwitch_* as on/off lights on wall-style categories only."""
    cat = device.get("categoryKey") or ""
    if cat not in WALL_SWITCH_LIGHT_CATEGORIES:
        return []

    pk = device.get("productKey") or ""
    pl = device.get("propertyList") or []
    ids_on = _identifiers_on_device(pl)
    use_filter = use_product_schema_filter(pk, pl)
    allowed = get_product_control_properties(pk, pl)
    if use_filter and allowed is not None:
        candidates = [i for i in allowed if i in ids_on]
    else:
        candidates = list(ids_on)

    dimmer_ps = {ch[0] for ch in iter_dimmer_light_channels(device)}
    out: list[str] = []
    for ident in candidates:
        if ident not in ids_on or not is_wall_power_switch_property(ident):
            continue
        if ident in dimmer_ps:
            continue
        if pk == "a1fVBnQNQZd" and ident == "PowerSwitch_1":
            continue
        out.append(ident)
    return sorted(set(out))


def iter_binary_switch_identifiers(device: dict[str, Any]) -> list[str]:
    """Binary toggles as HA switches. SocketSwitch* only on Socket category; PowerSwitch* on Socket as switches; wall categories use lights."""
    pk = device.get("productKey") or ""
    pl = device.get("propertyList") or []
    ids_on = _identifiers_on_device(pl)
    cat = device.get("categoryKey") or ""
    use_filter = use_product_schema_filter(pk, pl)
    allowed = get_product_control_properties(pk, pl)
    if use_filter and allowed is not None:
        candidates = [i for i in allowed if i in ids_on]
    else:
        candidates = list(ids_on)

    dimmer_channels = {ch[0] for ch in iter_dimmer_light_channels(device)}

    out: list[str] = []
    for ident in candidates:
        if ident not in ids_on:
            continue
        if ident.startswith("SocketSwitch_") and cat != SOCKET_CATEGORY:
            continue
        if is_wall_power_switch_property(ident):
            if cat in WALL_SWITCH_LIGHT_CATEGORIES:
                continue
            if cat != SOCKET_CATEGORY:
                continue
        if not is_binary_control_property(ident) and not is_binary_value_toggle(ident):
            continue
        if is_curtain_operation(ident):
            continue
        if ident == "on" and "bri" in ids_on:
            continue
        if ident in dimmer_channels:
            continue
        if pk in SMART_LIGHT_PRODUCT_KEYS and ident == "powerstate":
            continue
        if pk == "a1R8f46KuB1" and ident == "ScreenMode":
            continue
        out.append(ident)
    return sorted(set(out))


def iter_numeric_entities(device: dict[str, Any]) -> list[str]:
    pk = device.get("productKey") or ""
    pl = device.get("propertyList") or []
    ids_on = _identifiers_on_device(pl)
    use_filter = use_product_schema_filter(pk, pl)
    allowed = get_product_control_properties(pk, pl)
    if use_filter and allowed is not None:
        candidates = [i for i in allowed if i in ids_on]
    else:
        candidates = list(ids_on)

    skip_climate: set[str] = set()
    if pk == "a1fVBnQNQZd":
        skip_climate = {"AnalogValue2", "AnalogValue3"}
    if pk == "a1R8f46KuB1":
        skip_climate = {
            "TargetTemperature",
            "CurrentTemperature",
            "TemperatureCalibrate",
            "ScreenMode",
        }

    out = []
    for ident in candidates:
        if ident not in ids_on:
            continue
        if not is_numeric_control_property(ident):
            continue
        if ident in skip_climate:
            continue
        out.append(ident)
    return sorted(set(out))


def iter_readonly_sensor_properties(device: dict[str, Any]) -> list[str]:
    """Read-only status properties as sensors (not gated on product schema)."""
    pl = device.get("propertyList") or []
    pk = device.get("productKey") or ""
    ids_on = _identifiers_on_device(pl)
    skip: set[str] = set()

    if pk == "a1fVBnQNQZd":
        skip.update({"AnalogValue2", "AnalogValue3"})
    if pk == "a1R8f46KuB1":
        skip.update({"TargetTemperature", "CurrentTemperature", "ScreenMode"})

    out = []
    for ident in ids_on:
        if ident in skip:
            continue
        if device.get("categoryKey") == "Lock" and ident == "Status":
            continue
        if is_numeric_control_property(ident):
            continue
        if is_readonly_display_property(ident):
            out.append(ident)
    return sorted(set(out))


def should_create_lock(device: dict[str, Any]) -> bool:
    """Lock devices with a Status property (mock TTL / SJ locks)."""
    if device.get("categoryKey") != "Lock":
        return False
    return "Status" in _identifiers_on_device(device.get("propertyList") or [])


def is_trv_climate(device: dict[str, Any]) -> bool:
    return device.get("productKey") == "a1fVBnQNQZd"


def is_ec_thermostat_climate(device: dict[str, Any]) -> bool:
    return device.get("productKey") == "a1R8f46KuB1"


def has_curtain_position(device: dict[str, Any]) -> bool:
    return "CurtainPosition" in _identifiers_on_device(device.get("propertyList") or [])


def has_curtain_operation_only(device: dict[str, Any]) -> bool:
    """Curtain open/close/stop via CurtainOperation without position feedback."""
    ids_on = _identifiers_on_device(device.get("propertyList") or [])
    return "CurtainOperation" in ids_on and "CurtainPosition" not in ids_on


def has_curtain_cover(device: dict[str, Any]) -> bool:
    return has_curtain_position(device) or has_curtain_operation_only(device)


def smart_light_brightness_property(device: dict[str, Any]) -> str | None:
    ids_on = _identifiers_on_device(device.get("propertyList") or [])
    for key in ("brightness", "bri", "Brightness"):
        if key in ids_on:
            return key
    return None


def smart_light_color_temp_property(device: dict[str, Any]) -> str | None:
    ids_on = _identifiers_on_device(device.get("propertyList") or [])
    for key in ("colorTemperature", "ColorTemperature"):
        if key in ids_on:
            return key
    return None


def smart_light_has_hsv(device: dict[str, Any]) -> bool:
    return "HSVColor" in _identifiers_on_device(device.get("propertyList") or [])


def format_readonly_value(raw: Any) -> str:
    """Match JS formatReadonlyValue for sensor state."""
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False)
    return str(raw)
