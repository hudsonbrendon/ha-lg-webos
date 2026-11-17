# Changelog

## 0.2.1 - 2026-11-16

- Queued writes wait for the TV to settle after waking, are confirmed against
  the TV's own pushes and sent again if they did not take.
- The luna probe is asked again when the TV answers with something other than
  a clear refusal (a TV still waking up rejects every alert).
- The options accept a key code already generated on the TV menu.
- Uses the device's single config entry on Home Assistant 2026.11.

## 0.2.0 - 2026-11-16

- Pairs with extra permissions (granted silently): on/off timers as switches,
  times and a power-on volume; USB storage sensor; Bluetooth sensor.
- Setting changes made while the TV is off are queued and applied when it
  connects again; settings entities stay usable while it is off.
- Write-only picture mode, energy saving and sound mode on webOS 5, which
  cannot read them.
- HDMI-CEC: power button per device on an input and a `cec_key` action.
- LG IP Control option: enables the TV's TCP 9761 service with a generated
  key; remote lock switch, aspect ratio select and an `ip_control` action.

## 0.1.1 - 2026-11-16

- Require `aiowebostv>=1.0.1` instead of pinning it: Home Assistant ships the
  same library and has to be free to update it.

## 0.1.0 - 2026-11-16

- First release: media player with built-in Wake-on-LAN, remote, screenshot
  image, picture numbers, setting switches, sound output select, per-input
  device sensors and plug sensors, toast notify, seven actions.
- Entities follow what each firmware lets a client read: 35 on webOS 5.6, 57 on
  webOS 23, 60 on webOS 24 (picture mode, energy saving, sound mode...).
- Sensors keep their last value while the TV is off (cached on disk); settings
  stay usable on TVs that keep the network up in standby.
- Imports the pairing of the built-in `webostv` integration (no prompt on the
  TV, works with the TV off).
