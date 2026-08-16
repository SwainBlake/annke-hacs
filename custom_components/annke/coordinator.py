"""Coordinator for Annke ISAPI integration."""
from __future__ import annotations

import logging
import re
import socket
import threading
import time
from datetime import datetime, timedelta
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
    RECORDING_REACH_INTERVAL,
    RECORDING_SEARCH_EPOCH,
    RECORDING_SEARCH_PATH,
    RECORDING_TIME_PATH,
    SCAN_INTERVAL,
    SMART_ENDPOINT,
    SMART_FEATURES,
)

_LOGGER = logging.getLogger(__name__)

# Grace period for the alert stream thread after its connection was closed.
# Deliberately short: the connection is already gone at that point, so this
# only covers the thread unwinding, not a read that is still running.
ALERT_STREAM_JOIN_TIMEOUT = 5


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


# ---------------------------------------------------------------------------
# Recording reach: how far back does the ring buffer go?
# ---------------------------------------------------------------------------

# Die Suchbeschreibung, die /ISAPI/ContentMgmt/search/description selbst
# verlangt ("inboundData: CMSearchDescription"). maxResults 1 reicht: das erste
# Ergebnis ist das aelteste Segment, und die Antwort bleibt unter einem
# Kilobyte.
_SEARCH_BODY = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<CMSearchDescription version="1.0" xmlns="%s">\n'
    "<searchID>{%s}</searchID>\n"
    "<trackIDList><trackID>%s</trackID></trackIDList>\n"
    "<timeSpanList><timeSpan>"
    "<startTime>%s</startTime><endTime>%s</endTime>"
    "</timeSpan></timeSpanList>\n"
    "<maxResults>1</maxResults>\n"
    "<searchResultPosition>0</searchResultPosition>\n"
    "<metadataList><metadataDescriptor>//recordType.meta.std-cgi.com/"
    "</metadataDescriptor></metadataList>\n"
    "</CMSearchDescription>\n"
)

_WALL_CLOCK = re.compile(r"(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})")


def _wall_clock(text: str) -> datetime:
    """Read the recorder's wall clock, deliberately ignoring its UTC offset.

    Der Rekorder gibt bei Sommerzeit einen falschen Versatz aus: gemessen am
    2026-08-16 meldete er ``2026-08-16T15:25:42+01:00``, waehrend seine Uhr
    tatsaechlich auf mitteleuropaeischer Sommerzeit (+02:00) lief. Die Uhrzeit
    selbst stimmte auf zwei Sekunden mit dem Host ueberein.

    Deshalb wird nur die Wanduhr gelesen und Geraet gegen Geraet verglichen:
    aeltestes Segment gegen Gegenwart, beide vom selben Rekorder. Die Differenz
    ist dann unabhaengig davon richtig, ob der Versatz stimmt.
    """
    m = _WALL_CLOCK.search(text or "")
    if not m:
        raise ValueError(f"keine Zeitangabe in {text!r}")
    return datetime.strptime(f"{m.group(1)}T{m.group(2)}", "%Y-%m-%dT%H:%M:%S")


def _search_oldest_segment(session, host: str, track: int, now: datetime):
    """Return the start of the oldest segment still on disk for one track."""
    ende = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = _SEARCH_BODY % (
        NS_STD,
        f"c7c43a1e-b8e0-4a2c-9c1c-{track:012d}",
        track,
        RECORDING_SEARCH_EPOCH,
        ende,
    )
    r = session.post(
        f"http://{host}{RECORDING_SEARCH_PATH}",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/xml"},
        timeout=30,
    )
    r.raise_for_status()
    root = ET.fromstring(r.text)
    item = root.find(f".//{{{NS_STD}}}searchMatchItem")
    if item is None:
        return None
    span = item.find(f"{{{NS_STD}}}timeSpan")
    start = _text(span, "startTime", NS_STD)
    return _wall_clock(start) if start else None


