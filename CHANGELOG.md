# Changelog

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
