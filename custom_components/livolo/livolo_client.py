"""Livolo API client - ported from livolo-rest-api."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from typing import Any

import aiohttp

from .const import (
    APP_KEY as DEFAULT_APP_KEY,
    APP_SECRET as DEFAULT_APP_SECRET,
    IOT_TOKEN_TTL_SEC,
    MQTT_ENDPOINTS,
    REGION_MAP,
    TOKEN_EXPIRY_BUFFER_MS,
)
from .property_identifiers import ALL_PROPERTY_IDENTIFIERS

_LOGGER = logging.getLogger(__name__)

LIVOLO_HEADERS = {
    "language": "en",
    "apiVer": "1.0.0",
    "Content-Type": "application/json",
}


class LivoloClient:
    """Client for Livolo/Alibaba IoT API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        email: str,
        password: str,
        country_code: str = "DE",
        app_key: str | None = None,
        app_secret: str | None = None,
    ):
        """Initialize the client."""
        self._session = session
        self._email = email
        self._password = password
        self._country_code = country_code
        self._app_key = app_key or DEFAULT_APP_KEY
        self._app_secret = app_secret or DEFAULT_APP_SECRET
        self._session_data: dict[str, Any] | None = None

    def _log_request(self, method: str, url: str, headers: dict[str, str] | None = None, body: Any = None) -> None:
        """Log HTTP request details."""
        log_headers = headers.copy() if headers else {}
        # Redact sensitive headers
        if "Authorization" in log_headers:
            log_headers["Authorization"] = "***REDACTED***"
        if "x-ca-signature" in log_headers:
            log_headers["x-ca-signature"] = "***REDACTED***"
        
        log_body = body
        if isinstance(body, str) and len(body) > 500:
            log_body = body[:500] + "... (truncated)"
        elif isinstance(body, dict) and "password" in str(body).lower():
            log_body = "***REDACTED (contains password)***"
        
        _LOGGER.debug("HTTP Request: %s %s", method, url)
        _LOGGER.debug("Request Headers: %s", log_headers)
        _LOGGER.debug("Request Body: %s", log_body)

    async def _log_response(self, resp: aiohttp.ClientResponse, url: str) -> str:
        """Log HTTP response details and return response text."""
        try:
            text = await resp.text()
        except Exception as e:
            _LOGGER.warning("Failed to read response text: %s", e)
            return ""
        
        _LOGGER.debug("HTTP Response: %s %s - Status: %d", resp.method, url, resp.status)
        _LOGGER.debug("Response Headers: %s", dict(resp.headers))
        
        # Log response body (truncate if too long)
        log_text = text
        if len(text) > 1000:
            log_text = text[:1000] + "... (truncated)"
        _LOGGER.debug("Response Body: %s", log_text)
        
        return text

    def _generate_client_id(self, session_id: str) -> str:
        """Generate deterministic client ID from session ID.
        
        Matches JavaScript: hash.substring(0, 8).replace(/[+/=]/g, '')
        """
        hash_obj = hashlib.sha256(session_id.encode())
        hash_b64 = base64.b64encode(hash_obj.digest()).decode('ascii')
        return hash_b64[:8].replace('+', '').replace('/', '').replace('=', '')

    def _generate_device_sn(self, session_id: str) -> str:
        """Generate deterministic device SN from session ID.
        
        Matches JavaScript: hash.substring(0, 32).replace(/[+/=]/g, '')
        """
        hash_obj = hashlib.sha256(session_id.encode())
        hash_b64 = base64.b64encode(hash_obj.digest()).decode('ascii')
        return hash_b64[:32].replace('+', '').replace('/', '').replace('=', '')

    def _sign_request(
        self,
        method: str,
        path_and_query: str,
        body: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, str]:
        """Sign Alibaba API Gateway request."""
        import base64

        def content_md5(data: str | None) -> str:
            if not data:
                return ""
            return base64.b64encode(hashlib.md5(data.encode()).digest()).decode()

        ts = str(int(time.time() * 1000))
        nonce = str(uuid.uuid4())
        date = time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime())

        headers: dict[str, str] = {
            "accept": "application/json; charset=utf-8",
            "date": date,
            "x-ca-key": self._app_key,
            "x-ca-nonce": nonce,
            "x-ca-timestamp": ts,
            "x-ca-signature-method": "HmacSHA1",
            "user-agent": "ALIYUN-ANDROID-DEMO",
            "ca_version": "1",
        }
        if extra_headers:
            headers.update(extra_headers)

        body_for_sign = body if body else None
        if body_for_sign:
            headers["content-md5"] = content_md5(body_for_sign)
            headers.setdefault(
                "content-type", "application/octet-stream; charset=utf-8"
            )
        else:
            headers.setdefault(
                "content-type", "application/octet-stream; charset=utf-8"
            )

        # Build string to sign
        headers_to_sign = {
            k: v for k, v in headers.items() if k.startswith("x-ca-") and k != "x-ca-signature" and k != "x-ca-signature-headers"
        }
        sorted_header_keys = sorted(headers_to_sign.keys())
        canonical_headers = "\n".join(
            f"{key}:{headers_to_sign[key]}" for key in sorted_header_keys
        )
        signed_header_keys = ",".join(sorted_header_keys)

        md5_value = content_md5(body_for_sign) if body_for_sign else ""
        string_to_sign = (
            f"{method}\n"
            f"{headers.get('accept', '')}\n"
            f"{md5_value}\n"
            f"{headers.get('content-type', '')}\n"
            f"{date}\n"
            f"{canonical_headers}\n"
            f"{path_and_query}"
        )

        signature = base64.b64encode(
            hmac.new(self._app_secret.encode(), string_to_sign.encode(), hashlib.sha1).digest()
        ).decode()

        headers["x-ca-signature-headers"] = signed_header_keys
        headers["x-ca-signature"] = signature

        return headers

    def _sign_triple_values_request(self, client_id: str, device_sn: str) -> tuple[int, str]:
        """Generate sign for triple values request."""
        timestamp = int(time.time() * 1000)
        to_sign_str = f"appKey{self._app_key}clientId{client_id}deviceSn{device_sn}timestamp{timestamp}"
        sign = hmac.new(
            self._app_secret.encode(), to_sign_str.encode(), hashlib.sha1
        ).hexdigest()
        return timestamp, sign

    async def _get_livolo_region(self) -> str:
        """Get Livolo region for email."""
        url = "https://iot.livolo.com/user/region"
        request_body = {"email": self._email}
        self._log_request("POST", url, LIVOLO_HEADERS, request_body)
        
        async with self._session.post(url, json=request_body, headers=LIVOLO_HEADERS) as resp:
            # Get raw text first to handle edge cases
            text = await self._log_response(resp, url)
            if not text:
                return "eu-central-1"
            
            # Parse JSON
            try:
                data = json.loads(text)
            except Exception as e:
                _LOGGER.warning("Failed to parse JSON response from region endpoint: %s, text: %s", e, text[:200])
                return "eu-central-1"
            
            # Ensure data is a dict
            if not isinstance(data, dict):
                _LOGGER.warning("Unexpected response format from region endpoint: %s, value: %s", type(data), str(data)[:200])
                return "eu-central-1"
            
            if data.get("result_code") != "000" and data.get("resultCode") != "000":
                raise Exception(data.get("result_msg") or data.get("resultMessage") or "Region lookup failed")
            
            # Handle different response formats
            data_value = data.get("data")
            if isinstance(data_value, dict):
                region = data_value.get("aliEndPoint") or data_value.get("region")
            elif isinstance(data_value, str):
                region = data_value
            else:
                region = None
            
            return region if isinstance(region, str) and region else "eu-central-1"

    async def _livolo_sign_in(self, region_url: str) -> dict[str, Any]:
        """Sign in to Livolo."""
        url = f"{region_url}/sns/sign_in"
        request_body = {"email": self._email, "password": "***REDACTED***"}
        self._log_request("POST", url, LIVOLO_HEADERS, request_body)
        
        async with self._session.post(
            url, json={"email": self._email, "password": self._password}, headers=LIVOLO_HEADERS
        ) as resp:
            text = await self._log_response(resp, url)
            try:
                data = json.loads(text) if text else {}
            except Exception as e:
                _LOGGER.error("Failed to parse JSON response from sign_in: %s", e)
                raise
            
            # Handle case where response might be a string
            if not isinstance(data, dict):
                raise Exception(f"Unexpected response format from sign_in endpoint: {type(data)}")
            
            if data.get("result_code") != "000" and data.get("resultCode") != "000":
                raise Exception(data.get("result_msg") or data.get("resultMessage") or "Sign in failed")
            
            # Handle different response formats
            data_value = data.get("data")
            if isinstance(data_value, dict):
                data_dict = data_value
            else:
                data_dict = {}
            
            return {
                "authCode": data_dict.get("code"),
                "identityId": data_dict.get("identityId"),
                "openId": data_dict.get("openId"),
                "aliEndPoint": data_dict.get("aliEndPoint"),
            }

    async def _alibaba_region_get(self, auth_code: str) -> dict[str, Any]:
        """Get Alibaba region info."""
        host = "https://cn-shanghai.api-iot.aliyuncs.com"
        request_id = str(uuid.uuid4())
        path_and_query = f"/living/account/region/get?x-ca-request-id={request_id}"
        body = json.dumps({
            "a": request_id,
            "b": "1.0",
            "c": {"apiVer": "1.0.2", "language": "en-US"},
            "d": {"authCode": auth_code, "type": "THIRD_AUTHCODE", "countryCode": self._country_code},
            "id": request_id,
            "params": {"$ref": "$.d"},
            "request": {"$ref": "$.c"},
            "version": "1.0",
        })
        headers = self._sign_request("POST", path_and_query, body, {"host": "cn-shanghai.api-iot.aliyuncs.com"})
        headers["host"] = "cn-shanghai.api-iot.aliyuncs.com"
        full_url = f"{host}{path_and_query}"
        self._log_request("POST", full_url, headers, body)
        
        async with self._session.post(full_url, data=body, headers=headers) as resp:
            text = await self._log_response(resp, full_url)
            try:
                data = json.loads(text) if text else {}
            except Exception as e:
                _LOGGER.error("Failed to parse JSON response from region/get: %s", e)
                raise
            
            # Handle case where response might be a string
            if not isinstance(data, dict):
                raise Exception(f"Unexpected response format from region/get endpoint: {type(data)}")
            
            if data.get("code") != 200:
                raise Exception(data.get("message") or f"region/get failed: {json.dumps(data)}")
            
            # Handle different response formats
            raw = data.get("data")
            if not isinstance(raw, dict):
                raw = {}
            
            return {
                "apiGatewayEndpoint": raw.get("apiGatewayEndpoint", "").replace("https://", "").replace("http://", "") or raw.get("regionId"),
                "oaApiGatewayEndpoint": raw.get("oaApiGatewayEndpoint", "").replace("https://", "").replace("http://", ""),
                "regionId": raw.get("regionId"),
                "mqttEndpoint": raw.get("mqttEndpoint"),
                "pushChannelEndpoint": raw.get("pushChannelEndpoint", "").replace("https://", "").replace("http://", "") if raw.get("pushChannelEndpoint") else None,
            }

    async def _alibaba_login_by_oauth(self, oa_host: str, auth_code: str) -> dict[str, str]:
        """Login to Alibaba by OAuth."""
        path = "/api/prd/loginbyoauth.json"
        device_id = str(uuid.uuid4())
        login_payload = {
            "country": self._country_code,
            "authCode": auth_code,
            "oauthPlateform": 23,
            "oauthAppKey": self._app_key,
            "riskControlInfo": {
                "appVersion": "230",
                "USE_OA_PWD_ENCRYPT": "true",
                "utdid": "ffffffffffffffffffffffff",
                "netType": "wifi",
                "umidToken": "",
                "locale": "en_US",
                "appVersionName": "5.4.22",
                "deviceId": device_id,
                "routerMac": "02:00:00:00:00:00",
                "platformVersion": "30",
                "appAuthToken": "",
                "appID": "com.livolo.livoloapp",
                "signType": "RSA",
                "sdkVersion": "3.4.2",
                "model": "sdk_gphone_x86_64",
                "USE_H5_NC": "true",
                "platformName": "android",
                "brand": "google",
                "yunOSId": "",
            },
        }
        from urllib.parse import quote
        raw_json = json.dumps(login_payload)
        form_body = f"loginByOauthRequest={quote(raw_json)}"
        path_and_query = f"{path}?loginByOauthRequest={raw_json}"
        host_clean = oa_host.replace("https://", "").replace("http://", "")
        headers = self._sign_request(
            "POST",
            path_and_query,
            form_body,
            {
                "host": host_clean,
                "Content-Type": "application/octet-stream; charset=utf-8",
                "vid": f"V-{uuid.uuid4()}",
            },
        )
        headers["host"] = host_clean
        headers["Content-Type"] = "application/x-www-form-urlencoded; charset=utf-8"
        headers.setdefault("vid", f"V-{uuid.uuid4()}")
        full_url = f"https://{host_clean}{path}"
        self._log_request("POST", full_url, headers, form_body)
        
        async with self._session.post(full_url, data=form_body, headers=headers) as resp:
            text = await self._log_response(resp, full_url)
            try:
                data = json.loads(text) if text else {}
            except Exception as e:
                _LOGGER.error("Failed to parse JSON response from loginbyoauth: %s", e)
                raise
            
            # Handle case where response might be a string
            if not isinstance(data, dict):
                raise Exception(f"Unexpected response format from loginbyoauth endpoint: {type(data)}")
            
            # Handle different response formats
            data_value = data.get("data")
            if isinstance(data_value, dict):
                data_dict = data_value
            else:
                data_dict = {}
            
            ok = (
                data.get("success") == "true"
                or data.get("success") is True
                or data_dict.get("successful") == "true"
                or data_dict.get("code") == 1
            )
            if not ok:
                raise Exception(data_dict.get("message") or data.get("message") or f"loginbyoauth failed: {json.dumps(data)}")
            
            # Handle nested data structure
            login_result_data = data_dict.get("data") if isinstance(data_dict.get("data"), dict) else data_dict
            login_result = login_result_data.get("loginSuccessResult") or login_result_data
            
            if not isinstance(login_result, dict):
                raise Exception(f"Invalid login result format: {json.dumps(data)}")
            
            sid = login_result.get("sid")
            open_account = login_result.get("openAccount", {}) if isinstance(login_result.get("openAccount"), dict) else {}
            open_id = open_account.get("openId")
            if not sid:
                raise Exception("No sid in loginbyoauth response")
            return {"sid": sid, "openId": open_id}

    async def _create_session_by_auth_code(self, api_host: str, sid: str) -> dict[str, Any]:
        """Create session by auth code."""
        path = "/account/createSessionByAuthCode"
        request_id = str(uuid.uuid4())
        body = json.dumps({
            "a": request_id,
            "b": "1.0",
            "c": {"apiVer": "1.0.4", "language": "en-US"},
            "d": {"request": {"authCode": sid, "accountType": "OA_SESSION", "appKey": self._app_key}},
            "id": request_id,
            "params": {"$ref": "$.d"},
            "request": {"$ref": "$.c"},
            "version": "1.0",
        })
        host_clean = api_host.replace("https://", "").replace("http://", "")
        headers = self._sign_request("POST", path, body, {"host": host_clean})
        headers["host"] = host_clean
        base = api_host if api_host.startswith("http") else f"https://{api_host}"
        full_url = f"{base}{path}"
        self._log_request("POST", full_url, headers, body)
        
        async with self._session.post(full_url, data=body, headers=headers) as resp:
            text = await self._log_response(resp, full_url)
            try:
                data = json.loads(text) if text else {}
            except Exception as e:
                _LOGGER.error("Failed to parse JSON response from createSession: %s", e)
                raise
            
            # Handle case where response might be a string
            if not isinstance(data, dict):
                raise Exception(f"Unexpected response format from createSession endpoint: {type(data)}")
            
            if data.get("code") != 200:
                raise Exception(data.get("message") or f"createSession failed: {json.dumps(data)}")
            
            # Handle different response formats
            data_value = data.get("data")
            if isinstance(data_value, dict):
                data_dict = data_value
            else:
                data_dict = {}
            
            return {
                "iotToken": data_dict.get("iotToken"),
                "identityId": data_dict.get("identityId"),
                "refreshToken": data_dict.get("refreshToken"),
                "iotTokenExpire": data_dict.get("iotTokenExpire"),
            }

    async def _livolo_set_identity_id(self, region_url: str, open_id: str, identity_id: str) -> None:
        """Set identity ID in Livolo."""
        url = f"{region_url}/sns/setidentityid"
        request_body = {"openid": open_id, "identityId": identity_id}
        self._log_request("POST", url, LIVOLO_HEADERS, request_body)
        
        async with self._session.post(url, json=request_body, headers=LIVOLO_HEADERS) as resp:
            await self._log_response(resp, url)

    async def _query_home(self, api_host: str, iot_token: str) -> dict[str, Any]:
        """Query home."""
        path = "/living/home/query"
        body = json.dumps({
            "id": str(uuid.uuid4()),
            "version": "1.0",
            "request": {"apiVer": "1.1.0", "iotToken": iot_token},
            "params": {"pageNo": 1, "pageSize": 20},
        })
        host_clean = api_host.replace("https://", "").replace("http://", "")
        headers = self._sign_request("POST", path, body, {"host": host_clean})
        headers["host"] = host_clean
        base = api_host if api_host.startswith("http") else f"https://{api_host}"
        full_url = f"{base}{path}"
        self._log_request("POST", full_url, headers, body)
        
        async with self._session.post(full_url, data=body, headers=headers) as resp:
            text = await self._log_response(resp, full_url)
            try:
                data = json.loads(text) if text else {}
            except Exception as e:
                _LOGGER.error("Failed to parse JSON response from home/query: %s", e)
                raise
            
            # Handle case where response might be a string
            if not isinstance(data, dict):
                raise Exception(f"Unexpected response format from home/query endpoint: {type(data)}")
            
            if data.get("code") != 200:
                raise Exception(data.get("message") or f"home/query failed: {json.dumps(data)}")
            
            # Handle different response formats
            data_value = data.get("data")
            if isinstance(data_value, dict):
                list_data = data_value.get("data") or []
            elif isinstance(data_value, list):
                list_data = data_value
            else:
                list_data = []
            
            if not isinstance(list_data, list):
                list_data = []
            
            home = list_data[0] if list_data else {}
            return {
                "homeId": home.get("homeId") if isinstance(home, dict) else None,
                "homes": list_data if isinstance(list_data, list) else []
            }

    async def _get_triple_values(self, api_host: str, client_id: str, device_sn: str) -> dict[str, str]:
        """Get triple values (productKey, deviceName, deviceSecret).
        
        Parameter order matches JavaScript function signature: getTripleValues(apiHost, clientId, deviceSn)
        """
        timestamp, sign = self._sign_triple_values_request(client_id, device_sn)
        path = "/app/aepauth/handle"
        request_id = str(uuid.uuid4())
        path_and_query = f"{path}?x-ca-request-id={request_id}"
        body = json.dumps({
            "a": request_id,
            "b": "1.0",
            "c": {"apiVer": "1.0.0", "language": "en-US"},
            "d": {
                "authInfo": {
                    "clientId": client_id,
                    "sign": sign,
                    "deviceSn": device_sn,
                    "timestamp": str(timestamp),
                },
            },
            "id": request_id,
            "params": {"$ref": "$.d"},
            "request": {"$ref": "$.c"},
            "version": "1.0",
        })
        host_clean = api_host.replace("https://", "").replace("http://", "")
        headers = self._sign_request("POST", path_and_query, body, {"host": host_clean})
        headers["host"] = host_clean
        base = api_host if api_host.startswith("http") else f"https://{api_host}"
        full_url = f"{base}{path_and_query}"
        self._log_request("POST", full_url, headers, body)
        
        async with self._session.post(full_url, data=body, headers=headers) as resp:
            text = await self._log_response(resp, full_url)
            try:
                data = json.loads(text) if text else {}
            except Exception as e:
                _LOGGER.error("Failed to parse JSON response from getTripleValues: %s", e)
                raise
            
            # Handle case where response might be a string
            if not isinstance(data, dict):
                raise Exception(f"Unexpected response format from getTripleValues endpoint: {type(data)}")
            
            if data.get("code") != 200:
                raise Exception(data.get("message") or f"getTripleValues failed: {json.dumps(data)}")
            
            # Handle different response formats
            result = data.get("data")
            if not isinstance(result, dict):
                raise Exception(f"Invalid triple values response format: {json.dumps(data)}")
            
            if not result.get("deviceSecret") or not result.get("productKey") or not result.get("deviceName"):
                raise Exception(f"Missing triple values in response: {json.dumps(result)}")
            return {
                "deviceSecret": result["deviceSecret"],
                "productKey": result["productKey"],
                "deviceName": result["deviceName"],
            }

    async def login(self) -> dict[str, Any]:
        """Run full login flow."""
        # Generate session ID from email/password
        base_str = f"homeassistant-{self._email}-{self._country_code}-{self._password}"
        session_id = hashlib.md5(base_str.encode()).hexdigest()

        region_key = await self._get_livolo_region()
        region_url = REGION_MAP.get(region_key, "https://euiot.livolo.com")

        sign_in_result = await self._livolo_sign_in(region_url)
        auth_code = sign_in_result["authCode"]
        identity_id = sign_in_result["identityId"]
        open_id = sign_in_result["openId"]

        api_gateway = f"{region_key}.api-iot.aliyuncs.com"
        oa_gateway = f"living-account.{region_key}.aliyuncs.com"
        mqtt_endpoint = None
        push_channel_endpoint = None

        try:
            region_data = await self._alibaba_region_get(auth_code)
            if region_data.get("apiGatewayEndpoint"):
                api_gateway = region_data["apiGatewayEndpoint"]
            if region_data.get("oaApiGatewayEndpoint"):
                oa_gateway = region_data["oaApiGatewayEndpoint"]
            if region_data.get("mqttEndpoint"):
                mqtt_endpoint = region_data["mqttEndpoint"]
            if region_data.get("pushChannelEndpoint"):
                push_channel_endpoint = region_data["pushChannelEndpoint"]
        except Exception:
            pass

        oauth_result = await self._alibaba_login_by_oauth(oa_gateway, auth_code)
        sid = oauth_result["sid"]
        oa_open_id = oauth_result.get("openId")
        effective_open_id = oa_open_id or open_id

        session_result = await self._create_session_by_auth_code(api_gateway, sid)
        iot_token = session_result["iotToken"]
        session_identity_id = session_result["identityId"]
        refresh_token = session_result["refreshToken"]
        iot_token_expire = session_result.get("iotTokenExpire")

        await self._livolo_set_identity_id(region_url, effective_open_id, session_identity_id or identity_id)

        home_result = await self._query_home(api_gateway, iot_token)
        home_id = home_result.get("homeId")

        ttl_sec = iot_token_expire or IOT_TOKEN_TTL_SEC
        iot_token_expires_at = int(time.time() * 1000) + (ttl_sec * 1000)

        session_payload = {
            "sessionId": session_id,
            "iotToken": iot_token,
            "identityId": session_identity_id or identity_id,
            "refreshToken": refresh_token,
            "apiGateway": api_gateway,
            "regionUrl": region_url,
            "regionKey": region_key,
            "mqttEndpoint": mqtt_endpoint,
            "pushChannelEndpoint": push_channel_endpoint,
            "homeId": home_id,
            "homes": home_result.get("homes", []),
            "iotTokenExpiresAt": iot_token_expires_at,
        }

        # Get gateway credentials
        device_sn = self._generate_device_sn(session_id)
        client_id = self._generate_client_id(session_id)

        # try:
            # Matches JavaScript: getTripleValues(apiGateway, clientId, deviceSn)
        triple_result = await self._get_triple_values(api_gateway, client_id, device_sn)
        _LOGGER.info("Triple result: %s", triple_result)
        _LOGGER.info("Session payload: %s", session_payload)
        session_payload["deviceSn"] = device_sn
        session_payload["clientId"] = client_id
        session_payload["gatewayCredentials"] = {
            "productKey": triple_result["productKey"],
            "deviceName": triple_result["deviceName"],
            "deviceSecret": triple_result["deviceSecret"],
            "region": region_key,
        }
        # except Exception as e:
        #     _LOGGER.warning("Failed to get triple values during login: %s", e)

        self._session_data = session_payload
        return session_payload

    async def _api_request(self, path: str, api_ver: str, params: dict[str, Any], retry_on_auth_error: bool = True) -> dict[str, Any]:
        """Make API request with automatic token refresh on auth errors."""
        if not self._session_data:
            raise Exception("Not logged in")
        api_host = self._session_data["apiGateway"]
        iot_token = self._session_data["iotToken"]
        body = json.dumps({
            "id": str(uuid.uuid4()),
            "version": "1.0",
            "request": {"apiVer": api_ver, "iotToken": iot_token},
            "params": params,
        })
        host_clean = api_host.replace("https://", "").replace("http://", "")
        headers = self._sign_request("POST", path, body, {"host": host_clean})
        headers["host"] = host_clean
        base = api_host if api_host.startswith("http") else f"https://{api_host}"
        full_url = f"{base}{path}"
        self._log_request("POST", full_url, headers, body)
        
        async with self._session.post(full_url, data=body, headers=headers) as resp:
            text = await self._log_response(resp, full_url)
            try:
                data = json.loads(text) if text else {}
            except Exception as e:
                _LOGGER.error("Failed to parse JSON response from API %s: %s", path, e)
                raise
            
            # Handle case where response might be a string
            if not isinstance(data, dict):
                raise Exception(f"Unexpected response format from API {path}: {type(data)}")
            
            if data.get("code") != 200:
                error_message = data.get("message") or f"API {path} failed: {json.dumps(data)}"
                # Check if this is an authentication error (token expired)
                # Common auth error codes: 401, 403, or specific error messages
                is_auth_error = (
                    resp.status in (401, 403) or
                    "token" in error_message.lower() or
                    "auth" in error_message.lower() or
                    "expired" in error_message.lower() or
                    "unauthorized" in error_message.lower()
                )
                
                # Try to refresh token and retry once if it's an auth error
                if is_auth_error and retry_on_auth_error:
                    _LOGGER.warning("Authentication error detected, attempting token refresh: %s", error_message)
                    refreshed = await self.refresh_token()
                    if refreshed:
                        _LOGGER.info("Token refreshed successfully, retrying API request")
                        # Retry the request with new token (only once)
                        return await self._api_request(path, api_ver, params, retry_on_auth_error=False)
                    else:
                        _LOGGER.warning("Token refresh failed, attempting re-login")
                        await self.login()
                        # Retry the request after re-login (only once)
                        return await self._api_request(path, api_ver, params, retry_on_auth_error=False)
                
                raise Exception(error_message)
            return data.get("data") or data

    async def get_devices(self) -> list[dict[str, Any]]:
        """Get all devices."""
        if not self._session_data:
            raise Exception("Not logged in")
        home_id = self._session_data.get("homeId")
        if not home_id:
            home_result = await self._query_home(self._session_data["apiGateway"], self._session_data["iotToken"])
            home_id = home_result.get("homeId")
            if not home_id:
                return []
        all_devices = []
        page_no = 1
        while True:
            params = {
                "homeId": home_id,
                "pageNo": page_no,
                "pageSize": 20,
                "propertyIdentifiers": ALL_PROPERTY_IDENTIFIERS,
            }
            page = await self._api_request("/living/home/element/query", "1.0.6", params)
            items = page.get("items") or page.get("data") or []
            total = page.get("total", 0)
            page_size = page.get("pageSize", 20)
            if isinstance(items, list):
                all_devices.extend(items)
            if not items or total <= page_no * page_size:
                break
            page_no += 1
            if page_no > 50:
                break
        return all_devices

    async def get_gateway_subdevices(self, gateway_iot_id: str) -> list[dict[str, Any]]:
        """Get child devices for a gateway using /subdevices/list API.
        
        Args:
            gateway_iot_id: The gateway's iotId/elementId
            
        Returns:
            List of child device dictionaries
        """
        if not self._session_data:
            raise Exception("Not logged in")
        
        all_subdevices = []
        page_no = 1
        while True:
            params = {
                "iotId": gateway_iot_id,
                "pageNo": page_no,
                "pageSize": 20,
            }
            try:
                page = await self._api_request("/subdevices/list", "1.0.6", params)
                items = page.get("items") or page.get("data") or []
                total = page.get("total", 0)
                page_size = page.get("pageSize", 20)
                if isinstance(items, list):
                    all_subdevices.extend(items)
                if not items or total <= page_no * page_size:
                    break
                page_no += 1
                if page_no > 50:
                    break
            except Exception as e:
                _LOGGER.warning("Failed to get subdevices for gateway %s: %s", gateway_iot_id, e)
                break
        return all_subdevices

    async def set_device_properties(self, iot_id: str, items: dict[str, Any]) -> dict[str, Any]:
        """Set device properties."""
        return await self._api_request("/thing/properties/set", "1.0.2", {"iotId": iot_id, "items": items})

    async def get_device_properties(self, iot_id: str) -> dict[str, Any]:
        """Get device properties."""
        return await self._api_request("/thing/properties/get", "1.0.2", {"iotId": iot_id})

    async def refresh_token(self) -> bool:
        """Refresh IoT token."""
        if not self._session_data:
            return False
        refresh_token = self._session_data.get("refreshToken")
        identity_id = self._session_data.get("identityId")
        if not refresh_token or not identity_id:
            return False
        
        try:
            api_host = self._session_data["apiGateway"]
            path = "/account/checkOrRefreshSession"
            request_id = str(uuid.uuid4())
            body = json.dumps({
                "a": request_id,
                "b": "1.0",
                "c": {"apiVer": "1.0.4", "language": "en-US"},
                "d": {"request": {"refreshToken": refresh_token, "identityId": identity_id, "appKey": self._app_key}},
                "id": request_id,
                "params": {"$ref": "$.d"},
                "request": {"$ref": "$.c"},
                "version": "1.0",
            })
            host_clean = api_host.replace("https://", "").replace("http://", "")
            headers = self._sign_request("POST", path, body, {"host": host_clean})
            headers["host"] = host_clean
            base = api_host if api_host.startswith("http") else f"https://{api_host}"
            full_url = f"{base}{path}"
            self._log_request("POST", full_url, headers, body)
            
            async with self._session.post(full_url, data=body, headers=headers) as resp:
                text = await self._log_response(resp, full_url)
                if resp.status == 404:
                    return False
                
                try:
                    data = json.loads(text) if text else {}
                except Exception as e:
                    _LOGGER.warning("Failed to parse JSON response from refresh token: %s", e)
                    return False
                
                # Handle case where response might be a string
                if not isinstance(data, dict):
                    _LOGGER.warning("Unexpected response format from refresh token endpoint: %s", type(data))
                    return False
                
                if data.get("code") != 200:
                    return False
                
                # Handle different response formats
                data_value = data.get("data")
                if isinstance(data_value, dict):
                    data_dict = data_value
                else:
                    data_dict = {}
                
                ttl_sec = data_dict.get("iotTokenExpire") or IOT_TOKEN_TTL_SEC
                self._session_data["iotToken"] = data_dict.get("iotToken")
                self._session_data["identityId"] = data_dict.get("identityId")
                self._session_data["refreshToken"] = data_dict.get("refreshToken") or refresh_token
                self._session_data["iotTokenExpiresAt"] = int(time.time() * 1000) + (ttl_sec * 1000)
                return True
        except Exception as e:
            _LOGGER.warning("Token refresh failed: %s", e)
            return False

    def get_session_data(self) -> dict[str, Any] | None:
        """Get current session data."""
        return self._session_data