def _fetch_recording_reach_sync(session, host: str, tracks: list[int]) -> dict:
    """How many days back do the recordings go, measured on the device.

    Bewusst keine Rechnung aus Kapazitaet und Schreibrate. Die waere am
    2026-08-16 um 63 Prozent danebengelegen: 3,815 TB geteilt durch 156 GB am
    Tag ergibt 24,5 Tage, tatsaechlich reichten die Aufnahmen 15,0 Tage
    zurueck. Ursache ist der Betriebsmodus ``quota``, der nicht die ganze
    Platte fuer Video freigibt.
    """
    r = session.get(f"http://{host}{RECORDING_TIME_PATH}", timeout=10)
    r.raise_for_status()
    jetzt = _wall_clock(r.text)

    aeltestes = None
    gemessene_tracks = 0
    for track in tracks:
        try:
            start = _search_oldest_segment(session, host, track, jetzt)
        except Exception as exc:  # ein stummer Kanal darf den Rest nicht kippen
            _LOGGER.debug("Recording search failed for track %s: %s", track, exc)
            continue
        if start is None:
            continue
        gemessene_tracks += 1
        if aeltestes is None or start < aeltestes:
            aeltestes = start

    if aeltestes is None:
        return {}

    return {
        "recording_oldest": aeltestes,
        "recording_reach_days": round((jetzt - aeltestes).total_seconds() / 86400, 2),
        "recording_tracks_measured": gemessene_tracks,
        "recording_nvr_time": jetzt,
    }


def _has_notification(root, method: str) -> bool:
    for notif in root.iter(f"{{{NS_ISAPI}}}EventTriggerNotification"):
        m = notif.find(f"{{{NS_ISAPI}}}notificationMethod")
        if m is not None and m.text == method:
            return True
    return False


# ---------------------------------------------------------------------------
# Capability probing
# ---------------------------------------------------------------------------

def _probe_capabilities_sync(session, host: str) -> dict:

    def probe(path) -> bool:
        try:
            r = session.get(f"http://{host}{path}", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    # Discover channels from streaming list
    channels = []
    try:
        r = session.get(f"http://{host}/ISAPI/Streaming/channels", timeout=10)
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
        # Die Aufzeichnungssuche wird nicht am Statuscode allein gemessen: das
        # Geraet antwortet auf manche nicht unterstuetzte Anfrage mit 200 und
        # einer Fehlerhuelle. Deshalb muss ein CMSearchResult zurueckkommen,
        # und die Zeitquelle muss ebenfalls lesbar sein, sonst laesst sich aus
        # dem aeltesten Segment keine Reichweite bilden.
        "recording_search": (
            probe(RECORDING_TIME_PATH)
            and _probe_recording_search(session, host, channels)
        ),
    }

    return {"channels": channels, "channel_caps": channel_caps, "nvr_caps": nvr_caps}


def _probe_recording_search(session, host: str, channels: list[int]) -> bool:
    """True only if a real search result comes back for at least one track."""
    for ch in channels:
        try:
            body = _SEARCH_BODY % (
                NS_STD,
                f"c7c43a1e-b8e0-4a2c-9c1c-{ch * 100 + 1:012d}",
                ch * 100 + 1,
                RECORDING_SEARCH_EPOCH,
                "2038-01-01T00:00:00Z",
            )
            r = session.post(
                f"http://{host}{RECORDING_SEARCH_PATH}",
                data=body.encode("utf-8"),
                headers={"Content-Type": "application/xml"},
                timeout=15,
            )
            if r.status_code == 200 and "CMSearchResult" in r.text:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# Full data fetch
# ---------------------------------------------------------------------------

