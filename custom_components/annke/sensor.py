"""Sensor platform for Annke integration – NVR system metrics."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, RTSP_PORT
from .coordinator import AnnkeCoordinator
from .entity import AnnkeNvrEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AnnkeCoordinator = hass.data[DOMAIN][entry.entry_id]
    nvr_caps = coordinator.capabilities.get("nvr_caps", {})
    entities: list = []

    if nvr_caps.get("status"):
        entities += [
            CpuUsageSensor(coordinator),
            RamUsedSensor(coordinator),
            RamFreeSensor(coordinator),
            UptimeSensor(coordinator),
        ]
    if nvr_caps.get("hdd"):
        entities += [
            HddCapacitySensor(coordinator),
            HddFreeSensor(coordinator),
            HddUsedPctSensor(coordinator),
            HddStatusSensor(coordinator),
        ]
    if nvr_caps.get("streaming_status"):
        entities.append(RtspSessionsSensor(coordinator))
    if nvr_caps.get("network"):
        entities += [
            IpAddressSensor(coordinator),
            MacAddressSensor(coordinator),
        ]

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# NVR sensors
# ---------------------------------------------------------------------------

class _NvrSensor(AnnkeNvrEntity, SensorEntity):
    def __init__(self, coordinator: AnnkeCoordinator, key: str) -> None:
        super().__init__(coordinator, f"sensor_{key}")
        self._key = key

    @property
    def _nvr(self) -> dict:
        return self.coordinator.data.get("nvr", {}) if self.coordinator.data else {}


class CpuUsageSensor(_NvrSensor):
    _attr_name = "CPU Usage"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:cpu-64-bit"

    def __init__(self, c): super().__init__(c, "cpu_usage")

    @property
    def native_value(self): return self._nvr.get("cpu_usage")


class RamUsedSensor(_NvrSensor):
    _attr_name = "RAM Used"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:memory"

    def __init__(self, c): super().__init__(c, "ram_used_mb")

    @property
    def native_value(self): return round(self._nvr.get("ram_used_mb", 0), 1)


class RamFreeSensor(_NvrSensor):
    _attr_name = "RAM Free"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:memory"

    def __init__(self, c): super().__init__(c, "ram_free_mb")

    @property
    def native_value(self): return round(self._nvr.get("ram_free_mb", 0), 1)


class UptimeSensor(_NvrSensor):
    _attr_name = "Uptime"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:timer-outline"

    def __init__(self, c): super().__init__(c, "uptime_seconds")

    @property
    def native_value(self): return self._nvr.get("uptime_seconds")


class HddCapacitySensor(_NvrSensor):
    _attr_name = "HDD Capacity"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:harddisk"

    def __init__(self, c): super().__init__(c, "hdd_capacity_mb")

    @property
    def native_value(self): return self._nvr.get("hdd_capacity_mb")


class HddFreeSensor(_NvrSensor):
    _attr_name = "HDD Free"
    _attr_native_unit_of_measurement = UnitOfInformation.MEGABYTES
    _attr_device_class = SensorDeviceClass.DATA_SIZE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:harddisk"

    def __init__(self, c): super().__init__(c, "hdd_free_mb")

    @property
    def native_value(self): return self._nvr.get("hdd_free_mb")


class HddUsedPctSensor(_NvrSensor):
    _attr_name = "HDD Used"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:harddisk"

    def __init__(self, c): super().__init__(c, "hdd_used_pct")

    @property
    def native_value(self): return self._nvr.get("hdd_used_pct")


class HddStatusSensor(_NvrSensor):
    _attr_name = "HDD Status"
    _attr_icon = "mdi:harddisk"

    def __init__(self, c): super().__init__(c, "hdd_status")

    @property
    def native_value(self): return self._nvr.get("hdd_status", "unknown")


class RtspSessionsSensor(_NvrSensor):
    _attr_name = "Active RTSP Sessions"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:video-wireless"

    def __init__(self, c): super().__init__(c, "rtsp_sessions")

    @property
    def native_value(self): return self._nvr.get("rtsp_sessions", 0)


class IpAddressSensor(_NvrSensor):
    _attr_name = "IP Address"
    _attr_icon = "mdi:ip-network"

    def __init__(self, c): super().__init__(c, "ip_address")

    @property
    def native_value(self): return self._nvr.get("ip_address") or self.coordinator.host

    @property
    def extra_state_attributes(self):
        return {
            "rtsp_url_template": f"rtsp://<user>:<password>@{self.coordinator.host}:{RTSP_PORT}/Streaming/Channels/{{ch}}01",
        }


class MacAddressSensor(_NvrSensor):
    _attr_name = "MAC Address"
    _attr_icon = "mdi:ethernet"

    def __init__(self, c): super().__init__(c, "mac_address")

    @property
    def native_value(self): return self._nvr.get("mac_address") or self._dev.get("mac")
