#!/usr/bin/env python3
"""Exercises the blocking helpers in coordinator.py against a fake ISAPI device.

    python3 tests/test_sync_helpers.py

No Home Assistant required — the few HA imports are stubbed. This covers the
parts that talk HTTP and XML, in particular the shared-session refactor and the
alert stream's shutdown behaviour.
"""

import os
import sys
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "custom_components"))

# --- Stub the Home Assistant imports coordinator.py pulls in ----------------
def _stub(name, **attrs):
    mod = types.ModuleType(name)
    mod.__path__ = []  # mark as a package so submodule imports resolve
    for k, v in attrs.items():
        setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


class _Coordinator:
    def __init__(self, *a, **kw):
        pass


_stub("homeassistant")
_stub("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
_stub("homeassistant.config_entries", ConfigEntry=object, ConfigFlow=object)
_stub("homeassistant.helpers")
_stub("homeassistant.helpers.update_coordinator",
      DataUpdateCoordinator=_Coordinator,
      UpdateFailed=type("UpdateFailed", (Exception,), {}))

# Import the module directly instead of through the package __init__, which
# pulls in far more of Home Assistant than these tests need.
import importlib.util  # noqa: E402

_pkg = os.path.join(ROOT, "custom_components", "annke")
spec = importlib.util.spec_from_file_location("annke_const", os.path.join(_pkg, "const.py"))
const = importlib.util.module_from_spec(spec)
spec.loader.exec_module(const)
sys.modules["annke_const"] = const
NS_ISAPI, NS_STD = const.NS_ISAPI, const.NS_STD

_src = open(os.path.join(_pkg, "coordinator.py")).read().replace("from .const import", "from annke_const import")
co = types.ModuleType("annke_coordinator")
co.__dict__["__file__"] = os.path.join(_pkg, "coordinator.py")
exec(compile(_src, os.path.join(_pkg, "coordinator.py"), "exec"), co.__dict__)

passed = failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"PASS — {name}")
    else:
        failed += 1
        print(f"FAIL — {name} {detail}")


# --- Fake device ------------------------------------------------------------

def _std(body):
    return f'<?xml version="1.0" encoding="UTF-8"?><root xmlns="{NS_STD}">{body}</root>'


def _isapi(tag, body):
    return f'<?xml version="1.0" encoding="UTF-8"?><{tag} xmlns="{NS_ISAPI}">{body}</{tag}>'


