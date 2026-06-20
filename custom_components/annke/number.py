"""Number platform for Annke integration."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SMART_FEATURES, SMART_ENDPOINT, NS_ISAPI
from .coordinator import AnnkeCoordinator, _modify_int_field
from .entity import AnnkeChannelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AnnkeCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = []

    for ch, ch_cap in coordinator.capabilities.get("channel_caps", {}).items():
        if ch_cap.get("motion"):
            entities.append(MotionSensitivityNumber(coordinator, ch))
        if ch_cap.get("image"):
            entities += [
                WdrLevelNumber(coordinator, ch),
                BrightnessNumber(coordinator, ch),
                ContrastNumber(coordinator, ch),
                SaturationNumber(coordinator, ch),
                SharpnessNumber(coordinator, ch),
            ]
        entities.append(BitrateNumber(coordinator, ch))
        for feat in SMART_FEATURES:
            if ch_cap.get(feat):
                entities.append(SmartSensitivityNumber(coordinator, ch, feat))

    async_add_entities(entities)


class _ChNumber(AnnkeChannelEntity, NumberEntity):
    _attr_mode = NumberMode.SLIDER
    def __init__(self, coordinator, channel, key):
        super().__init__(coordinator, channel, f"number_{key}")


class MotionSensitivityNumber(_ChNumber):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:tune"
    def __init__(self, c, ch):
        super().__init__(c, ch, "motion_sensitivity")
        self._attr_name = "Motion Sensitivity"
    @property
    def native_value(self): return self._ch.get("motion_sensitivity", 50)
    async def async_set_native_value(self, v): await self.coordinator.set_motion_sensitivity(self._channel, int(v))


class WdrLevelNumber(_ChNumber):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:contrast-box"
    def __init__(self, c, ch):
        super().__init__(c, ch, "wdr_level")
        self._attr_name = "WDR Level"
    @property
    def native_value(self): return self._ch.get("wdr_level", 50)
    async def async_set_native_value(self, v): await self.coordinator.set_wdr_level(self._channel, int(v))


class BrightnessNumber(_ChNumber):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:brightness-6"
    def __init__(self, c, ch):
        super().__init__(c, ch, "brightness")
        self._attr_name = "Brightness"
    @property
    def native_value(self): return self._ch.get("brightness", 50)
    async def async_set_native_value(self, v): await self.coordinator.set_brightness(self._channel, int(v))


class ContrastNumber(_ChNumber):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:contrast"
    def __init__(self, c, ch):
        super().__init__(c, ch, "contrast")
        self._attr_name = "Contrast"
    @property
    def native_value(self): return self._ch.get("contrast", 50)
    async def async_set_native_value(self, v): await self.coordinator.set_contrast(self._channel, int(v))


class SaturationNumber(_ChNumber):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:palette"
    def __init__(self, c, ch):
        super().__init__(c, ch, "saturation")
        self._attr_name = "Saturation"
    @property
    def native_value(self): return self._ch.get("saturation", 50)
    async def async_set_native_value(self, v): await self.coordinator.set_saturation(self._channel, int(v))


class SharpnessNumber(_ChNumber):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_icon = "mdi:image-filter-center-focus"
    def __init__(self, c, ch):
        super().__init__(c, ch, "sharpness")
        self._attr_name = "Sharpness"
    @property
    def native_value(self): return self._ch.get("sharpness", 50)
    async def async_set_native_value(self, v): await self.coordinator.set_sharpness(self._channel, int(v))


class BitrateNumber(_ChNumber):
    _attr_native_min_value = 32
    _attr_native_max_value = 16384
    _attr_native_step = 32
    _attr_native_unit_of_measurement = "kbps"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:video-high-definition"
    def __init__(self, c, ch):
        super().__init__(c, ch, "bitrate_max")
        self._attr_name = "Max Bitrate"
    @property
    def native_value(self): return self._ch.get("bitrate_max", 4096)
    async def async_set_native_value(self, v): await self.coordinator.set_bitrate_max(self._channel, int(v))


SMART_NUMBER_META = {
    "line_detection":  ("Line Crossing Sensitivity",   "mdi:vector-line"),
    "field_detection": ("Intrusion Sensitivity",        "mdi:shield-alert"),
    "face_detection":  ("Face Detection Sensitivity",   "mdi:face-recognition"),
    "audio_exception": ("Audio Exception Sensitivity",  "mdi:volume-alert"),
    "region_entrance": ("Region Entrance Sensitivity",  "mdi:location-enter"),
    "region_exiting":  ("Region Exiting Sensitivity",   "mdi:location-exit"),
}


class SmartSensitivityNumber(_ChNumber):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    def __init__(self, coordinator, channel, feat):
        super().__init__(coordinator, channel, f"{feat}_sensitivity")
        label, icon = SMART_NUMBER_META.get(feat, (feat, "mdi:tune"))
        self._attr_name = label
        self._attr_icon = icon
        self._feat = feat
    @property
    def native_value(self): return self._ch.get(f"{self._feat}_sensitivity", 50)
    @property
    def available(self): return f"{self._feat}_sensitivity" in self._ch
    async def async_set_native_value(self, v):
        path = SMART_ENDPOINT[self._feat].format(ch=self._channel)
        await self.coordinator._call(_modify_int_field, path, None, "sensitivityLevel", NS_ISAPI, int(v))