def _fetch_all_sync(session, host: str, caps: dict) -> dict:

    dev = _get(session, host, "/ISAPI/System/deviceInfo")
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
            proxy = _get(session, host, "/ISAPI/ContentMgmt/InputProxy/channels")
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
        st = _get(session, host, "/ISAPI/System/status")
        cpu_list = _find(st, "CPUList", NS_STD)
        cpu = _find(cpu_list, "CPU", NS_STD) if cpu_list is not None else None
        mem_list = _find(st, "MemoryList", NS_STD)
        mem = _find(mem_list, "Memory", NS_STD) if mem_list is not None else None
        nvr["cpu_usage"]      = int(_text(cpu, "cpuUtilization", NS_STD, "0") or 0)
        nvr["ram_used_mb"]    = float((_text(mem, "memoryUsage",     NS_STD, "0") or "0").strip())
        nvr["ram_free_mb"]    = float((_text(mem, "memoryAvailable", NS_STD, "0") or "0").strip())
        nvr["uptime_seconds"] = int(_text(st, "deviceUpTime", NS_STD, "0") or 0)

    if nvr_caps.get("hdd"):
        stor = _get(session, host, "/ISAPI/ContentMgmt/Storage")
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
        ss = _get(session, host, "/ISAPI/Streaming/status")
        nvr["rtsp_sessions"] = int(_text(ss, "totalStreamingSessions", NS_STD, "0") or 0)

    if nvr_caps.get("network"):
        net = _get(session, host, "/ISAPI/System/Network/interfaces")
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
            md = _get(session, host, f"/ISAPI/System/Video/inputs/channels/{ch}/motionDetection")
            layout = _find(md, "MotionDetectionLayout", NS_ISAPI)
            data["motion_enabled"]     = _bool(_text(md, "enabled", NS_ISAPI))
            data["motion_sensitivity"] = int(_text(layout, "sensitivityLevel", NS_ISAPI, "50") or 50)

        if ch_cap.get("tamper"):
            td = _get(session, host, f"/ISAPI/System/Video/inputs/channels/{ch}/tamperDetection")
            data["tamper_enabled"] = _bool(_text(td, "enabled", NS_ISAPI))

        if ch_cap.get("privacy"):
            pm = _get(session, host, f"/ISAPI/System/Video/inputs/channels/{ch}/privacyMask")
            data["privacy_mask_enabled"] = _bool(_text(pm, "enabled", NS_ISAPI))

        if ch_cap.get("vmd_trigger"):
            vmd = _get(session, host, f"/ISAPI/Event/triggers/VMD-{ch}")
            data["notify_push"]  = _has_notification(vmd, "center")
            data["notify_email"] = _has_notification(vmd, "email")

        if ch_cap.get("tamper_trigger"):
            te = _get(session, host, f"/ISAPI/Event/triggers/tamper-{ch}")
            data["tamper_notify_push"] = _has_notification(te, "center")

        if ch_cap.get("image"):
            img = _get(session, host, f"/ISAPI/Image/channels/{ch}")
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
            ov = _get(session, host, f"/ISAPI/System/Video/inputs/channels/{ch}/overlays")
            dt_ov   = _find(ov, "DateTimeOverlay",    NS_STD)
            name_ov = _find(ov, "channelNameOverlay", NS_STD)
            data["osd_datetime"]    = _bool(_text(dt_ov,   "enabled", NS_STD))
            data["osd_channelname"] = _bool(_text(name_ov, "enabled", NS_STD))

        try:
            sc    = _get(session, host, f"/ISAPI/Streaming/channels/{ch * 100 + 1}")
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
                    sf = _get(session, host, SMART_ENDPOINT[feat].format(ch=ch))
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

def _modify_bool_field(session, host, path, tag, ns, value: bool):
    root = _get(session, host, path)
    el = root.find(f"{{{ns}}}{tag}")
    if el is not None:
        el.text = "true" if value else "false"
    _put(session, host, path, root, ns)


def _modify_nested_bool(session, host, path, parent_tag, tag, ns, value: bool):
    root = _get(session, host, path)
    parent = root.find(f"{{{ns}}}{parent_tag}") if parent_tag else root
    if parent is not None:
        el = parent.find(f"{{{ns}}}{tag}")
        if el is not None:
            el.text = "true" if value else "false"
    _put(session, host, path, root, ns)


def _modify_int_field(session, host, path, parent_tag, tag, ns, value: int):
    root = _get(session, host, path)
    parent = root.find(f"{{{ns}}}{parent_tag}") if parent_tag else root
    if parent is None:
        parent = root
    el = parent.find(f"{{{ns}}}{tag}")
    if el is not None:
        el.text = str(value)
    _put(session, host, path, root, ns)


def _modify_text_field(session, host, path, parent_tag, tag, ns, value: str):
    root = _get(session, host, path)
    parent = root.find(f"{{{ns}}}{parent_tag}") if parent_tag else root
    if parent is None:
        parent = root
    el = parent.find(f"{{{ns}}}{tag}")
    if el is not None:
        el.text = value
    _put(session, host, path, root, ns)


def _toggle_notification(session, host, url_path, method: str, enabled: bool):
    root = _get(session, host, url_path)
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
    _put(session, host, url_path, root, NS_ISAPI)


def _set_smart_codec_sync(session, host, ch, value: bool):
    path = f"/ISAPI/Streaming/channels/{ch * 100 + 1}"
    root = _get(session, host, path)
    video = root.find(f"{{{NS_STD}}}Video")
    if video is not None:
        sc = video.find(f"{{{NS_STD}}}SmartCodec")
        if sc is not None:
            el = sc.find(f"{{{NS_STD}}}enabled")
            if el is not None:
                el.text = "true" if value else "false"
    _put(session, host, path, root, NS_STD)