ROUTES = {
    "/ISAPI/Streaming/channels": _std("<StreamingChannel><id>101</id></StreamingChannel>"),
    "/ISAPI/System/deviceInfo": _std(
        "<model>DW-41KD</model><firmwareVersion>V4.30</firmwareVersion>"
        "<serialNumber>SN123</serialNumber><macAddress>aa:bb:cc:dd:ee:ff</macAddress>"
        "<deviceName>NVR-Keller</deviceName><deviceType>NVR</deviceType>"),
    "/ISAPI/System/status": _std(
        "<deviceUpTime>86400</deviceUpTime>"
        "<CPUList><CPU><cpuUtilization>17</cpuUtilization></CPU></CPUList>"
        "<MemoryList><Memory><memoryUsage>512</memoryUsage>"
        "<memoryAvailable>256</memoryAvailable></Memory></MemoryList>"),
    "/ISAPI/ContentMgmt/Storage": _std(
        "<hddList><hdd><capacity>1000</capacity><freeSpace>250</freeSpace>"
        "<status>ok</status></hdd></hddList>"),
    "/ISAPI/Streaming/status": _std("<totalStreamingSessions>3</totalStreamingSessions>"),
    "/ISAPI/System/Network/interfaces": _std(
        "<NetworkInterface><IPAddress><ipAddress>192.168.1.9</ipAddress></IPAddress>"
        "<MACAddress><macAddress>aa:bb:cc:dd:ee:ff</macAddress></MACAddress></NetworkInterface>"),
    "/ISAPI/ContentMgmt/InputProxy/channels": _std(
        "<InputProxyChannel><id>1</id><name>Einfahrt</name>"
        "<sourceInputPortDescriptor><model>C800</model><serialNumber>CAM1</serialNumber>"
        "<firmwareVersion>V5.7</firmwareVersion><ipAddress>192.168.1.21</ipAddress>"
        "</sourceInputPortDescriptor></InputProxyChannel>"),
    "/ISAPI/System/Video/inputs/channels/1/motionDetection": _isapi(
        "MotionDetection",
        "<enabled>true</enabled><MotionDetectionLayout><sensitivityLevel>40</sensitivityLevel>"
        "</MotionDetectionLayout>"),
    "/ISAPI/System/Video/inputs/channels/1/tamperDetection": _isapi(
        "TamperDetection", "<enabled>false</enabled>"),
    "/ISAPI/System/Video/inputs/channels/1/privacyMask": _isapi(
        "PrivacyMask", "<enabled>false</enabled>"),
    "/ISAPI/System/Video/inputs/channels/1/overlays": _std(
        "<DateTimeOverlay><enabled>true</enabled></DateTimeOverlay>"
        "<channelNameOverlay><enabled>false</enabled></channelNameOverlay>"),
    "/ISAPI/Image/channels/1": _std(
        "<IrcutFilter><IrcutFilterType>auto</IrcutFilterType></IrcutFilter>"
        "<SupplementLight><supplementLightMode>irLight</supplementLightMode></SupplementLight>"
        "<ImageFlip><enabled>false</enabled></ImageFlip>"
        "<WDR><mode>open</mode><WDRLevel>60</WDRLevel></WDR>"
        "<Color><brightnessLevel>55</brightnessLevel><contrastLevel>45</contrastLevel>"
        "<saturationLevel>50</saturationLevel></Color>"
        "<Sharpness><SharpnessLevel>33</SharpnessLevel></Sharpness>"),
    "/ISAPI/Streaming/channels/101": _std(
        "<Video><videoCodecType>H.265</videoCodecType><vbrUpperCap>4096</vbrUpperCap>"
        "<maxFrameRate>2000</maxFrameRate><videoQualityControlType>VBR</videoQualityControlType>"
        "<SmartCodec><enabled>true</enabled></SmartCodec></Video>"
        "<Audio><enabled>false</enabled></Audio>"),
    "/ISAPI/Streaming/channels/101/picture": "JPEGDATA",
    "/ISAPI/Event/triggers/VMD-1": _isapi(
        "EventTrigger",
        "<EventTriggerNotificationList>"
        "<EventTriggerNotification><id>center</id>"
        "<notificationMethod>center</notificationMethod></EventTriggerNotification>"
        "</EventTriggerNotificationList>"),
    "/ISAPI/Event/triggers/tamper-1": _isapi(
        "EventTrigger", "<EventTriggerNotificationList></EventTriggerNotificationList>"),
}

ALERT = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    f'<EventNotificationAlert xmlns="{NS_ISAPI}">'
    "<dynChannelID>1</dynChannelID><eventType>VMD</eventType>"
    "<eventState>active</eventState></EventNotificationAlert>"
)

puts = []

# When switched on, the alert stream sends its one event and then says nothing
# more. That is the case the shutdown path has to survive: the reader sits in a
# blocking read and only the socket going away can free it before the timeout.
silent_stream = {"on": False}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _body(self, text, status=200):
        data = text.encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/ISAPI/Event/notification/alertStream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/mixed; boundary=boundary")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self._chunk(ALERT.encode())
            if silent_stream["on"]:
                time.sleep(45)  # well past the reader's 30s read timeout
                return
            # keepalives so the reader loop can notice its stop flag quickly
            for _ in range(100):
                time.sleep(0.1)
                try:
                    self._chunk(b" ")
                except Exception:
                    return
            return
        if self.path in ROUTES:
            return self._body(ROUTES[self.path])
        return self._body("not found", 404)

    def _chunk(self, payload):
        self.wfile.write(b"%x\r\n%s\r\n" % (len(payload), payload))
        self.wfile.flush()

    def do_PUT(self):
        length = int(self.headers.get("Content-Length") or 0)
        puts.append((self.path, self.rfile.read(length).decode()))
        self._body("<ResponseStatus/>")


