# Livolo Home Assistant Integration

A Home Assistant custom component for controlling Livolo smart switches and devices with Livolo Gateways via cloud similar to how the Android application does.

## Features

- Control Livolo switches directly from Home Assistant
- Real-time updates via MQTT
- Automatic device discovery
- Support for multiple switch channels (PowerSwitch_1, PowerSwitch_2, etc.)

## Installation

### Via HACS (Recommended)

1. Install [HACS](https://hacs.xyz/)
2. Go to HACS → Integrations
3. Click "Explore & Download Repositories"
4. Search for "Livolo"
5. Click "Download"
6. Restart Home Assistant
7. Go to Settings → Devices & Services → Add Integration
8. Search for "Livolo" and configure with your credentials

### Manual Installation

1. Copy the `livolo` folder to `custom_components` in your Home Assistant config directory
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "Livolo" and configure with your credentials

## Configuration

During setup, you'll need to provide:
- **Email**: Your Livolo account email
- **Password**: Your Livolo account password
- **Country Code**: Your country code (e.g., DE, US, CN)
- **APP Key**: Livolo APP Secret. Can be obtained from [SDKInitHelper.java](https://github.com/PengJiang520/livoloapp) or by [decompiling](https://www.javadecompilers.com/apk) the [android APK](https://apkpure.com/livolo-home/com.livolo.livoloapp) and search for **appKey**
- **APP Secret**: Livolo APP Secret. Can be obtained from [SDKInitHelper.java](https://github.com/PengJiang520/livoloapp) or by [decompiling](https://www.javadecompilers.com/apk) the [android APK](https://apkpure.com/livolo-home/com.livolo.livoloapp) and search for **appSecret**

## Usage

After installation, Livolo switches will appear as separate switch entities in Home Assistant. Each switch channel (PowerSwitch_1, PowerSwitch_2, etc.) will be a separate entity.

Entities are named: `{Device Name} {Property Name Without "PowerSwitch "}` (e.g., "Kitchen Switch 1")

### Dashboard YAML Template Generator

The integration includes a service to automatically generate Lovelace YAML templates that group your Livolo entities by device.

#### Prerequisites

- The Livolo integration must be installed and configured in Home Assistant
- The [custom-card-features](https://github.com/Nerwyn/custom-card-features) integration must be installed (used to render the generated dashboard)

#### How to Use

1. Go to **Developer Tools** → **Events**
2. In the **Listen to events** field, enter: `livolo_generate_dashboard_result`
3. Click **Start Listening**
4. In a new tab, go to **Developer Tools** → **Services**
5. Search for and select the **"Livolo: Generate Dashboard YAML"** service
6. (Optional) Specify a config entry ID to generate YAML for a specific Livolo integration instance
7. Click **Call Service**
8. The generated Lovelace YAML will appear in the event listener as a `livolo_generate_dashboard_result` event
9. Copy the YAML snippet from the event data and add it to your Lovelace dashboard configuration

The generator creates YAML groups for each device, organizing PowerSwitch channels (PowerSwitch_1, PowerSwitch_2, etc.) together. It automatically prefers light entities if available, otherwise uses switch entities.

## Requirements

- Home Assistant 2023.1 or later
- Python 3.10 or later
- paho-mqtt>=1.6.1
- aiohttp>=3.9.0
- cryptography>=41.0.0

## Troubleshooting

If devices don't appear:
1. Check your credentials are correct
2. Check the Home Assistant logs for errors
3. Ensure your Livolo account has devices configured

If switches don't update in real-time:
1. Check MQTT connection in logs
2. Ensure gateway credentials were obtained during login
3. Check firewall settings for MQTT port (1883)


## Debug events

The integration exposes two optional events for inspection and automations. You can listen under **Developer tools → Events** (event type = the name below) or use them as **triggers** in automations.

### `livolo_get_devices_result`

Fired when you call the **`livolo.get_devices`** service (see `services.yaml`). That service runs the same cloud request the integration uses to load devices (`get_devices()`), then publishes the result on the bus.

| | |
| --- | --- |
| **How to trigger** | **Developer tools → Actions** → Domain `livolo`, action `get_devices`. Optionally set `entry_id` to a single config entry; omit it to run for every Livolo integration (one event per entry). |
| **Event data** | `devices`: a **string** containing pretty-printed JSON (`indent=2`) of the device list returned by the API. Home Assistant event data must be JSON-friendly; the list is therefore sent as formatted text. |

**Example automation trigger** (fires when the event occurs; adjust `action` to match how you invoke the service):

```yaml
trigger:
  - platform: event
    event_type: livolo_get_devices_result
action:
  - service: logbook.log
    data:
      name: Livolo
      message: "Device dump received (see event data: devices)"
```

### `livolo_mqtt_message`

Fired for each incoming MQTT message on the Livolo broker **after** the payload is successfully parsed as JSON (real-time switch updates use this path). Requires a working MQTT session (gateway credentials from login).

| | |
| --- | --- |
| **When** | Automatically whenever the integration receives a JSON MQTT payload on subscribed topics. |
| **Event data** | Normally `json`: a **string** containing pretty-printed JSON of an object with `topic` (MQTT topic) and `data` (parsed message body). If formatting fails, the event may contain `topic` and `data` directly instead. |

**Listen in Developer tools:** subscribe to event type `livolo_mqtt_message`, then toggle a physical switch or wait for cloud push traffic to see payloads.

**Example automation trigger:**

```yaml
trigger:
  - platform: event
    event_type: livolo_mqtt_message
action:
  - service: logbook.log
    data:
      name: Livolo MQTT
      message: "MQTT event (see trigger data)"
```

## ⚠️ Beta Status & Disclaimer

This integration is currently provided **as-is** and should be considered **beta software**.

While it has been tested and works with supported Livolo gateways and switches, it is **not an official integration** and is **not affiliated with Livolo**.

By using this integration, you acknowledge that:

- The integration interacts with **Livolo cloud APIs** in a way similar to the official Android application.
- Future changes to Livolo's cloud services may **break functionality without notice**.
- The integration may contain **bugs or incomplete features**.

The author(s) of this integration **are not responsible for**:

- Issues related to your **Livolo account**
- Device malfunctions or unexpected device behavior
- Account locks, bans, or API restrictions imposed by Livolo
- Any damage, loss, or unintended behavior caused by using this integration

Use it **at your own risk**.

If you encounter issues, please open an issue in the repository with logs and details so the community can help improve the integration.
