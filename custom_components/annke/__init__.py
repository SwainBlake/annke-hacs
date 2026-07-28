"""Annke integration – NVR and IP cameras via Hikvision ISAPI."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN
from .coordinator import AnnkeCoordinator

PLATFORMS = ["binary_sensor", "camera", "number", "select", "sensor", "switch"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = AnnkeCoordinator(
        hass,
        host=entry.data[CONF_HOST],
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
    )
    # Order matters: the fetch is driven entirely by the probed capabilities.
    # Refreshing first returned device info and zero channels, which left every
    # channel entity blank until the next poll 30 seconds later.
    await coordinator.async_probe_capabilities()
    await coordinator.async_config_entry_first_refresh()

    # Only start the stream once the device has answered — a failed refresh
    # raises ConfigEntryNotReady and would otherwise leave a thread running
    # behind a dead config entry.
    coordinator.start_alert_stream()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator: AnnkeCoordinator = hass.data[DOMAIN][entry.entry_id]
    await coordinator.async_shutdown()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
