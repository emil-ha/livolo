"""MQTT client for Livolo real-time updates."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Callable

import paho.mqtt.client as mqtt

from .const import MQTT_ENDPOINTS

_LOGGER = logging.getLogger(__name__)


class LivoloMqttClient:
    """MQTT client for Livolo."""

    def __init__(
        self,
        session_data: dict[str, Any],
        update_callback: Callable[[dict[str, Any]], None],
        hass: Any = None,
    ) -> None:
        """Initialize MQTT client."""
        self._session_data = session_data
        self._update_callback = update_callback
        self._hass = hass
        self._client: mqtt.Client | None = None
        self._connected = False
        self._devices_cache: dict[str, dict[str, Any]] = {}

    def update_session_data(self, session_data: dict[str, Any]) -> None:
        """Update session data (e.g., after token refresh).

        We intentionally do NOT force a rebind here. The livolo-rest-api binds on every
        MQTT (re)connect, so the important part is that the cached token is current
        when (re)connecting happens.
        """
        self._session_data = session_data

    def _generate_mqtt_password(self, product_key: str, device_name: str, device_secret: str) -> str:
        """Generate MQTT password."""
        password_map = {
            "productKey": product_key,
            "deviceName": device_name,
            "clientId": f"{device_name}&{product_key}",
        }
        sorted_keys = sorted(password_map.keys())
        canonical_string = "".join(f"{key}{password_map[key]}" for key in sorted_keys)
        password = hmac.new(
            device_secret.encode(), canonical_string.encode(), hashlib.sha1
        ).hexdigest().upper()
        return password

    def _resolve_mqtt_host(self) -> tuple[str, int]:
        """Resolve MQTT host and port."""
        gw = self._session_data.get("gatewayCredentials", {})
        region = gw.get("region", "eu-central-1")

        if self._session_data.get("mqttEndpoint"):
            endpoint = self._session_data["mqttEndpoint"]
            if "://" in endpoint:
                endpoint = endpoint.split("://")[-1]
            if ":" in endpoint:
                host, port_str = endpoint.rsplit(":", 1)
                return host, int(port_str)
            return endpoint, 1883

        default_endpoint = MQTT_ENDPOINTS.get(region, MQTT_ENDPOINTS["eu-central-1"])
        if ":" in default_endpoint:
            host, port_str = default_endpoint.rsplit(":", 1)
            return host, int(port_str)
        return default_endpoint, 1883

    async def connect(self) -> None:
        """Connect to MQTT broker."""
        import asyncio
        
        gw = self._session_data.get("gatewayCredentials", {})
        product_key = gw.get("productKey")
        device_name = gw.get("deviceName")
        device_secret = gw.get("deviceSecret")

        if not all([product_key, device_name, device_secret]):
            _LOGGER.warning("Missing gateway credentials for MQTT")
            return

        mqtt_username = f"{device_name}&{product_key}"
        mqtt_client_id = f"{device_name}&{product_key}|securemode=2,_v=0.8.0,lan=Android,os=11,signmethod=hmacsha1,ext=1|"
        mqtt_password = self._generate_mqtt_password(product_key, device_name, device_secret)

        host, port = self._resolve_mqtt_host()

        # Run MQTT connection in executor since paho-mqtt is synchronous
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._connect_sync, host, port, mqtt_username, mqtt_password, mqtt_client_id, product_key, device_name)

    def _connect_sync(self, host: str, port: int, mqtt_username: str, mqtt_password: str, mqtt_client_id: str, product_key: str, device_name: str) -> None:
        """Synchronous MQTT connection."""
        self._client = mqtt.Client(client_id=mqtt_client_id, protocol=mqtt.MQTTv311)
        self._client.username_pw_set(mqtt_username, mqtt_password)
        # Auto-reconnect behavior (similar to mqtt.js reconnectPeriod)
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

        def on_connect(client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
            if rc == 0:
                _LOGGER.info("MQTT connected")
                self._connected = True

                # Subscribe to downstream topics
                bind_reply_topic = f"/sys/{product_key}/{device_name}/app/down/account/bind_reply"
                downstream_topic = f"/sys/{product_key}/{device_name}/app/down/thing/properties"
                app_down_topic = f"/sys/{product_key}/{device_name}/app/down/#"

                client.subscribe(bind_reply_topic, qos=0)
                client.subscribe(downstream_topic, qos=1)
                client.subscribe(app_down_topic, qos=1)

                # Bind account
                if self._session_data.get("iotToken"):
                    bind_topic = f"/sys/{product_key}/{device_name}/app/up/account/bind"
                    bind_payload = json.dumps({
                        "request": {"clientId": mqtt_username},
                        "system": {"time": str(int(time.time() * 1000)), "version": "1.0"},
                        "id": "1",
                        "params": {"iotToken": self._session_data["iotToken"]},
                    })
                    client.publish(bind_topic, bind_payload, qos=0)
            else:
                _LOGGER.error("MQTT connection failed: %s", rc)

        def on_message(client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
            try:
                data = json.loads(msg.payload.decode())
                topic = msg.topic

                if "/app/down/account/bind_reply" in topic:
                    _LOGGER.debug("Account binding successful")
                elif "/app/down/thing/properties" in topic:
                    # Handle property updates
                    # MQTT message can have params.items or items directly
                    params = data.get("params") or data
                    items = params.get("items") or {}
                    iot_id = params.get("iotId") or params.get("deviceName") or data.get("iotId") or data.get("deviceName")
                    
                    if iot_id and items:
                        _LOGGER.debug("MQTT property update for %s: %s", iot_id, items)
                        
                        # Build device update structure
                        # Extract property values (can be object with 'value' or direct value)
                        property_list = []
                        for prop_id, prop_data in items.items():
                            # Skip ResendCount
                            if prop_id == "ResendCount" or prop_id == "resendCount":
                                continue
                            
                            # Extract value - can be object with 'value' key or direct value
                            if isinstance(prop_data, dict):
                                prop_value = prop_data.get("value", prop_data)
                            else:
                                prop_value = prop_data
                            
                            property_list.append({
                                "identifier": prop_id,
                                "value": prop_value,
                                "dataType": "BOOL",
                            })
                        
                        if property_list:
                            # Create device update structure
                            device_update = {
                                "iotId": iot_id,
                                "elementId": iot_id,
                                "propertyList": property_list,
                            }
                            
                            # Trigger coordinator update
                            self._update_callback({"devices": [device_update]})
            except Exception as e:
                _LOGGER.error("Error processing MQTT message: %s", e, exc_info=True)

        def on_disconnect(client: mqtt.Client, userdata: Any, rc: int) -> None:
            self._connected = False
            if rc != 0:
                # Unexpected disconnect. With connect_async + loop_start paho will reconnect automatically.
                _LOGGER.warning("MQTT disconnected unexpectedly (rc=%s). Will attempt to reconnect.", rc)
            else:
                _LOGGER.info("MQTT disconnected")

        self._client.on_connect = on_connect
        self._client.on_message = on_message
        self._client.on_disconnect = on_disconnect

        try:
            # connect_async + loop_start enables automatic reconnect handling in paho
            self._client.connect_async(host, port, 60)
            self._client.loop_start()
        except Exception as e:
            _LOGGER.error("Failed to connect to MQTT: %s", e)
            self._client = None

    async def disconnect(self) -> None:
        """Disconnect from MQTT broker."""
        if self._client:
            import asyncio
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._disconnect_sync)
            
    def _disconnect_sync(self) -> None:
        """Synchronous MQTT disconnection."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None
            self._connected = False
