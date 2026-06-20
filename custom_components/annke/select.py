"""Select platform for Annke integration."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, IR_FILTER_MODES, SUPPLEMENT_LIGHT_MODES, VIDEO_CODEC_TYPES, VIDEO_QUALITY_TYPES
from .coordinator import AnnkeCoordinator
from .entity import AnnkeChannelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AnnkeCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = []

    for ch, ch_cap in coordinator.capabilities.get("channel_caps", {}).items():
        if ch_cap.get("image"):
            entities += [IrFilterSelect(coordinator, ch), SupplementLightSelect(coordinator, ch)]
        # Codec and quality mode always available if channel present
        entities += [CodecSelect(coordinator, ch), QualityModeSelect(coordinator, ch)]

    async_add_entities(entities)


class _ChSelect(AnnkeChannelEntity, SelectEntity):
    def __init__(self, coordinator, channel, key):
        super().__init__(coordinator, channel, f"select_{key}")


class IrFilterSelect(_ChSelect):
    _attr_options = IR_FILTER_MODES
    _attr_icon = "mdi:theme-light-dark"
    def __init__(self, c, ch):
        super().__init__(c, ch, "ir_filter")
        self._attr_name = "IR Cut Filter"
    @property
    def current_option(self): return self._ch.get("ir_filter", "auto")
    async def async_select_option(self, option): await self.coordinator.set_ir_filter(self._channel, option)


class SupplementLightSelect(_ChSelect):
    _attr_options = SUPPLEMENT_LIGHT_MODES
    _attr_icon = "mdi:flashlight"
    def __init__(self, c, ch):
        super().__init__(c, ch, "supplement_light")
        self._attr_name = "Supplement Light"
    @property
    def current_option(self): return self._ch.get("supplement_light", "irLight")
    async def async_select_option(self, option): await self.coordinator.set_supplement_light(self._channel, option)


class CodecSelect(_ChSelect):
    _attr_options = VIDEO_CODEC_TYPES
    _attr_icon = "mdi:video"
    def __init__(self, c, ch):
        super().__init__(c, ch, "codec")
        self._attr_name = "Video Codec"
    @property
    def current_option(self): return self._ch.get("codec", "H.265")
    async def async_select_option(self, option): await self.coordinator.set_codec(self._channel, option)


class QualityModeSelect(_ChSelect):
    _attr_options = VIDEO_QUALITY_TYPES
    _attr_icon = "mdi:quality-high"
    def __init__(self, c, ch):
        super().__init__(c, ch, "quality_mode")
        self._attr_name = "Quality Mode"
    @property
    def current_option(self): return self._ch.get("quality_mode", "VBR")
    async def async_select_option(self, option): await self.coordinator.set_quality_mode(self._channel, option)
