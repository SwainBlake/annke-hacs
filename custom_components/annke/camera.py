"""Camera platform – snapshot via ISAPI, RTSP URL as attribute."""
from __future__ import annotations

import requests
from requests.auth import HTTPDigestAuth

from homeassistant.components.camera import Camera
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, RTSP_PORT
from .coordinator import AnnkeCoordinator
from .entity import AnnkeChannelEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator: AnnkeCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [
        AnnkeCameraEntity(coordinator, ch)
        for ch, ch_cap in coordinator.capabilities.get("channel_caps", {}).items()
        if ch_cap.get("snapshot")
    ]
    async_add_entities(entities)


def _fetch_snapshot_sync(host, username, password, channel) -> bytes | None:
    url = f"http://{host}/ISAPI/Streaming/channels/{channel * 100 + 1}/picture"
    try:
        r = requests.get(url, auth=HTTPDigestAuth(username, password), timeout=15)
        r.raise_for_status()
        return r.content
    except Exception:
        return None


class AnnkeCameraEntity(AnnkeChannelEntity, Camera):

    def __init__(self, coordinator: AnnkeCoordinator, channel: int) -> None:
        AnnkeChannelEntity.__init__(self, coordinator, channel, "camera")
        Camera.__init__(self)
        self._attr_name = "Camera"
        self._attr_is_streaming = False

    @property
    def extra_state_attributes(self):
        host = self.coordinator.host
        username = self.coordinator.username
        return {
            "rtsp_main_stream": f"rtsp://{username}:***@{host}:{RTSP_PORT}/Streaming/Channels/{self._channel * 100 + 1}",
            "rtsp_sub_stream":  f"rtsp://{username}:***@{host}:{RTSP_PORT}/Streaming/Channels/{self._channel * 100 + 2}",
        }

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        return await self.hass.async_add_executor_job(
            _fetch_snapshot_sync,
            self.coordinator.host,
            self.coordinator.username,
            self.coordinator.password,
            self._channel,
        )
