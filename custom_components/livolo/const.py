"""Constants for the Livolo integration."""
from __future__ import annotations

DOMAIN = "livolo"

# Options keys
CONF_HAS_ENTITY_NAME = "has_entity_name"

# Config entry data
CONF_MOCK_MODE = "mock_mode"

# Fired when any MQTT payload is received from the Livolo broker (see mqtt_client).
EVENT_MQTT_MESSAGE = f"{DOMAIN}_mqtt_message"

# App credentials
APP_KEY = ""
APP_SECRET = ""

# Region mapping
REGION_MAP = {
    "cn-shanghai": "https://iot.livolo.com",
    "ap-southeast-1": "https://apiot.livolo.com",
    "eu-central-1": "https://euiot.livolo.com",
    "us-east-1": "https://usiot.livolo.com",
}

# Default MQTT endpoints by region
MQTT_ENDPOINTS = {
    "cn-shanghai": "public.itls.cn-shanghai.aliyuncs.com:1883",
    "ap-southeast-1": "public.itls.ap-southeast-1.aliyuncs.com:1883",
    "eu-central-1": "public.itls.eu-central-1.aliyuncs.com:1883",
    "us-east-1": "public.itls.us-east-1.aliyuncs.com:1883",
}

# Token expiry buffer (refresh 5 min before expiry)
TOKEN_EXPIRY_BUFFER_MS = 5 * 60 * 1000

# IOT token TTL (20 hours default)
IOT_TOKEN_TTL_SEC = 72000