def main():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    host = f"127.0.0.1:{srv.server_address[1]}"
    session = requests.Session()

    # --- capability probing -------------------------------------------------
    caps = co._probe_capabilities_sync(session, host)
    check("probing finds the channel", caps["channels"] == [1], caps["channels"])
    check("probing detects supported features",
          caps["channel_caps"][1]["motion"] and caps["channel_caps"][1]["image"])
    check("probing marks absent features as unsupported",
          caps["channel_caps"][1]["face_detection"] is False)
    check("probing detects NVR endpoints", caps["nvr_caps"]["hdd"] and caps["nvr_caps"]["status"])

    # --- full fetch ---------------------------------------------------------
    data = co._fetch_all_sync(session, host, caps)
    check("reads device info", data["device"]["model"] == "DW-41KD", data["device"])
    check("reads NVR status", data["nvr"]["cpu_usage"] == 17 and data["nvr"]["uptime_seconds"] == 86400,
          data["nvr"])
    check("computes HDD usage", data["nvr"]["hdd_used_pct"] == 75.0, data["nvr"].get("hdd_used_pct"))
    ch = data["channels"][1]
    check("reads motion settings", ch["motion_enabled"] is True and ch["motion_sensitivity"] == 40, ch)
    check("reads image settings", ch["wdr_enabled"] is True and ch["brightness"] == 55, ch)
    check("reads streaming settings", ch["codec"] == "H.265" and ch["smart_codec"] is True, ch)
    check("merges the channel name from InputProxy", ch["name"] == "Einfahrt", ch.get("name"))
    check("detects the push notification", ch["notify_push"] is True, ch)

    # This is why probing has to run before the first refresh: without
    # capabilities the fetch reports the device and not a single channel.
    blind = co._fetch_all_sync(session, host, {})
    check("fetching without capabilities yields no channels",
          blind["channels"] == {} and blind["device"]["model"] == "DW-41KD", blind["channels"])

    # --- writes go through the same session --------------------------------
    puts.clear()
    co._modify_bool_field(session, host,
                          "/ISAPI/System/Video/inputs/channels/1/tamperDetection",
                          "enabled", NS_ISAPI, True)
    check("PUT reaches the device", len(puts) == 1, puts)
    check("PUT flips the value", "<enabled>true</enabled>" in puts[0][1], puts[:1])

    puts.clear()
    co._modify_int_field(session, host, "/ISAPI/Image/channels/1", "Color", "brightnessLevel",
                         NS_STD, 80)
    check("nested int write keeps the document", "<brightnessLevel>80</brightnessLevel>" in puts[0][1]
          and "<contrastLevel>45</contrastLevel>" in puts[0][1], puts[:1])

    check("one session serves probing, fetching and writing",
          len(session.adapters) > 0 and isinstance(session, requests.Session))

    # --- alert stream: events and prompt shutdown --------------------------
    events = []
    stop = threading.Event()
    alert_session = requests.Session()
    thread = threading.Thread(
        target=co._read_alert_stream_sync,
        args=(alert_session, host, lambda c, t, a: events.append((c, t, a)), stop),
        daemon=True,
    )
    thread.start()
    deadline = time.time() + 5
    while not events and time.time() < deadline:
        time.sleep(0.05)
    check("parses an event from the stream", events == [(1, "VMD", True)], events)

    stop.set()
    thread.join(5)
    check("thread stops promptly on the stop flag", not thread.is_alive())

    # --- shutdown aborts a blocked read instead of waiting out the timeout --
    # Without the abort this thread would hang on the read for 30 seconds, so
    # the join below is what makes the difference visible.
    silent_stream["on"] = True
    stop2 = threading.Event()
    # DataUpdateCoordinator is stubbed out above, so the real class can be
    # built here without a Home Assistant instance.
    coordinator = co.AnnkeCoordinator(None, host, "admin", "secret")
    thread2 = threading.Thread(
        target=co._read_alert_stream_sync,
        args=(requests.Session(), host, lambda c, t, a: None, stop2,
              coordinator._publish_alert_response),
        daemon=True,
    )
    thread2.start()
    deadline = time.time() + 5
    while coordinator._alert_response is None and time.time() < deadline:
        time.sleep(0.05)
    check("the reader hands its live response to the coordinator",
          coordinator._alert_response is not None)

    stop2.set()
    started = time.time()
    coordinator._abort_alert_stream()
    thread2.join(10)
    elapsed = time.time() - started
    check("closing the socket ends the blocked read at once",
          not thread2.is_alive() and elapsed < 5, f"{elapsed:.1f}s")
    check("the coordinator no longer holds a response afterwards",
          coordinator._alert_response is None)

    srv.shutdown()
    print(f"\n{passed}/{passed + failed} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
