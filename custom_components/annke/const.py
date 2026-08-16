DOMAIN = "annke"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"

SCAN_INTERVAL = 30
RTSP_PORT = 554

# --- Reichweite des Ringpuffers --------------------------------------------
# Der Rekorder haelt seine Aufnahmen in einem Ringspeicher. Die Platte steht
# deshalb dauerhaft auf 100 Prozent belegt; das sagt nichts darueber, wie weit
# die Aufzeichnung zurueckreicht. Genau das beantwortet die Aufzeichnungssuche
# unter RECORDING_SEARCH_PATH: sie liefert das aelteste noch vorhandene
# Segment. Die Zahl ist damit gemessen und nicht gerechnet.
#
# Eigener, viel langsamerer Takt als SCAN_INTERVAL: der Wert bewegt sich um
# Minuten pro Stunde, und das Geraet erlaubt laut
# /ISAPI/ContentMgmt/search/profile nur eine Suche gleichzeitig
# (maxConcurrentSearches 1). Eine Suche je Viertelstunde kostet vier Anfragen
# von je rund einem Kilobyte.
RECORDING_REACH_INTERVAL = 900
RECORDING_SEARCH_PATH = "/ISAPI/ContentMgmt/search"
RECORDING_TIME_PATH = "/ISAPI/System/time/localTime"
# Untergrenze des Suchfensters. Frueher als das kann keine Aufnahme liegen,
# und ein festes Datum ist nachvollziehbarer als eine gerechnete Spanne.
RECORDING_SEARCH_EPOCH = "2000-01-01T00:00:00Z"

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
