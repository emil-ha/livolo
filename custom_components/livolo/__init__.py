"""The Livolo integration."""
from __future__ import annotations

import json
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import LivoloDataUpdateCoordinator

PLATFORMS: list[Platform] = [Platform.LIGHT]

_LOGGER = logging.getLogger(__name__)

SERVICE_REFRESH_TOKEN = "refresh_token"
EVENT_REFRESH_TOKEN_RESULT = f"{DOMAIN}_refresh_token_result"
SERVICE_GENERATE_DASHBOARD = "generate_dashboard"
EVENT_GENERATE_DASHBOARD_RESULT = f"{DOMAIN}_generate_dashboard_result"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry[LivoloDataUpdateCoordinator]) -> bool:
    """Set up Livolo from a config entry."""
    coordinator = LivoloDataUpdateCoordinator(hass, entry)
    
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        raise
    
    # Store coordinator in runtime_data (modern pattern)
    entry.runtime_data = coordinator

    # Keep a registry of coordinators for domain services (so we can target a specific entry).
    domain_data = hass.data.setdefault(DOMAIN, {})
    coordinators: dict[str, LivoloDataUpdateCoordinator] = domain_data.setdefault("coordinators", {})
    coordinators[entry.entry_id] = coordinator

    # Register debug/test service once per hass instance
    if not domain_data.get("service_registered"):

        async def _handle_refresh_token(call) -> None:
            _LOGGER.info("livolo.refresh_token service called with data: %s", call.data)
            entry_id = call.data.get("entry_id")
            
            _LOGGER.info("Available coordinators: %s", list(coordinators.keys()))
            
            if entry_id:
                targets = [coordinators.get(entry_id)]
                targets = [t for t in targets if t is not None]
                _LOGGER.info("Targeting specific entry_id=%s, found: %s", entry_id, bool(targets))
            else:
                targets = list(coordinators.values())
                _LOGGER.info("Targeting all entries, found %d coordinator(s)", len(targets))

            if not targets:
                _LOGGER.warning("livolo.refresh_token called but no matching config entry found (entry_id=%s)", entry_id)
                return

            results: list[dict] = []
            for c in targets:
                try:
                    _LOGGER.info("Starting token refresh for entry_id=%s", c.entry.entry_id)
                    result = await c.async_force_refresh_token()
                    _LOGGER.info("Token refresh completed for entry_id=%s: %s", c.entry.entry_id, result)
                    results.append(result)
                except Exception as err:  # noqa: BLE001 - service should never crash HA
                    _LOGGER.exception("Failed to refresh token for entry_id=%s: %s", c.entry.entry_id, err)
                    results.append({"entry_id": c.entry.entry_id, "error": str(err)})

            _LOGGER.info("livolo.refresh_token results: %s", results)
            hass.bus.async_fire(EVENT_REFRESH_TOKEN_RESULT, {"results": results})

        async def _handle_generate_dashboard(call) -> None:
            """Generate a Lovelace YAML snippet grouping Livolo entities per device.

            Generates cards for `light.*` entities.
            """
            entry_id = call.data.get("entry_id")

            # Resolve target entry ids
            if entry_id:
                entry_ids = [entry_id] if entry_id in coordinators else []
            else:
                entry_ids = list(coordinators.keys())

            if not entry_ids:
                _LOGGER.warning(
                    "livolo.generate_dashboard called but no matching config entry found (entry_id=%s)",
                    entry_id,
                )
                return

            from homeassistant.helpers import device_registry as dr
            from homeassistant.helpers import entity_registry as er

            dev_reg = dr.async_get(hass)
            ent_reg = er.async_get(hass)

            def _q(s: str) -> str:
                # JSON quoting works fine for YAML scalar strings too.
                return json.dumps(s)

            results: list[dict] = []
            for eid in entry_ids:
                # Find all devices belonging to this config entry
                devices = [
                    d
                    for d in dev_reg.devices.values()
                    if eid in d.config_entries
                    and any(i[0] == DOMAIN for i in (d.identifiers or set()))
                ]

                # Group entity_ids by device_id
                cards: list[tuple[str, list[str]]] = []
                for d in devices:
                    device_name = d.name_by_user or d.name or "Livolo device"
                    # Get light entities (we only expose lights now)
                    entity_ids = [
                        e.entity_id
                        for e in ent_reg.entities.values()
                        if e.config_entry_id == eid
                        and e.device_id == d.id
                        and e.domain == "light"
                    ]
                    if not entity_ids:
                        continue

                    # Sort by friendly name when possible (PowerSwitch_1/2/3 order)
                    def _sort_key(entity_id: str) -> str:
                        st = hass.states.get(entity_id)
                        fn = (st.attributes.get("friendly_name") if st else "") or ""
                        return fn.lower() + "|" + entity_id

                    entity_ids = sorted(entity_ids, key=_sort_key)
                    cards.append((device_name, entity_ids))

                # Fallback: if devices aren't linked, just include all lights for the entry
                if not cards:
                    all_lights = [
                        e.entity_id
                        for e in ent_reg.entities.values()
                        if e.config_entry_id == eid and e.domain == "light"
                    ]
                    all_entities = sorted(all_lights)
                    if all_entities:
                        cards = [("Livolo", all_entities)]

                # Build Lovelace YAML using custom-features-card (matches user's preferred format)
                lines: list[str] = [
                    "type: grid",
                    "square: false",
                    "cards:",
                ]
                
                for device_name, entity_ids in cards:
                    lines.append("  - type: custom:custom-features-card")
                    lines.append("    features:")
                    # Button for device name
                    lines.append("      - type: custom:service-call")
                    lines.append("        entries:")
                    lines.append("          - type: button")
                    lines.append("            autofill_entity_id: false")
                    lines.append(f"            label: {_q(device_name)}")
                    lines.append("            thumb: md3-outlined")
                    # Toggle switches for each PowerSwitch
                    lines.append("      - type: custom:service-call")
                    lines.append("        entries:")
                    for idx, entity_id in enumerate(entity_ids, 1):
                        # Extract friendly name for label
                        st = hass.states.get(entity_id)
                        friendly_name = (st.attributes.get("friendly_name") if st else "") or entity_id
                        # Extract "Intrerupator N" from friendly name or use index
                        label = f"Intrerupator {idx}"
                        if "PowerSwitch_" in friendly_name:
                            num = friendly_name.split("PowerSwitch_")[-1].split()[0] if "PowerSwitch_" in friendly_name else str(idx)
                            label = f"Intrerupator {num}"
                        
                        lines.append("          - type: toggle")
                        lines.append(f"            entity_id: {entity_id}")
                        lines.append("            tap_action:")
                        lines.append("              action: toggle")
                        lines.append("              target:")
                        lines.append(f"                entity_id: {entity_id}")
                        lines.append("              data: {}")
                        lines.append("            swipe_only: false")
                        lines.append("            haptics: true")
                        lines.append("            thumb: default")
                        lines.append("            checked_icon: mdi:lightbulb-on-outline")
                        lines.append("            unchecked_icon: mdi:lightbulb-off-outline")
                        # Add empty styles string only to the last toggle (matches user's example)
                        if idx == len(entity_ids):
                            lines.append('            styles: ""')
                    # Styles for the service-call feature
                    lines.append("        styles: |-")
                    lines.append("          custom-feature-toggle:not([value=\"on\"]) {")
                    lines.append("           color: #bbb !important;")
                    lines.append("          }")
                    lines.append("          custom-feature-toggle[value=\"on\"] {")
                    lines.append("           color: #087b9d !important;")
                    lines.append("          }")
                    lines.append("          custom-feature-toggle {")
                    lines.append("           max-width: 33.33%;")
                    lines.append("          }")
                    lines.append("          custom-feature-toggle::part(default-switch) {")
                    lines.append("           min-width: 100%;")
                    lines.append("          }")
                    lines.append("    transparent: false")
                    # Calculate grid columns based on number of switches (device name button + switches)
                    total_items = 1 + len(entity_ids)  # 1 button + N toggles
                    lines.append("    grid_options:")
                    lines.append(f"      columns: {total_items}")
                    lines.append("      rows: 1")

                yaml_text = "\n".join(lines) + "\n"

                results.append(
                    {
                        "entry_id": eid,
                        "devices": len(cards),
                        "yaml": yaml_text,
                    }
                )

            _LOGGER.info("livolo.generate_dashboard results (devices per entry): %s", [(r["entry_id"], r["devices"]) for r in results])
            hass.bus.async_fire(EVENT_GENERATE_DASHBOARD_RESULT, {"results": results})

        # Lazy import to avoid hard dependency at import time in some HA tooling contexts
        import voluptuous as vol

        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_TOKEN,
            _handle_refresh_token,
            schema=vol.Schema({vol.Optional("entry_id"): str}),
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_GENERATE_DASHBOARD,
            _handle_generate_dashboard,
            schema=vol.Schema({vol.Optional("entry_id"): str}),
        )
        domain_data["service_registered"] = True
        _LOGGER.info("Registered service livolo.%s", SERVICE_REFRESH_TOKEN)
        _LOGGER.info("Registered service livolo.%s", SERVICE_GENERATE_DASHBOARD)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry[LivoloDataUpdateCoordinator]) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator = entry.runtime_data
        await coordinator.async_shutdown()

        domain_data = hass.data.get(DOMAIN) or {}
        coordinators: dict[str, LivoloDataUpdateCoordinator] = domain_data.get("coordinators") or {}
        coordinators.pop(entry.entry_id, None)

        # If this was the last entry, unregister our debug service.
        if domain_data.get("service_registered") and not coordinators:
            hass.services.async_remove(DOMAIN, SERVICE_REFRESH_TOKEN)
            hass.services.async_remove(DOMAIN, SERVICE_GENERATE_DASHBOARD)
            domain_data["service_registered"] = False

    return unload_ok
