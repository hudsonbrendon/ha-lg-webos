<p align="center"><img src="assets/lg.png" alt="LG" height="90"></p>

# LG webOS for Home Assistant

[![Tests](https://github.com/hudsonbrendon/ha-lg-webos/actions/workflows/tests.yml/badge.svg)](https://github.com/hudsonbrendon/ha-lg-webos/actions/workflows/tests.yml)
[![hassfest](https://github.com/hudsonbrendon/ha-lg-webos/actions/workflows/hassfest.yml/badge.svg)](https://github.com/hudsonbrendon/ha-lg-webos/actions/workflows/hassfest.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

Local, push-based integration for LG webOS TVs that exposes what the built-in
**LG webOS TV** (`webostv`) integration leaves out. It runs next to the built-in
one and can reuse its pairing, so nothing has to be accepted on the TV again.

Everything comes from probing real TVs over SSAP (the websocket API on ports
3000/3001). What was found, and what the TV refuses, is in
[REVERSE_ENGINEERING.md](REVERSE_ENGINEERING.md).

## What it adds over the built-in integration

| | Built-in `webostv` | This integration |
|---|---|---|
| Turn on | needs an automation with a Wake-on-LAN action | built in (MACs learned from the TV) |
| Remote entity | no (one `button` action) | yes, apps as activities |
| Screenshot of what is on screen | no | `image` entity + `screenshot` action |
| Picture settings | no | backlight, contrast, brightness, color as numbers, live |
| System settings | no | SIMPLINK, Wake on LAN, Live Plus, audio guidance, eARC, Bluetooth advertising as switches; any other key through `set_system_settings` |
| What is on each HDMI | no | sensor per input (label, CEC name, detected type) and plug sensor per HDMI |
| Sound output | attribute + action | select entity and media player sound mode |
| Power state, input, app, channel, firmware, webOS version | attributes at most | sensors |
| Media browser | no | apps, inputs and channels with icons |
| Notify | legacy service | notify entity |
| Internal (luna) calls | no | `luna` action, gated by what the firmware accepts |
| On/off timers | no | switches, times and power-on volume |
| Devices on HDMI | no | power button per CEC device, `cec_key` action |
| LG IP Control (TCP 9761) | no | turned on from the options: remote lock, aspect ratio, `ip_control` action |
| Changes while the TV is off | rejected | queued and applied when it wakes |
| Settings webOS 5 cannot read | no | picture mode, energy saving and sound mode as write-only selects |
| Setup | pairing prompt on the TV | imports the built-in pairing, even with the TV off |

## Tested on

All three verified live through Home Assistant (every write read back and
restored, power cycle included):

| Model | webOS | Firmware | Entities |
|---|---|---|---|
| 60UN7310PSA | 5.6.2 | 04.64.00 | 35 |
| 32RL601CBSA | 8.5.0 (webOS 23) | 13.50.44 | 57 |
| 50UT8050PSA | 10.3.2 (webOS 24) | 33.31.75 | 60 |

Newer webOS lets a client read far more settings, so the entity set grows with
the firmware. Other models set up the same way.

## Installation

HACS / Marketplace → custom repository `hudsonbrendon/ha-lg-webos` (integration),
install, restart Home Assistant.

## Setup

Settings → Devices & services → Add integration → **LG webOS**.

- **Import from the built-in integration**: pick the TVs; the pairing key is
  reused. The built-in integration keeps working.
- **Enter the address**: the TV has to be on; accept the prompt on screen.

TVs are also discovered over SSDP.

## Entities

- `media_player`: power (Wake-on-LAN), volume, mute, source (apps and inputs),
  sound mode (sound output), play/pause/stop, channel up/down on live TV, media
  browser, `play_media` with `channel`, `app`, `input` or `url`.
- `remote`: `send_command` with the remote key names (`HOME`, `BACK`, `ENTER`,
  `UP`, `MENU`, `INFO`, digits...), activities are the installed apps.
- `image` Screen: screenshot taken on demand (protected video comes out black).
- `switch` Screen: panel off with the TV still running.
- `number`: backlight, contrast, brightness, color; on webOS 23+ also
  sharpness, tint, color temperature.
- `switch`: SIMPLINK (HDMI-CEC), Wake on LAN, Live Plus, audio guidance, eARC,
  Bluetooth advertising, AV sync; on webOS 23+ also Quick Start+, eye comfort,
  motion eye care, Real Cinema, always on, home at power on, home promotions,
  automatic updates, Deep Color per HDMI.
- `select`: sound output, digital sound output; on webOS 23+ also picture mode,
  energy saving, sound mode, dynamic contrast, peak brightness, color gamut,
  gamma, super resolution, noise reduction, smooth gradation, HDR tone mapping,
  screen at power on, always ready.
- `sensor`: power state, power-on reason, app, input, channel, network, IP
  address, firmware, webOS version, and one per input with the device on it.
- `time`: on and off timer times; with `switch` on/off timer and `number`
  power-on volume.
- `sensor` USB storage (count, names), `binary_sensor` Bluetooth radio.
- `button`: power key of each device the TV sees on HDMI-CEC (toggles it).
- With LG IP Control on: `switch` remote lock and `select` aspect ratio
  (write only; the TV cannot report them).
- `binary_sensor`: internet, and one per HDMI input (on while a powered device
  is plugged in, with a `signal` attribute).
- `button`: restart, screen saver, input picker, only on firmware that accepts
  those luna calls. None of the three tested TVs does, so none shows up there.
- `notify`: toast on screen.

## Actions

| Action | What it does |
|---|---|
| `lg_webos.button` | press a remote key |
| `lg_webos.command` | any SSAP request, returns the answer |
| `lg_webos.luna` | internal luna call through a system alert (no answer) |
| `lg_webos.set_system_settings` | write settings of any category, e.g. `picture` / `pictureMode: cinema` |
| `lg_webos.launch_app` | open an app, optionally on a content id |
| `lg_webos.type_text` | type into the focused text field |
| `lg_webos.screenshot` | save the screen as a JPEG file |
| `lg_webos.cec_key` | press a key on the device behind an HDMI input (HDMI-CEC) |
| `lg_webos.ip_control` | send a raw LG IP Control command, returns the answer |

## Options

- **LG IP Control**: turns on the TV's IP Control service with a key the
  integration generates and keeps. It stays on across TV restarts. If a key
  was already generated on the TV menu, the new one only applies after the TV
  restarts.

## Extra permissions

The integration pairs with a few permissions the built-in one does not ask
for (timers, USB storage, Bluetooth, content state, recording state). The TV
grants them silently when the existing key re-registers, so nothing has to be
accepted on screen.

## Known limitations

- The TV only lets a paired client **read** a whitelist of settings, short on
  webOS 5 and long on webOS 23+. What cannot be read is not an entity, but can
  still be written with `set_system_settings`.
- No remote restart: the luna power calls are refused on webOS 5.6, 23 and 24,
  and `devicereset/requestReboot` answers success without restarting.
- With the TV off, read-only entities (sensors, plug sensors, internet) keep
  the last value the TV reported, also across Home Assistant restarts.
  Settings (numbers, selects, setting switches) need a live socket: TVs with
  Quick Start+ that keep the network up in standby (verified on webOS 24) can
  still be read and changed while off; the others show them as unavailable.
  Screen, screenshot, toast and sound output need the TV awake.
- A TV in network standby refuses new connections: if Home Assistant restarts
  while it sleeps, the settings come back when the TV is next turned on.
- Settings changed while the TV is off are kept and sent when Home Assistant
  next connects; for TVs that keep the network up in standby they apply right
  away.
- CEC needs SIMPLINK on, and the device has to answer on CEC. The power key
  toggles, so pressing it on a device that is already off turns it on.
- Write-only selects show the last value sent from Home Assistant; a change
  made with the remote is not seen.
- Wake-on-LAN needs "Turn on via Wi-Fi/LAN" enabled on the TV (the Wake on LAN
  switch shows it).

## Development

```sh
uv venv --python 3.14 .venv && uv pip install -p .venv -r requirements_test.txt
.venv/bin/ruff check . && .venv/bin/pytest
```

## License

MIT
