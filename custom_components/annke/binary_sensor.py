"""Binary sensor platform – real-time events via ISAPI alert stream."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SMART_FEATURES
from .coordinator import AnnkeCoordinator
from .entity import AnnkeChannelEntity, AnnkeNvrEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AnnkeCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = []

    for ch, ch_cap in coordinator.capabilities.get("channel_caps", {}).items():
        if ch_cap.get("motion"):
            entities.append(MotionBinarySensor(coordinator, ch))
        if ch_cap.get("tamper"):
            entities.append(TamperBinarySensor(coordinator, ch))
        for feat in SMART_FEATURES:
            if ch_cap.get(feat):
                entities.append(SmartBinarySensor(coordinator, ch, feat))

    entities += [DiskFullBinarySensor(coordinator), DiskErrorBinarySensor(coordinator)]
    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Base: subscribes to alert stream, not to polling coordinator
# ---------------------------------------------------------------------------

class _AlertChannelSensor(AnnkeChannelEntity, BinarySensorEntity):
    """Binary sensor driven by the alert stream (not polling)."""

    _alert_key: str

    def __init__(self, coordinator: AnnkeCoordinator, channel: int, key: str) -> None:
        super().__init__(coordinator, channel, f"binary_{key}")
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.coordinator.register_alert_listener(self._on_alert)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()

    @callback
    def _on_alert(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.coordinator.alert_state.get(self._channel, {}).get(self._alert_key, False)

    # Override: don't grey out when coordinator polling fails
    @property
    def available(self) -> bool:
        return True


class _AlertNvrSensor(AnnkeNvrEntity, BinarySensorEntity):
    _alert_key: str

    def __init__(self, coordinator: AnnkeCoordinator, key: str) -> None:
        super().__init__(coordinator, f"binary_{key}")
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_listener = self.coordinator.register_alert_listener(self._on_alert)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()

    @callback
    def _on_alert(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.coordinator.nvr_alert.get(self._alert_key, False)

    @property
    def available(self) -> bool:
        return True


# ---------------------------------------------------------------------------
# Concrete sensors
# ---------------------------------------------------------------------------

class MotionBinarySensor(_AlertChannelSensor):
    _attr_device_class = BinarySensorDeviceClass.MOTION
    _alert_key = "motion"

    def __init__(self, coordinator, channel):
        super().__init__(coordinator, channel, "motion")
        self._attr_name = "Motion"


class TamperBinarySensor(_AlertChannelSensor):
    _attr_device_class = BinarySensorDeviceClass.TAMPER
    _alert_key = "tamper"

    def __init__(self, coordinator, channel):
        super().__init__(coordinator, channel, "tamper")
        self._attr_name = "Tamper"


SMART_LABELS = {
    "line_detection":  ("Line Crossing",    "mdi:vector-line",        BinarySensorDeviceClass.MOTION),
    "field_detection": ("Intrusion",        "mdi:shield-alert",       BinarySensorDeviceClass.MOTION),
    "face_detection":  ("Face Detection",   "mdi:face-recognition",   None),
    "audio_exception": ("Audio Exception",  "mdi:volume-alert",       BinarySensorDeviceClass.SOUND),
    "region_entrance": ("Region Entrance",  "mdi:location-enter",     BinarySensorDeviceClass.MOTION),
    "region_exiting":  ("Region Exiting",   "mdi:location-exit",      BinarySensorDeviceClass.MOTION),
}


class SmartBinarySensor(_AlertChannelSensor):
    def __init__(self, coordinator, channel, feat):
        super().__init__(coordinator, channel, feat)
        label, icon, device_class = SMART_LABELS.get(feat, (feat, "mdi:alert", None))
        self._attr_name = label
        self._attr_icon = icon
        if device_class:
            self._attr_device_class = device_class
        self._alert_key = feat


class DiskFullBinarySensor(_AlertNvrSensor):
    _attr_name = "HDD Full"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:harddisk-remove"
    _alert_key = "disk_full"

    def __init__(self, coordinator):
        super().__init__(coordinator, "disk_full")


class DiskErrorBinarySensor(_AlertNvrSensor):
    _attr_name = "HDD Error"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:harddisk-off"
    _alert_key = "disk_error"

    def __init__(self, coordinator):
        super().__init__(coordinator, "disk_error")
