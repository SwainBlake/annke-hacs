# Annke – Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![HA version](https://img.shields.io/badge/Home%20Assistant-2024.1%2B-blue.svg)](https://www.home-assistant.io/)

A Home Assistant custom integration for **Annke NVR systems and IP cameras** — and any compatible **Hikvision-based device** — via the ISAPI protocol.

## Features

### Real-time events (no polling!)
The integration connects to the ISAPI alert stream and pushes events to HA with sub-second latency:

| Entity | Trigger |
|---|---|
| `binary_sensor` Motion | Motion detection active/inactive |
| `binary_sensor` Tamper | Camera tampering detected |
| `binary_sensor` Line Crossing | AI cameras only |
| `binary_sensor` Intrusion | AI cameras only |
| `binary_sensor` Face Detection | AI cameras only |
| `binary_sensor` Audio Exception | AI cameras only |
| `binary_sensor` HDD Full / HDD Error | NVR-level storage events |

### Per-channel controls (×N channels, auto-discovered)

**Switches**
- Motion Detection on/off
- Tamper Detection on/off
- Privacy Mask on/off
- Push Notifications (motion)
- Email Notifications (motion)
- Tamper Push Notifications
- Image Flip
- WDR (Wide Dynamic Range)
- OSD Date/Time overlay
- OSD Channel Name overlay
- Audio
- Smart Codec (H.265+)
- Line Crossing / Intrusion / Face / Audio Exception Detection *(AI cameras only, auto-detected)*

**Numbers (sliders)**
- Motion Sensitivity (0–100)
- WDR Level (0–100)
- Brightness / Contrast / Saturation / Sharpness (0–100)
- Max Bitrate (32–16384 kbps)

**Selects**
- IR Cut Filter (auto / day / night)
- Supplement Light (IR / white light / off)
- Video Codec (H.264 / H.265)
- Quality Mode (VBR / CBR)

**Camera**
- JPEG snapshot on demand
- RTSP stream URLs as entity attribute (for use with Generic Camera or go2rtc)

### NVR system monitoring

| Entity | Value |
|---|---|
| `sensor` CPU Usage | % |
| `sensor` RAM Used / Free | MB |
| `sensor` Uptime | seconds |
| `sensor` HDD Capacity / Free / Used | MB / % |
| `sensor` HDD Status | ok / error / full |
| `sensor` Active RTSP Sessions | count |
| `sensor` IP Address | with RTSP URL template |
| `sensor` MAC Address | — |

### Master switches (NVR device)
- All Push Notifications (all channels at once)
- All Motion Detection (all channels at once)

## Compatibility

**Tested on:**
- Annke N98PBK (8-channel PoE NVR, firmware V4.75.000)

**Should work with:**
- All Annke NVR models
- All Annke IP cameras (direct connection, no NVR required)
- Any Hikvision-compatible device supporting ISAPI

**Smart detection features** (line crossing, intrusion, face detection, audio exception) are automatically enabled when the connected camera supports them. Basic cameras (without AI) will not show these entities.

## Installation

### HACS (recommended)

1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/SwainBlake/annke-hacs` as **Integration**
3. Install "Annke" and restart Home Assistant

### Manual

Copy `custom_components/annke/` into your HA `config/custom_components/` directory and restart.

## Configuration

**Settings → Integrations → Add Integration → Annke**

Enter:
- **IP Address** of your NVR or camera (e.g. `192.168.1.100`)
- **Username** (default: `admin`)
- **Password**

The integration will auto-discover all channels and capabilities. Entities that are not supported by your hardware will not appear.

## RTSP streams

The integration provides snapshot images via the camera entity. For live streams, use the RTSP URLs shown in the camera entity attributes with HA's [Generic Camera](https://www.home-assistant.io/integrations/generic/) or [go2rtc](https://github.com/AlexxIT/go2rtc):

```
Main stream (full res): rtsp://admin:PASSWORD@NVR_IP:554/Streaming/Channels/101
Sub stream (low res):   rtsp://admin:PASSWORD@NVR_IP:554/Streaming/Channels/102
Channel 2 main:         rtsp://admin:PASSWORD@NVR_IP:554/Streaming/Channels/201
```

## Automation examples

### Disable push notifications when home
```yaml
automation:
  - alias: "NVR – notifications off when home"
    trigger:
      platform: state
      entity_id: group.family
      to: "home"
    action:
      service: switch.turn_off
      target:
        entity_id: switch.annke_all_push_notifications

  - alias: "NVR – notifications on when away"
    trigger:
      platform: state
      entity_id: group.family
      to: "not_home"
    action:
      service: switch.turn_on
      target:
        entity_id: switch.annke_all_push_notifications
```

### Trigger light on motion (real-time, no delay)
```yaml
automation:
  - alias: "Gate camera motion → outside light"
    trigger:
      platform: state
      entity_id: binary_sensor.annke_ch4_motion
      to: "on"
    action:
      service: light.turn_on
      target:
        entity_id: light.outside
```

## Known limitations

- Smart analytics endpoints (line crossing, field detection, face detection) return 403 on cameras without AI hardware — no entities are created for unsupported features
- Recording schedule configuration not accessible via ISAPI on tested models
- PTZ control not implemented
- Only first HDD is monitored on multi-disk NVRs

## License

MIT

## Contributing

Issues and PRs welcome at [github.com/SwainBlake/annke-hacs](https://github.com/SwainBlake/annke-hacs).

Especially useful: test reports from other Annke/Hikvision models, and reports on which smart detection endpoints work on which camera models.
