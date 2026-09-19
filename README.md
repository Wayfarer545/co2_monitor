# ZyTemp CO2 Monitor

Home Assistant integration for USB CO₂ sensors built around the ZyAura ZG01 chip
(USB `04d9:a052`, "Holtek USB-zyTemp"). Sold under many names: Даджет MT8057 and
MT8057s, MasterKit, TFA Dostmann AIRCO2NTROL MINI, ZyAura ZGm053U, CO2Mini.

Reports carbon dioxide and temperature, and raises two configurable alarms.

## Why this exists

The sensor ships with a Windows-only program that draws a live graph and nothing
else — no history, no automations, no place in a smart home. This integration
reads the device directly so Home Assistant can record it and act on it.

## What you get

| Entity | Type | Notes |
|---|---|---|
| CO2 | sensor | ppm, `carbon_dioxide` device class |
| Temperature | sensor | °C, with a configurable offset |
| CO2 warning | binary_sensor | `problem`, on above the warning threshold |
| CO2 critical | binary_sensor | `problem`, on above the critical threshold |

Both alarms clear 50 ppm below their threshold, so a reading sitting on the line
does not flap your notifications. While CO₂ is unknown they report `unknown`
rather than "no alarm", which would be a quiet false negative.

## Requirements

- Linux. The device is read through `/dev/hidraw*`.
- No Python dependencies. Everything is done with the standard library, so
  there is no `hidapi` to compile on your ARM board.

### Permissions

Install a udev rule so the device is readable, then replug it:

```
# /etc/udev/rules.d/90-zytemp-co2.rules
SUBSYSTEMS=="usb", ATTRS{idVendor}=="04d9", ATTRS{idProduct}=="a052", \
    KERNEL=="hidraw*", GROUP="plugdev", MODE="0660", SYMLINK+="co2mini%n"
```

```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Home Assistant in a container

Docker takes a snapshot of `/dev` when the container is created, so a sensor
plugged in later is invisible inside it — and `privileged: true` does not change
that. Share the host's `/dev` instead:

```yaml
services:
  homeassistant:
    volumes:
      - /dev:/dev
```

Do not use `devices:` for this device: it pins one node at start-up and breaks as
soon as the sensor is replugged under a different `hidraw` number.

## Installation

HACS → three dots → **Custom repositories** → this repository, category
**Integration** → install → restart Home Assistant → **Add integration** →
*ZyTemp CO2 Monitor*. The sensor is found automatically; there is nothing to
enter.

## Configuration

**Settings → Devices & services → ZyTemp CO2 Monitor → Configure**

| Option | Default | Meaning |
|---|---|---|
| CO2 warning threshold | 1000 ppm | Warning alarm turns on above this |
| CO2 critical threshold | 1400 ppm | Critical alarm turns on above this |
| Temperature offset | 0 °C | Added to every reading |

The offset is there because the sensor sits inside the case next to the
electronics and typically reads 1–3 °C high.

Changing a threshold takes effect immediately and does not reopen the USB
device, so your automations see no gap.

## How it works

The device streams frames by itself once it has been handed a key over a HID
feature report; nothing polls it. Home Assistant watches the file descriptor and
decodes each 8-byte frame as it arrives.

Firmware older than 2.00 obfuscates its frames. The decoder detects which kind it
is talking to from the data and latches that decision, so both revisions work.

The `hidraw` node number changes between replugs, so the device is located afresh
on every open by scanning sysfs for its USB id — a replugged sensor is picked up
again on its own, without restarting Home Assistant.

## Troubleshooting

Download diagnostics from the integration page. They carry the current hidraw
path, whether the firmware was detected as obfuscated, frame counters, the age of
each reading and how many times the device had to be reopened.

## Credits

The ZG01 protocol was reverse engineered by the community — in particular Henryk
Plötz's write-up and the `dmage/co2mon`, `heinemml/CO2Meter` and
`vfilimonov/co2meter` projects.