def _set_wdr_enabled_sync(session, host, ch, value: bool):
    path = f"/ISAPI/Image/channels/{ch}"
    root = _get(session, host, path)
    wdr = root.find(f"{{{NS_STD}}}WDR")
    if wdr is not None:
        el = wdr.find(f"{{{NS_STD}}}mode")
        if el is not None:
            el.text = "open" if value else "close"
    _put(session, host, path, root, NS_STD)


def _set_osd_datetime_sync(session, host, ch, value: bool):
    path = f"/ISAPI/System/Video/inputs/channels/{ch}/overlays"
    root = _get(session, host, path)
    dt_ov = root.find(f"{{{NS_STD}}}DateTimeOverlay")
    if dt_ov is not None:
        el = dt_ov.find(f"{{{NS_STD}}}enabled")
        if el is not None:
            el.text = "true" if value else "false"
    _put(session, host, path, root, NS_STD)


def _set_osd_channelname_sync(session, host, ch, value: bool):
    path = f"/ISAPI/System/Video/inputs/channels/{ch}/overlays"
    root = _get(session, host, path)
    name_ov = root.find(f"{{{NS_STD}}}channelNameOverlay")
    if name_ov is not None:
        el = name_ov.find(f"{{{NS_STD}}}enabled")
        if el is not None:
            el.text = "true" if value else "false"
    _put(session, host, path, root, NS_STD)


# ---------------------------------------------------------------------------
# Alert stream reader
# ---------------------------------------------------------------------------

