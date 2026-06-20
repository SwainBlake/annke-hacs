"""Coordinator for Annke ISAPI integration."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from xml.etree import ElementTree as ET

import requests
from requests.auth import HTTPDigestAuth

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    EVENT_TYPE_KEY,
    NS_ISAPI,
    NS_STD,
    SCAN_INTERVAL,
    SMART_ENDPOINT,
    SMART_FEATURES,
)

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# XML helpers
# ---------------------------------------------------------------------------

def _text(el, tag, ns, default=None):
    found = el.find(f"{{{ns}}}{tag}") if el is not None else None
    return found.text if found is not None else default


def _find(el, tag, ns):
    return el.find(f"{{{ns}}}{tag}") if el is not None else None


def _bool(val):
    return (val or "").lower() == "true"


def _get(session, host, path):
    r = session.get(f"http://{host}{path}", timeout=10)
    r.raise_for_status()
    return ET.fromstring(r.text)


def _put(session, host, path, root, ns):
    ET.register_namespace("", ns)
    payload = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    r = session.put(
        f"http://{host}{path}",
        data=payload.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
        timeout=10,
    )
    r.raise_for_status()


def _has_notification(root, method: str) -> bool:
    for notif in root.iter(f"{{{NS_ISAPI}}}EventTriggerNotification"):
        m = notif.find(f"{{{NS_ISAPI}}}notificationMethod")
        if m is not None and m.text == method:
            return True
    return False


# ---------------------------------------------------------------------------
# Capability probing
# ---------------------------------------------------------------------------

def _probe_capabilities_sync(host: str, username: str, password: str) -> dict:
    auth = HTTPDigestAuth(username, password)
    s = requests.Session()
    s.auth = auth

    def probe(path) -> bool:
        try:
            r = s.get(f"http://{host}{path}", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    # Discover channels from streaming list
    channels = []
    try:
        r = s.get(f"http://{host}/ISAPI/Streaming/channels", timeout=10)
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            for ch_el in root:
                for ns in (NS_STD, NS_ISAPI):
                    id_el = ch_el.find(f"{{{ns}}}id")
                    if id_el is not None:
                        sid = int(id_el.text)
                        if sid % 100 == 1:
                            channels.append(sid // 100)
                        break
    except Exception:
        pass

    if not channels:
        for ch in range(1, 9):
            if probe(f"/ISAPI/System/Video/inputs/channels/{ch}/motionDetection"):
                channels.append(ch)

    channel_caps = {}
    for ch in channels:
        caps = {
            "motion":         probe(f"/ISAPI/System/Video/inputs/channels/{ch}/motionDetection"),
            "tamper":         probe(f"/ISAPI/System/Video/inputs/channels/{ch}/tamperDetection"),
            "privacy":        probe(f"/ISAPI/System/Video/inputs/channels/{ch}/privacyMask"),
            "image":          probe(f"/ISAPI/Image/channels/{ch}"),
            "overlays":       probe(f"/ISAPI/System/Video/inputs/channels/{ch}/overlays"),
            "snapshot":       probe(f"/ISAPI/Streaming/channels/{ch * 100 + 1}/picture"),
            "vmd_trigger":    probe(f"/ISAPI/Event/triggers/VMD-{ch}"),
            "tamper_trigger": probe(f"/ISAPI/Event/triggers/tamper-{ch}"),
        }
        for feat in SMART_FEATURES:
            caps[feat] = probe(SMART_ENDPOINT[feat].format(ch=ch))
        channel_caps[ch] = caps

    nvr_caps = {
        "status":           probe("/ISAPI/System/status"),
        "hdd":              probe("/ISAPI/ContentMgmt/Storage"),
        "streaming_status": probe("/ISAPI/Streaming/status"),
        "network":          probe("/ISAPI/System/Network/interfaces"),
        "input_proxy":      probe("/ISAPI/ContentMgmt/InputProxy/channels"),
    }

    return {"channels": channels, "channel_caps": channel_caps, "nvr_caps": nvr_caps}


# ---------------------------------------------------------------------------
# Full data fetch
# ---------------------------------------------------------------------------

def _fetch_all_sync(host: str, username: str, password: str, caps: dict) -> dict:
    auth = HTTPDigestAuth(username, password)
    s = requests.Session()
    s.auth = auth

    dev = _get(s, host, "/ISAPI/System/deviceInfo")
    device_info = {
        "model":    _text(dev, "model",           NS_STD, ""),
        "firmware": _text(dev, "firmwareVersion", NS_STD, ""),
        "serial":   _text(dev, "serialNumber",    NS_STD, ""),
        "mac":      _text(dev, "macAddress",      NS_STD, ""),
        "name":     _text(dev, "deviceName",      NS_STD, "Annke"),
        "type":     _text(dev, "deviceType",      NS_STD, "NVR"),
    }

    # Channel names + camera device info from InputProxy
    channel_meta: dict[int, dict] = {}
    nvr_caps = caps.get("nvr_caps", {})
    if nvr_caps.get("input_proxy"):
        try:
            proxy = _get(s, host, "/ISAPI/ContentMgmt/InputProxy/channels")
            for ch_el in proxy:
                id_el = _find(ch_el, "id", NS_STD)
                if id_el is None:
                    continue
                ch_id = int(id_el.text)
                src = _find(ch_el, "sourceInputPortDescriptor", NS_STD)
                channel_meta[ch_id] = {
                    "name":     _text(ch_el, "name",           NS_STD, f"Channel {ch_id}"),
                    "cam_model":   _text(src, "model",          NS_STD, "") if src is not None else "",
                    "cam_serial":  _text(src, "serialNumber",   NS_STD, "") if src is not None else "",
                    "cam_firmware":_text(src, "firmwareVersion",NS_STD, "") if src is not None else "",
                    "cam_ip":      _text(src, "ipAddress",      NS_STD, "") if src is not None else "",
                }
        except Exception:
            pass

    nvr = {}


    if nvr_caps.get("status"):
        st = _get(s, host, "/ISAPI/System/status")
        cpu_list = _find(st, "CPUList", NS_STD)
        cpu = _find(cpu_list, "CPU", NS_STD) if cpu_list is not None else None
        mem_list = _find(st, "MemoryList", NS_STD)
        mem = _find(mem_list, "Memory", NS_STD) if mem_list is not None else None
        nvr["cpu_usage"]      = int(_text(cpu, "cpuUtilization", NS_STD, "0") or 0)
        nvr["ram_used_mb"]    = float((_text(mem, "memoryUsage",     NS_STD, "0") or "0").strip())
        nvr["ram_free_mb"]    = float((_text(mem, "memoryAvailable", NS_STD, "0") or "0").strip())
        nvr["uptime_seconds"] = int(_text(st, "deviceUpTime", NS_STD, "0") or 0)

    if nvr_caps.get("hdd"):
        stor = _get(s, host, "/ISAPI/ContentMgmt/Storage")
        hdd_list = _find(stor, "hddList", NS_STD)
        hdd = _find(hdd_list, "hdd", NS_STD) if hdd_list is not None else None
        cap_mb  = int(_text(hdd, "capacity",  NS_STD, "0") or 0)
        free_mb = int(_text(hdd, "freeSpace", NS_STD, "0") or 0)
        used_mb = cap_mb - free_mb
        nvr["hdd_capacity_mb"] = cap_mb
        nvr["hdd_free_mb"]     = free_mb
        nvr["hdd_used_mb"]     = used_mb
        nvr["hdd_used_pct"]    = round(used_mb / cap_mb * 100, 1) if cap_mb else 0
        nvr["hdd_status"]      = _text(hdd, "status", NS_STD, "unknown")

    if nvr_caps.get("streaming_status"):
        ss = _get(s, host, "/ISAPI/Streaming/status")
        nvr["rtsp_sessions"] = int(_text(ss, "totalStreamingSessions", NS_STD, "0") or 0)

    if nvr_caps.get("network"):
        net = _get(s, host, "/ISAPI/System/Network/interfaces")
        ifaces = list(net)
        if ifaces:
            iface = ifaces[0]
            ip_el  = _find(iface, "IPAddress",  NS_STD)
            mac_el = _find(iface, "MACAddress", NS_STD)
            nvr["ip_address"]  = _text(ip_el,  "ipAddress",  NS_STD, "")
            nvr["mac_address"] = _text(mac_el, "macAddress", NS_STD, "") or device_info["mac"]

    channels = {}
    for ch, ch_cap in caps.get("channel_caps", {}).items():
        data = {}

        if ch_cap.get("motion"):
            md = _get(s, host, f"/ISAPI/System/Video/inputs/channels/{ch}/motionDetection")
            layout = _find(md, "MotionDetectionLayout", NS_ISAPI)
            data["motion_enabled"]     = _bool(_text(md, "enabled", NS_ISAPI))
            data["motion_sensitivity"] = int(_text(layout, "sensitivityLevel", NS_ISAPI, "50") or 50)

        if ch_cap.get("tamper"):
            td = _get(s, host, f"/ISAPI/System/Video/inputs/channels/{ch}/tamperDetection")
            data["tamper_enabled"] = _bool(_text(td, "enabled", NS_ISAPI))

        if ch_cap.get("privacy"):
            pm = _get(s, host, f"/ISAPI/System/Video/inputs/channels/{ch}/privacyMask")
            data["privacy_mask_enabled"] = _bool(_text(pm, "enabled", NS_ISAPI))

        if ch_cap.get("vmd_trigger"):
            vmd = _get(s, host, f"/ISAPI/Event/triggers/VMD-{ch}")
            data["notify_push"]  = _has_notification(vmd, "center")
            data["notify_email"] = _has_notification(vmd, "email")

        if ch_cap.get("tamper_trigger"):
            te = _get(s, host, f"/ISAPI/Event/triggers/tamper-{ch}")
            data["tamper_notify_push"] = _has_notification(te, "center")

        if ch_cap.get("image"):
            img = _get(s, host, f"/ISAPI/Image/channels/{ch}")
            ircut = _find(img, "IrcutFilter",     NS_STD)
            suplt = _find(img, "SupplementLight", NS_STD)
            flip  = _find(img, "ImageFlip",       NS_STD)
            wdr   = _find(img, "WDR",             NS_STD)
            color = _find(img, "Color",           NS_STD)
            sharp = _find(img, "Sharpness",       NS_STD)
            data["ir_filter"]        = _text(ircut, "IrcutFilterType",     NS_STD, "auto")
            data["supplement_light"] = _text(suplt, "supplementLightMode", NS_STD, "irLight")
            data["image_flip"]       = _bool(_text(flip,  "enabled",        NS_STD))
            data["wdr_enabled"]      = (_text(wdr, "mode", NS_STD, "close") or "close") != "close"
            data["wdr_level"]        = int(_text(wdr,   "WDRLevel",        NS_STD, "50") or 50)
            data["brightness"]       = int(_text(color, "brightnessLevel", NS_STD, "50") or 50)
            data["contrast"]         = int(_text(color, "contrastLevel",   NS_STD, "50") or 50)
            data["saturation"]       = int(_text(color, "saturationLevel", NS_STD, "50") or 50)
            data["sharpness"]        = int(_text(sharp, "SharpnessLevel",  NS_STD, "50") or 50)

        if ch_cap.get("overlays"):
            ov = _get(s, host, f"/ISAPI/System/Video/inputs/channels/{ch}/overlays")
            dt_ov   = _find(ov, "DateTimeOverlay",    NS_STD)
            name_ov = _find(ov, "channelNameOverlay", NS_STD)
            data["osd_datetime"]    = _bool(_text(dt_ov,   "enabled", NS_STD))
            data["osd_channelname"] = _bool(_text(name_ov, "enabled", NS_STD))

        try:
            sc    = _get(s, host, f"/ISAPI/Streaming/channels/{ch * 100 + 1}")
            video = _find(sc, "Video", NS_STD)
            audio = _find(sc, "Audio", NS_STD)
            sc_el = _find(video, "SmartCodec", NS_STD) if video is not None else None
            data["codec"]        = _text(video, "videoCodecType",            NS_STD, "H.265")
            data["bitrate_max"]  = int(_text(video, "vbrUpperCap",           NS_STD, "4096") or 4096)
            data["framerate"]    = int(_text(video, "maxFrameRate",           NS_STD, "0")    or 0)
            data["quality_mode"] = _text(video, "videoQualityControlType",   NS_STD, "VBR")
            data["smart_codec"]  = _bool(_text(sc_el, "enabled",             NS_STD))
            data["audio_enabled"]= _bool(_text(audio, "enabled",             NS_STD))
        except Exception:
            pass

        for feat in SMART_FEATURES:
            if ch_cap.get(feat):
                try:
                    sf = _get(s, host, SMART_ENDPOINT[feat].format(ch=ch))
                    data[f"{feat}_enabled"] = _bool(_text(sf, "enabled", NS_ISAPI))
                    sens = _text(sf, "sensitivityLevel", NS_ISAPI)
                    if sens is not None:
                        data[f"{feat}_sensitivity"] = int(sens)
                except Exception:
                    pass

        # Merge channel meta (name, camera model/serial) into channel data
        if ch in channel_meta:
            data.update(channel_meta[ch])
        else:
            data.setdefault("name", f"Channel {ch}")

        channels[ch] = data

    return {"device": device_info, "nvr": nvr, "channels": channels, "channel_meta": channel_meta}


# ---------------------------------------------------------------------------
# PUT helpers
# ---------------------------------------------------------------------------

def _modify_bool_field(host, username, password, path, tag, ns, value: bool):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    root = _get(s, host, path)
    el = root.find(f"{{{ns}}}{tag}")
    if el is not None:
        el.text = "true" if value else "false"
    _put(s, host, path, root, ns)


def _modify_nested_bool(host, username, password, path, parent_tag, tag, ns, value: bool):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    root = _get(s, host, path)
    parent = root.find(f"{{{ns}}}{parent_tag}") if parent_tag else root
    if parent is not None:
        el = parent.find(f"{{{ns}}}{tag}")
        if el is not None:
            el.text = "true" if value else "false"
    _put(s, host, path, root, ns)


def _modify_int_field(host, username, password, path, parent_tag, tag, ns, value: int):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    root = _get(s, host, path)
    parent = root.find(f"{{{ns}}}{parent_tag}") if parent_tag else root
    if parent is None:
        parent = root
    el = parent.find(f"{{{ns}}}{tag}")
    if el is not None:
        el.text = str(value)
    _put(s, host, path, root, ns)


def _modify_text_field(host, username, password, path, parent_tag, tag, ns, value: str):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    root = _get(s, host, path)
    parent = root.find(f"{{{ns}}}{parent_tag}") if parent_tag else root
    if parent is None:
        parent = root
    el = parent.find(f"{{{ns}}}{tag}")
    if el is not None:
        el.text = value
    _put(s, host, path, root, ns)


def _toggle_notification(host, username, password, url_path, method: str, enabled: bool):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    root = _get(s, host, url_path)
    notif_list = root.find(f"{{{NS_ISAPI}}}EventTriggerNotificationList")
    if notif_list is None:
        return
    existing = None
    for notif in notif_list.findall(f"{{{NS_ISAPI}}}EventTriggerNotification"):
        m = notif.find(f"{{{NS_ISAPI}}}notificationMethod")
        if m is not None and m.text == method:
            existing = notif
            break
    if enabled and existing is None:
        n = ET.SubElement(notif_list, f"{{{NS_ISAPI}}}EventTriggerNotification")
        ET.SubElement(n, f"{{{NS_ISAPI}}}id").text = method
        ET.SubElement(n, f"{{{NS_ISAPI}}}notificationMethod").text = method
    elif not enabled and existing is not None:
        notif_list.remove(existing)
    else:
        return
    _put(s, host, url_path, root, NS_ISAPI)


def _set_smart_codec_sync(host, username, password, ch, value: bool):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    path = f"/ISAPI/Streaming/channels/{ch * 100 + 1}"
    root = _get(s, host, path)
    video = root.find(f"{{{NS_STD}}}Video")
    if video is not None:
        sc = video.find(f"{{{NS_STD}}}SmartCodec")
        if sc is not None:
            el = sc.find(f"{{{NS_STD}}}enabled")
            if el is not None:
                el.text = "true" if value else "false"
    _put(s, host, path, root, NS_STD)


def _set_wdr_enabled_sync(host, username, password, ch, value: bool):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    path = f"/ISAPI/Image/channels/{ch}"
    root = _get(s, host, path)
    wdr = root.find(f"{{{NS_STD}}}WDR")
    if wdr is not None:
        el = wdr.find(f"{{{NS_STD}}}mode")
        if el is not None:
            el.text = "open" if value else "close"
    _put(s, host, path, root, NS_STD)


def _set_osd_datetime_sync(host, username, password, ch, value: bool):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    path = f"/ISAPI/System/Video/inputs/channels/{ch}/overlays"
    root = _get(s, host, path)
    dt_ov = root.find(f"{{{NS_STD}}}DateTimeOverlay")
    if dt_ov is not None:
        el = dt_ov.find(f"{{{NS_STD}}}enabled")
        if el is not None:
            el.text = "true" if value else "false"
    _put(s, host, path, root, NS_STD)


def _set_osd_channelname_sync(host, username, password, ch, value: bool):
    s = requests.Session()
    s.auth = HTTPDigestAuth(username, password)
    path = f"/ISAPI/System/Video/inputs/channels/{ch}/overlays"
    root = _get(s, host, path)
    name_ov = root.find(f"{{{NS_STD}}}channelNameOverlay")
    if name_ov is not None:
        el = name_ov.find(f"{{{NS_STD}}}enabled")
        if el is not None:
            el.text = "true" if value else "false"
    _put(s, host, path, root, NS_STD)


# ---------------------------------------------------------------------------
# Alert stream reader
# ---------------------------------------------------------------------------

def _read_alert_stream_sync(host, username, password, on_event, stop_event):
    auth = HTTPDigestAuth(username, password)
    url = f"http://{host}/ISAPI/Event/notification/alertStream"
    while not stop_event.is_set():
        try:
            with requests.get(url, auth=auth, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                buf = b""
                for chunk in resp.iter_content(chunk_size=512):
                    if stop_event.is_set():
                        break
                    buf += chunk
                    while b"<?xml" in buf and b"</EventNotificationAlert>" in buf:
                        start = buf.find(b"<?xml")
                        end   = buf.find(b"</EventNotificationAlert>") + len(b"</EventNotificationAlert>")
                        xml_bytes = buf[start:end]
                        buf = buf[end:]
                        try:
                            root = ET.fromstring(xml_bytes.decode("utf-8", errors="replace"))
                            ch_el    = root.find(f"{{{NS_ISAPI}}}channelID") or root.find(f"{{{NS_ISAPI}}}dynChannelID")
                            type_el  = root.find(f"{{{NS_ISAPI}}}eventType")
                            state_el = root.find(f"{{{NS_ISAPI}}}eventState")
                            if type_el is not None and state_el is not None:
                                channel = int(ch_el.text) if ch_el is not None else 0
                                on_event(channel, type_el.text.strip(), state_el.text.strip() == "active")
                        except Exception:
                            pass
        except Exception as exc:
            if not stop_event.is_set():
                _LOGGER.debug("Alert stream disconnected (%s), reconnecting in 5s", exc)
                time.sleep(5)


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------

class AnnkeCoordinator(DataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, host: str, username: str, password: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL),
        )
        self.host = host
        self.username = username
        self.password = password
        self.capabilities: dict = {}
        self.alert_state: dict[int, dict[str, bool]] = {}
        self.nvr_alert: dict[str, bool] = {}
        self._alert_stop = asyncio.Event()
        self._alert_task = None
        self._alert_listeners: list = []

    async def async_setup(self) -> None:
        self.capabilities = await self.hass.async_add_executor_job(
            _probe_capabilities_sync, self.host, self.username, self.password
        )
        for ch in self.capabilities.get("channels", []):
            self.alert_state[ch] = {k: False for k in EVENT_TYPE_KEY.values() if k not in ("disk_full", "disk_error")}
        self.nvr_alert = {"disk_full": False, "disk_error": False}
        self._start_alert_stream()

    def _start_alert_stream(self) -> None:
        self._alert_stop.clear()
        self._alert_task = self.hass.loop.run_in_executor(
            None,
            _read_alert_stream_sync,
            self.host,
            self.username,
            self.password,
            self._on_alert_event,
            self._alert_stop,
        )

    def _on_alert_event(self, channel: int, event_type: str, active: bool) -> None:
        key = EVENT_TYPE_KEY.get(event_type)
        if key is None:
            return
        if key in ("disk_full", "disk_error"):
            self.nvr_alert[key] = active
        elif channel in self.alert_state:
            self.alert_state[channel][key] = active
        self.hass.loop.call_soon_threadsafe(self._fire_alert_listeners)

    @callback
    def _fire_alert_listeners(self) -> None:
        for listener in list(self._alert_listeners):
            listener()

    def register_alert_listener(self, listener) -> callable:
        self._alert_listeners.append(listener)
        def remove():
            if listener in self._alert_listeners:
                self._alert_listeners.remove(listener)
        return remove

    async def async_shutdown(self) -> None:
        self._alert_stop.set()

    async def _async_update_data(self) -> dict:
        try:
            return await self.hass.async_add_executor_job(
                _fetch_all_sync, self.host, self.username, self.password, self.capabilities
            )
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err

    async def _call(self, fn, *args):
        await self.hass.async_add_executor_job(fn, self.host, self.username, self.password, *args)
        await self.async_request_refresh()

    # Motion
    async def set_motion_enabled(self, ch, v):
        await self._call(_modify_bool_field, f"/ISAPI/System/Video/inputs/channels/{ch}/motionDetection", "enabled", NS_ISAPI, v)

    async def set_motion_sensitivity(self, ch, v):
        await self._call(_modify_int_field, f"/ISAPI/System/Video/inputs/channels/{ch}/motionDetection", "MotionDetectionLayout", "sensitivityLevel", NS_ISAPI, v)

    # Tamper
    async def set_tamper_enabled(self, ch, v):
        await self._call(_modify_bool_field, f"/ISAPI/System/Video/inputs/channels/{ch}/tamperDetection", "enabled", NS_ISAPI, v)

    # Privacy mask
    async def set_privacy_mask(self, ch, v):
        await self._call(_modify_bool_field, f"/ISAPI/System/Video/inputs/channels/{ch}/privacyMask", "enabled", NS_ISAPI, v)

    # Notifications
    async def set_vmd_notification(self, ch, method, v):
        await self._call(_toggle_notification, f"/ISAPI/Event/triggers/VMD-{ch}", method, v)

    async def set_tamper_notification(self, ch, method, v):
        await self._call(_toggle_notification, f"/ISAPI/Event/triggers/tamper-{ch}", method, v)

    # Image
    async def set_ir_filter(self, ch, v):
        await self._call(_modify_text_field, f"/ISAPI/Image/channels/{ch}", "IrcutFilter", "IrcutFilterType", NS_STD, v)

    async def set_supplement_light(self, ch, v):
        await self._call(_modify_text_field, f"/ISAPI/Image/channels/{ch}", "SupplementLight", "supplementLightMode", NS_STD, v)

    async def set_image_flip(self, ch, v):
        await self._call(_modify_nested_bool, f"/ISAPI/Image/channels/{ch}", "ImageFlip", "enabled", NS_STD, v)

    async def set_wdr_enabled(self, ch, v):
        await self._call(_set_wdr_enabled_sync, ch, v)

    async def set_wdr_level(self, ch, v):
        await self._call(_modify_int_field, f"/ISAPI/Image/channels/{ch}", "WDR", "WDRLevel", NS_STD, v)

    async def set_brightness(self, ch, v):
        await self._call(_modify_int_field, f"/ISAPI/Image/channels/{ch}", "Color", "brightnessLevel", NS_STD, v)

    async def set_contrast(self, ch, v):
        await self._call(_modify_int_field, f"/ISAPI/Image/channels/{ch}", "Color", "contrastLevel", NS_STD, v)

    async def set_saturation(self, ch, v):
        await self._call(_modify_int_field, f"/ISAPI/Image/channels/{ch}", "Color", "saturationLevel", NS_STD, v)

    async def set_sharpness(self, ch, v):
        await self._call(_modify_int_field, f"/ISAPI/Image/channels/{ch}", "Sharpness", "SharpnessLevel", NS_STD, v)

    # OSD
    async def set_osd_datetime(self, ch, v):
        await self._call(_set_osd_datetime_sync, ch, v)

    async def set_osd_channelname(self, ch, v):
        await self._call(_set_osd_channelname_sync, ch, v)

    # Streaming
    async def set_codec(self, ch, v):
        await self._call(_modify_text_field, f"/ISAPI/Streaming/channels/{ch * 100 + 1}", "Video", "videoCodecType", NS_STD, v)

    async def set_quality_mode(self, ch, v):
        await self._call(_modify_text_field, f"/ISAPI/Streaming/channels/{ch * 100 + 1}", "Video", "videoQualityControlType", NS_STD, v)

    async def set_bitrate_max(self, ch, v):
        await self._call(_modify_int_field, f"/ISAPI/Streaming/channels/{ch * 100 + 1}", "Video", "vbrUpperCap", NS_STD, v)

    async def set_audio_enabled(self, ch, v):
        await self._call(_modify_nested_bool, f"/ISAPI/Streaming/channels/{ch * 100 + 1}", "Audio", "enabled", NS_STD, v)

    async def set_smart_codec(self, ch, v):
        await self._call(_set_smart_codec_sync, ch, v)

    # Smart features
    async def set_smart_feature_enabled(self, ch, feat, v):
        path = SMART_ENDPOINT[feat].format(ch=ch)
        await self._call(_modify_bool_field, path, "enabled", NS_ISAPI, v)
