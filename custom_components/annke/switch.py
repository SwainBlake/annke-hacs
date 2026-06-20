"""Switch platform for Annke integration."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
            entities.append(MotionSwitch(coordinator, ch))
        if ch_cap.get("tamper"):
            entities.append(TamperSwitch(coordinator, ch))
        if ch_cap.get("privacy"):
            entities.append(PrivacyMaskSwitch(coordinator, ch))
        if ch_cap.get("vmd_trigger"):
            entities += [PushNotificationSwitch(coordinator, ch), EmailNotificationSwitch(coordinator, ch)]
        if ch_cap.get("tamper_trigger"):
            entities.append(TamperPushSwitch(coordinator, ch))
        if ch_cap.get("image"):
            entities += [ImageFlipSwitch(coordinator, ch), WdrSwitch(coordinator, ch)]
        if ch_cap.get("overlays"):
            entities += [OsdDatetimeSwitch(coordinator, ch), OsdChannelNameSwitch(coordinator, ch)]
        entities += [AudioSwitch(coordinator, ch), SmartCodecSwitch(coordinator, ch)]
        for feat in SMART_FEATURES:
            if ch_cap.get(feat):
                entities.append(SmartFeatureSwitch(coordinator, ch, feat))

    channels = list(coordinator.capabilities.get("channel_caps", {}).keys())
    if channels:
        entities += [AllPushNotificationsSwitch(coordinator, channels), AllMotionSwitch(coordinator, channels)]

    async_add_entities(entities)


class _ChSwitch(AnnkeChannelEntity, SwitchEntity):
    def __init__(self, coordinator, channel, key):
        super().__init__(coordinator, channel, f"switch_{key}")


# Detection
class MotionSwitch(_ChSwitch):
    _attr_icon = "mdi:motion-sensor"
    def __init__(self, c, ch):
        super().__init__(c, ch, "motion_enabled")
        self._attr_name = "Motion Detection"
    @property
    def is_on(self): return self._ch.get("motion_enabled", False)
    async def async_turn_on(self, **_): await self.coordinator.set_motion_enabled(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_motion_enabled(self._channel, False)


class TamperSwitch(_ChSwitch):
    _attr_icon = "mdi:camera-lock"
    def __init__(self, c, ch):
        super().__init__(c, ch, "tamper_enabled")
        self._attr_name = "Tamper Detection"
    @property
    def is_on(self): return self._ch.get("tamper_enabled", False)
    async def async_turn_on(self, **_): await self.coordinator.set_tamper_enabled(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_tamper_enabled(self._channel, False)


class PrivacyMaskSwitch(_ChSwitch):
    _attr_icon = "mdi:eye-off"
    def __init__(self, c, ch):
        super().__init__(c, ch, "privacy_mask")
        self._attr_name = "Privacy Mask"
    @property
    def is_on(self): return self._ch.get("privacy_mask_enabled", False)
    async def async_turn_on(self, **_): await self.coordinator.set_privacy_mask(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_privacy_mask(self._channel, False)


# Notifications
class PushNotificationSwitch(_ChSwitch):
    _attr_icon = "mdi:bell"
    def __init__(self, c, ch):
        super().__init__(c, ch, "notify_push")
        self._attr_name = "Push Notifications"
    @property
    def is_on(self): return self._ch.get("notify_push", False)
    async def async_turn_on(self, **_): await self.coordinator.set_vmd_notification(self._channel, "center", True)
    async def async_turn_off(self, **_): await self.coordinator.set_vmd_notification(self._channel, "center", False)


class EmailNotificationSwitch(_ChSwitch):
    _attr_icon = "mdi:email-alert"
    def __init__(self, c, ch):
        super().__init__(c, ch, "notify_email")
        self._attr_name = "Email Notifications"
    @property
    def is_on(self): return self._ch.get("notify_email", False)
    async def async_turn_on(self, **_): await self.coordinator.set_vmd_notification(self._channel, "email", True)
    async def async_turn_off(self, **_): await self.coordinator.set_vmd_notification(self._channel, "email", False)


class TamperPushSwitch(_ChSwitch):
    _attr_icon = "mdi:bell-alert"
    def __init__(self, c, ch):
        super().__init__(c, ch, "tamper_notify_push")
        self._attr_name = "Tamper Push Notifications"
    @property
    def is_on(self): return self._ch.get("tamper_notify_push", False)
    async def async_turn_on(self, **_): await self.coordinator.set_tamper_notification(self._channel, "center", True)
    async def async_turn_off(self, **_): await self.coordinator.set_tamper_notification(self._channel, "center", False)


# Image
class ImageFlipSwitch(_ChSwitch):
    _attr_icon = "mdi:flip-vertical"
    def __init__(self, c, ch):
        super().__init__(c, ch, "image_flip")
        self._attr_name = "Image Flip"
    @property
    def is_on(self): return self._ch.get("image_flip", False)
    async def async_turn_on(self, **_): await self.coordinator.set_image_flip(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_image_flip(self._channel, False)


class WdrSwitch(_ChSwitch):
    _attr_icon = "mdi:contrast-box"
    def __init__(self, c, ch):
        super().__init__(c, ch, "wdr_enabled")
        self._attr_name = "WDR"
    @property
    def is_on(self): return self._ch.get("wdr_enabled", False)
    async def async_turn_on(self, **_): await self.coordinator.set_wdr_enabled(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_wdr_enabled(self._channel, False)


# OSD
class OsdDatetimeSwitch(_ChSwitch):
    _attr_icon = "mdi:clock-outline"
    def __init__(self, c, ch):
        super().__init__(c, ch, "osd_datetime")
        self._attr_name = "OSD Date/Time"
    @property
    def is_on(self): return self._ch.get("osd_datetime", False)
    async def async_turn_on(self, **_): await self.coordinator.set_osd_datetime(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_osd_datetime(self._channel, False)


class OsdChannelNameSwitch(_ChSwitch):
    _attr_icon = "mdi:label-outline"
    def __init__(self, c, ch):
        super().__init__(c, ch, "osd_channelname")
        self._attr_name = "OSD Channel Name"
    @property
    def is_on(self): return self._ch.get("osd_channelname", False)
    async def async_turn_on(self, **_): await self.coordinator.set_osd_channelname(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_osd_channelname(self._channel, False)


# Streaming
class AudioSwitch(_ChSwitch):
    _attr_icon = "mdi:microphone"
    def __init__(self, c, ch):
        super().__init__(c, ch, "audio_enabled")
        self._attr_name = "Audio"
    @property
    def is_on(self): return self._ch.get("audio_enabled", False)
    async def async_turn_on(self, **_): await self.coordinator.set_audio_enabled(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_audio_enabled(self._channel, False)


class SmartCodecSwitch(_ChSwitch):
    _attr_icon = "mdi:chip"
    def __init__(self, c, ch):
        super().__init__(c, ch, "smart_codec")
        self._attr_name = "Smart Codec (H.265+)"
    @property
    def is_on(self): return self._ch.get("smart_codec", False)
    async def async_turn_on(self, **_): await self.coordinator.set_smart_codec(self._channel, True)
    async def async_turn_off(self, **_): await self.coordinator.set_smart_codec(self._channel, False)


# Smart features
SMART_SWITCH_META = {
    "line_detection":  ("Line Crossing Detection",   "mdi:vector-line"),
    "field_detection": ("Intrusion Detection",        "mdi:shield-alert"),
    "face_detection":  ("Face Detection",             "mdi:face-recognition"),
    "audio_exception": ("Audio Exception Detection",  "mdi:volume-alert"),
    "region_entrance": ("Region Entrance Detection",  "mdi:location-enter"),
    "region_exiting":  ("Region Exiting Detection",   "mdi:location-exit"),
}


class SmartFeatureSwitch(_ChSwitch):
    def __init__(self, coordinator, channel, feat):
        super().__init__(coordinator, channel, f"{feat}_enabled")
        label, icon = SMART_SWITCH_META.get(feat, (feat, "mdi:alert"))
        self._attr_name = "{label}"
        self._attr_icon = icon
        self._feat = feat
    @property
    def is_on(self): return self._ch.get(f"{self._feat}_enabled", False)
    async def async_turn_on(self, **_): await self.coordinator.set_smart_feature_enabled(self._channel, self._feat, True)
    async def async_turn_off(self, **_): await self.coordinator.set_smart_feature_enabled(self._channel, self._feat, False)


# Master switches
class AllPushNotificationsSwitch(AnnkeNvrEntity, SwitchEntity):
    _attr_icon = "mdi:bell-ring"
    _attr_name = "All Push Notifications"
    def __init__(self, coordinator, channels):
        super().__init__(coordinator, "all_push_notifications")
        self._channels = channels
    @property
    def is_on(self):
        if not self.coordinator.data:
            return False
        return all(self.coordinator.data["channels"].get(ch, {}).get("notify_push", False) for ch in self._channels)
    async def async_turn_on(self, **_):
        for ch in self._channels: await self.coordinator.set_vmd_notification(ch, "center", True)
    async def async_turn_off(self, **_):
        for ch in self._channels: await self.coordinator.set_vmd_notification(ch, "center", False)


class AllMotionSwitch(AnnkeNvrEntity, SwitchEntity):
    _attr_icon = "mdi:motion-sensor"
    _attr_name = "All Motion Detection"
    def __init__(self, coordinator, channels):
        super().__init__(coordinator, "all_motion")
        self._channels = channels
    @property
    def is_on(self):
        if not self.coordinator.data:
            return False
        return all(self.coordinator.data["channels"].get(ch, {}).get("motion_enabled", False) for ch in self._channels)
    async def async_turn_on(self, **_):
        for ch in self._channels: await self.coordinator.set_motion_enabled(ch, True)
    async def async_turn_off(self, **_):
        for ch in self._channels: await self.coordinator.set_motion_enabled(ch, False)