def _read_alert_stream_sync(session, host, on_event, stop_event, publish_response=None):
    """Long-lived reader for the ISAPI alert stream.

    Runs on a dedicated thread, not on the Home Assistant executor pool: this
    loop never returns while the integration is loaded, and permanently holding
    a pool thread would starve other integrations.

    Two things bound how long this thread survives an unload:

    * the read timeout, which is the fallback — the loop can only notice
      `stop_event` between chunks, so a long timeout would keep the thread
      alive well past unload;
    * `publish_response`, which hands the live response to the coordinator so
      that shutdown can close the socket underneath this loop instead of
      waiting out the timeout. The blocked read then fails immediately, the
      exception is swallowed below and the loop leaves through `stop_event`.
    """
    url = f"http://{host}/ISAPI/Event/notification/alertStream"
    while not stop_event.is_set():
        try:
            with session.get(url, stream=True, timeout=(10, 30)) as resp:
                resp.raise_for_status()
                if publish_response is not None:
                    publish_response(resp)
                    # The response only became reachable for the closer now, so
                    # re-check: a stop between the request and this point would
                    # otherwise be missed and the read would block again.
                    if stop_event.is_set():
                        break
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
                # wait() instead of sleep(): returns immediately on shutdown
                stop_event.wait(5)
        finally:
            if publish_response is not None:
                publish_response(None)


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
        self._alert_stop = threading.Event()
        self._alert_thread: threading.Thread | None = None
        self._alert_response = None
        self._alert_response_lock = threading.Lock()
        self._alert_listeners: list = []
        # Reichweite des Ringpuffers: eigener, langsamer Takt (siehe const.py).
        self._reach: dict = {}
        self._reach_at: float = 0.0

        # One session for polling and writes, a separate one for the alert
        # stream. Reusing a session keeps the digest handshake and the TCP
        # connection alive; a fresh session per call doubled the round trips.
        # requests' HTTPDigestAuth keeps its state thread-local, so sharing the
        # polling session between the executor jobs is safe. The alert stream
        # gets its own because it holds a connection open indefinitely.
        auth = HTTPDigestAuth(username, password)
        self.session = requests.Session()
        self.session.auth = auth
        self._alert_session = requests.Session()
        self._alert_session.auth = HTTPDigestAuth(username, password)

    async def async_probe_capabilities(self) -> None:
        """Find out what this device actually supports.

        Must run before the first refresh — the fetch is driven entirely by
        these capabilities and returns no channels at all without them.
        """
        self.capabilities = await self.hass.async_add_executor_job(
            _probe_capabilities_sync, self.session, self.host
        )
        for ch in self.capabilities.get("channels", []):
            self.alert_state[ch] = {k: False for k in EVENT_TYPE_KEY.values() if k not in ("disk_full", "disk_error")}
        self.nvr_alert = {"disk_full": False, "disk_error": False}

    def start_alert_stream(self) -> None:
        self._alert_stop.clear()
        self._alert_thread = threading.Thread(
            target=_read_alert_stream_sync,
            args=(
                self._alert_session,
                self.host,
                self._on_alert_event,
                self._alert_stop,
                self._publish_alert_response,
            ),
            name=f"{DOMAIN}-alertstream-{self.host}",
            daemon=True,
        )
        self._alert_thread.start()

    def _publish_alert_response(self, response) -> None:
        """Record the response the reader thread is currently blocked on.

        Called from the reader thread, read from the event loop during
        shutdown, hence the lock.
        """
        with self._alert_response_lock:
            self._alert_response = response

    def _abort_alert_stream(self) -> None:
        """Tear down the open alert connection so the blocked read returns now.

        Runs in the executor. Without this the reader only notices the stop
        flag after the next chunk or the read timeout, up to 30 seconds later,
        and shutdown waited that out.

        `shutdown()` before `close()` is the point: a bare close leaves a read
        that is already blocked in the socket sitting there, because the file
        descriptor stays alive until the reading thread lets go of it.
        Shutting the socket down delivers an immediate end of file instead, so
        the read returns on the spot. Close alone would only help for the next
        pass through the loop.
        """
        with self._alert_response_lock:
            response = self._alert_response
            self._alert_response = None
        if response is None:
            return
        try:
            raw = getattr(response, "raw", None)
            # urllib3 renamed the attribute between 1.x and 2.x
            conn = getattr(raw, "_connection", None) or getattr(raw, "connection", None)
            sock = getattr(conn, "sock", None)
            if sock is not None:
                sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            # already gone, which is the outcome we wanted anyway
            pass
        except Exception as exc:  # noqa: BLE001 - shutdown must never raise here
            _LOGGER.debug("Could not shut down the alert stream socket: %s", exc)
        try:
            response.close()
        except Exception as exc:  # noqa: BLE001 - closing must never raise here
            _LOGGER.debug("Closing the alert stream response failed: %s", exc)

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
        thread = self._alert_thread
        if thread is not None and thread.is_alive():
            # Tear the connection down instead of waiting for the read to time
            # out. Waiting was the whole problem: the join ran as an executor
            # job, so a silent stream held a pool thread for up to 35 seconds
            # and Home Assistant ran into its own shutdown deadline
            # ("Thread[SyncWorker_*] is still running at shutdown").
            await self.hass.async_add_executor_job(self._abort_alert_stream)
            # Short grace period only, so the sessions are not closed out from
            # under a thread that is still unwinding. The thread is a daemon:
            # if it overruns even this, it cannot keep the process alive.
            await self.hass.async_add_executor_job(thread.join, ALERT_STREAM_JOIN_TIMEOUT)
            if thread.is_alive():
                _LOGGER.debug(
                    "Alert stream thread still unwinding after %ss, leaving it to the daemon flag",
                    ALERT_STREAM_JOIN_TIMEOUT,
                )
        self._alert_thread = None

        # super() cancels the scheduled refresh — skipping it left a timer behind.
        await super().async_shutdown()

        await self.hass.async_add_executor_job(self.session.close)
        await self.hass.async_add_executor_job(self._alert_session.close)

    async def _async_update_data(self) -> dict:
        try:
            data = await self.hass.async_add_executor_job(
                _fetch_all_sync, self.session, self.host, self.capabilities
            )
        except Exception as err:
            raise UpdateFailed(f"Error communicating with device: {err}") from err

        data["nvr"].update(await self._async_recording_reach())
        return data

    async def _async_recording_reach(self) -> dict:
        """Ring buffer reach, refreshed on its own slow schedule.

        Ein Fehlschlag der Suche darf die uebrigen 118 Entitaeten nicht
        umwerfen, deshalb faengt diese Ebene alles ab und behaelt im Zweifel
        den letzten gemessenen Wert.
        """
        if not self.capabilities.get("nvr_caps", {}).get("recording_search"):
            return {}
        if self._reach and time.monotonic() - self._reach_at < RECORDING_REACH_INTERVAL:
            return self._reach

        tracks = [ch * 100 + 1 for ch in self.capabilities.get("channels", [])]
        try:
            neu = await self.hass.async_add_executor_job(
                _fetch_recording_reach_sync, self.session, self.host, tracks
            )
        except Exception as exc:
            _LOGGER.debug("Recording reach not updated: %s", exc)
            return self._reach

        if neu:
            self._reach = neu
            self._reach_at = time.monotonic()
        return self._reach

    async def _call(self, fn, *args):
        await self.hass.async_add_executor_job(fn, self.session, self.host, *args)
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
