"""EC thermostat (a1R8f46KuB1) temperature wire-format helpers."""
from __future__ import annotations

from typing import Any

EC_THERMOSTAT_PRODUCT_KEY = "a1R8f46KuB1"


def is_ec_thermostat(product_key: str | None) -> bool:
    return product_key == EC_THERMOSTAT_PRODUCT_KEY


def decode_ec_thermostat_temperature(property_id: str, raw: Any) -> float | None:
    """Decode Livolo wire values to Celsius for display."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if property_id == "CurrentTemperature":
        return value / 10.0
    if property_id == "TargetTemperature":
        fahrenheit = value / 10.0
        return (fahrenheit - 32.0) / 1.8
    return value


def encode_ec_thermostat_target_temperature(celsius: float) -> int:
    """Encode a Celsius setpoint to the Livolo wire format (Fahrenheit × 10)."""
    fahrenheit = celsius * 1.8 + 32.0
    return int(round(fahrenheit * 10.0))
