"""Base entity classes for the Annke integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AnnkeCoordinator


class AnnkeNvrEntity(CoordinatorEntity):
    """Entity attached to the NVR device itself."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AnnkeCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_{coordinator.host}_{key}"

    @property
    def _dev(self) -> dict:
        return self.coordinator.data["device"] if self.coordinator.data else {}

    @property
    def device_info(self) -> DeviceInfo:
        dev = self._dev
        info = DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.host)},
            name=dev.get("name", "Annke"),
            manufacturer="Annke",
            model=dev.get("model"),
            sw_version=dev.get("firmware"),
            serial_number=dev.get("serial"),
        )
        if dev.get("mac"):
            info["connections"] = {("mac", dev["mac"])}
        return info


class AnnkeChannelEntity(CoordinatorEntity):
    """Entity attached to a single camera channel (child of NVR device)."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: AnnkeCoordinator, channel: int, key: str) -> None:
        super().__init__(coordinator)
        self._channel = channel
        self._attr_unique_id = f"{DOMAIN}_{coordinator.host}_ch{channel}_{key}"

    @property
    def _dev(self) -> dict:
        return self.coordinator.data["device"] if self.coordinator.data else {}

    @property
    def _ch(self) -> dict:
        if self.coordinator.data:
            return self.coordinator.data["channels"].get(self._channel, {})
        return {}

    @property
    def _channel_meta(self) -> dict:
        if self.coordinator.data:
            return self.coordinator.data.get("channel_meta", {}).get(self._channel, {})
        return {}

    @property
    def device_info(self) -> DeviceInfo:
        meta = self._channel_meta
        dev = self._dev
        # Use camera model/serial/firmware if available, else fall back to NVR info
        cam_model    = meta.get("cam_model")    or dev.get("model")
        cam_serial   = meta.get("cam_serial")   or None
        cam_firmware = meta.get("cam_firmware") or dev.get("firmware")
        ch_name      = meta.get("name", f"Channel {self._channel}")
        info = DeviceInfo(
            identifiers={(DOMAIN, f"{self.coordinator.host}_ch{self._channel}")},
            name=ch_name,
            manufacturer="Annke",
            model=cam_model,
            sw_version=cam_firmware,
            via_device=(DOMAIN, self.coordinator.host),
        )
        if cam_serial:
            info["serial_number"] = cam_serial
        return info
