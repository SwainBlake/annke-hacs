DOMAIN = "annke"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

SCAN_INTERVAL = 30
RTSP_PORT = 554

NS_ISAPI = "http://www.isapi.org/ver20/XMLSchema"
NS_STD   = "http://www.std-cgi.com/ver20/XMLSchema"
NS_PSIA  = "urn:psialliance-org"

IR_FILTER_MODES        = ["auto", "day", "night"]
SUPPLEMENT_LIGHT_MODES = ["irLight", "whiteLight", "close"]
VIDEO_CODEC_TYPES      = ["H.264", "H.265"]
VIDEO_QUALITY_TYPES    = ["VBR", "CBR"]

# Smart features probed at setup; entities only created if endpoint returns 200
SMART_FEATURES = [
    "line_detection",
    "field_detection",
    "face_detection",
    "audio_exception",
    "region_entrance",
    "region_exiting",
]

SMART_ENDPOINT = {
    "line_detection":  "/ISAPI/Smart/LineDetection/{ch}",
    "field_detection": "/ISAPI/Smart/FieldDetection/{ch}",
    "face_detection":  "/ISAPI/Smart/FaceDetection/{ch}",
    "audio_exception": "/ISAPI/Smart/AudioException/{ch}",
    "region_entrance": "/ISAPI/Smart/RegionEntrance/{ch}",
    "region_exiting":  "/ISAPI/Smart/RegionExiting/{ch}",
}

# eventType values from the ISAPI alert stream
EVENT_TYPE_KEY = {
    "VMD":             "motion",
    "tamperdetection": "tamper",
    "linedetection":   "line_detection",
    "fielddetection":  "field_detection",
    "facedetection":   "face_detection",
    "audioexception":  "audio_exception",
    "regionEntrance":  "region_entrance",
    "regionExiting":   "region_exiting",
    "diskFull":        "disk_full",
    "diskError":       "disk_error",
}
