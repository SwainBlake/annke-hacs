# ISAPI Endpoint Reference – Annke N98PBK

Tested with firmware V4.75.000, HTTP Digest Auth.

## Accessible endpoints (200 OK)

### Device info
```
GET /ISAPI/System/deviceInfo
```
Returns model, serial, firmware version, MAC address. Read-only.

### Motion Detection (per channel)
```
GET /ISAPI/System/Video/inputs/channels/{1-4}/motionDetection
PUT /ISAPI/System/Video/inputs/channels/{1-4}/motionDetection
```
Key fields:
- `<enabled>true|false</enabled>` – detection on/off
- `<MotionDetectionLayout><sensitivityLevel>0-100</sensitivityLevel>` – sensitivity

### Tamper Detection (per channel)
```
GET /ISAPI/System/Video/inputs/channels/{1-4}/tamperDetection
PUT /ISAPI/System/Video/inputs/channels/{1-4}/tamperDetection
```
Key fields:
- `<enabled>true|false</enabled>`

### Event Triggers – Motion (VMD)
```
GET /ISAPI/Event/triggers/VMD-{1-4}
PUT /ISAPI/Event/triggers/VMD-{1-4}
GET /ISAPI/Event/triggers/           (lists all triggers)
```
Controls notification methods via `EventTriggerNotificationList`.
Adding/removing `<EventTriggerNotification>` entries enables/disables each method:
- `center` – push notification to monitoring center (Annke app)
- `email` – email alert
- `record` – trigger recording (includes `dynVideoInputID`)

### Event Triggers – Tamper
```
GET /ISAPI/Event/triggers/tamper-{1-4}
PUT /ISAPI/Event/triggers/tamper-{1-4}
```
Same structure as VMD triggers, supports `center` notification.

### Image Settings (per channel)
```
GET /ISAPI/Image/channels/{1-4}
PUT /ISAPI/Image/channels/{1-4}
```
Key fields (namespace: `http://www.std-cgi.com/ver20/XMLSchema`):
- `<ImageFlip><enabled>true|false</enabled>` – vertical flip
- `<IrcutFilter><IrcutFilterType>auto|day|night</IrcutFilterType>` – IR cut filter
- `<SupplementLight><supplementLightMode>irLight|whiteLight|close</supplementLightMode>` – IR/white light
- `<Color><brightnessLevel>`, `<contrastLevel>`, `<saturationLevel>` (0–100)
- `<WDR><mode>open|close</mode>`, `<WDRLevel>` (0–100)

### Video Input Overlays (per channel)
```
GET /ISAPI/System/Video/inputs/channels/{1-4}/overlays
PUT /ISAPI/System/Video/inputs/channels/{1-4}/overlays
```
OSD text overlay configuration. Not yet implemented in integration.

## Blocked endpoints (403 Forbidden)

These endpoints exist in the ISAPI spec but return 403 on this model:

- `/ISAPI/System/Video/inputs/channels` – channel list
- `/ISAPI/Smart/LineDetection/{ch}` – line crossing detection
- `/ISAPI/Smart/FieldDetection/{ch}` – intrusion detection
- `/ISAPI/Smart/AudioException/{ch}` – audio exception
- `/ISAPI/System/schedules` – recording schedules
- `/ISAPI/Recording/channels` – recording channel config

## Not supported (503)

- `/ISAPI/PTZCtrl/channels` – PTZ control (NVR has no PTZ)

## XML Namespaces

| Namespace | Used for |
|---|---|
| `http://www.isapi.org/ver20/XMLSchema` | Event triggers, motion/tamper detection |
| `http://www.std-cgi.com/ver20/XMLSchema` | Device info, image settings |

## PUT workflow

All writable endpoints follow the same pattern:
1. `GET` the current XML
2. Modify the relevant field(s) in the XML tree
3. `PUT` the full XML back (including unchanged fields)
4. Check response: `<statusCode>1</statusCode>` = OK

Content-Type header must be `application/xml`.
