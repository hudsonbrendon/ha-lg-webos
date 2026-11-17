# Reverse engineering notes

How this integration knows what an LG webOS TV can do. Two sources, kept apart:
**firmware** (static, read from decrypted images) and **live** (answers from a
real TV). Nothing here is guessed from documentation.

## Sources

| | Model | Platform | webOS | Firmware | How |
|---|---|---|---|---|---|
| A | 60UN7310PSA | W20P (k6lp) | 5.6.2 | 04.64.00 | firmware decrypted + live |
| B | 50UT8050PSA | W24P (k8lpn2) | 10.3.x ("webOS 24") | 33.31.61 decrypted, 33.31.75 live | firmware decrypted + live |
| C | 32RL601CBSA | W23L | 8.5.0 ("webOS 23") | 13.50.44 | live only (LG publishes no firmware for it) |

Firmware: LG's public EPK files, decrypted with `epk2extract`, rootfs unpacked,
native binaries analysed with REA/Ghidra. Live: a paired SSAP client sending
read-only requests, plus reversible writes (each value read back and restored),
screen off/on, toast and a power cycle, on all three TVs.

## The control plane

- SSAP is a websocket on **3001 (TLS)**. Port 3000 is bound for localhost only
  in both firmwares (`xinetd`), so plain `ws://` from the LAN is not a thing.
- The gateway (`com.webos.service.secondscreen.gateway`) is plain Node.js. Its
  `interfaces/*.interface` files are the complete whitelist of `ssap://` URIs:
  **314 on A, 377 on B**. Anything else answers `404 no such service or method`.
- Each URI lists the permissions it needs. Permissions have an access type;
  everything except `SECURE` can be requested by an unsigned pairing manifest
  (what every third-party client sends). `SECURE` ones need a manifest signed
  by LG: `WRITE_SETTINGS`, `CONTROL_BLUETOOTH`, `ACCESS_STORAGE`,
  `READ_UPDATE_INFO`, `UPDATE_FROM_REMOTE_APP`, `SEARCH`, `CONTROL_VOICE`,
  `READ_LGE_SDX`. That is why `ssap://settings/setSystemSettings` answers
  `401 insufficient permissions` (live, A).
- A requires all of a method's permissions; B requires any one of them.

## What a paired client can read (live, A)

| URI | Gives |
|---|---|
| `settings/getSystemSettings` (subscribable) | only whitelisted keys, see below |
| `settings/getSystemSettingDesc` | allowed values of a few keys (sound output list) |
| `config/getConfigs` (subscribable) | any configd key: firmware, platform, serial, panel, ARC port, model flags |
| `com.webos.service.eim/getAllInputStatus` (subscribable) | per input: label, plug state, CEC name/vendor, detected device type |
| `com.webos.service.eim/getHDMISignalInfo` (subscribable) | per HDMI: 5 V and video signal |
| `com.webos.service.eim/getLastInput`, `getCurrentInput` | input ids |
| `com.webos.service.tvpower/power/getPowerState` (subscribable) | Active, Screen Off, Suspend... |
| `com.webos.service.tvpower/power/getPowerOnReason` (subscribable) | e.g. `wakeOnWiFi` |
| `com.webos.service.connectionmanager/getstatus` (subscribable) | wired/Wi-Fi state, SSID, IP, gateway, internet reachability |
| `com.webos.service.irdbmanager/getDevices` | devices set up for the universal remote |
| `com.webos.service.miracast/getDeviceInfo`, `wifi/p2p/getstate` | Wi-Fi Direct state |
| `com.webos.applicationManager/listApps`, `getAppInfo`, `searchApps` | installed apps |
| `tv/executeOneShot` | screenshot: 960x540 JPEG served at `https://tv:3001/resources/<hash>/capture.jpg` |
| `system/getCountryInfo` | country |

Refused with the standard manifest (live, A): `timer/getSettings`,
`tv/getContentState`, `user/getUserData`, `attachedstoragemanager/listDevices`
(their permissions are not in the manifest aiowebostv sends), and everything
`SECURE` (`update/getCurrentSWInformation`, Bluetooth, storage).
`com.webos.service.bosp/*` (picture mode list/current) is in the whitelist but
times out on A.

### Settings whitelist

`ssap://settings/getSystemSettings` only returns keys listed in the gateway's
`valid-settings.js`; a refused key is named in the error
(`Some keys are not allowed for the request. ( sharpness )`), one per error.

- **A (webOS 5.6)**, confirmed live: `picture`: backlight contrast brightness
  color · `sound`: soundOutput soundOutputDigital avSync eArcSupport ·
  `option`: audioGuidance livePlus country zipcode storeMode ·
  `network`: deviceName wolwowlOnOff bleAdvertisingOnOff · `other`:
  simplinkEnable.
- **B (webOS 24)**, firmware list confirmed live: all of the above plus ~60
  picture keys (pictureMode, energySaving, sharpness, tint, colorTemperature,
  dynamicContrast, peakBrightness, gamma, colorGamut, eyeComfortMode, white
  balance, CMS...), `sound.soundMode`, `general` (alwaysOn, homeAutoLaunch,
  homePromotion, tvOnScreen, lifeOnScreenMode), `option.quickStartMode`,
  `support.automaticUpdate`, `other.uhdDeepColorHDMI1-4`.
- **C (webOS 23)**, live: same set as B minus `eyeComfortMode`.

Two traps found live on B and C:

- A key that is whitelisted but absent on the model (`truMotionMode` on a 60 Hz
  panel) makes the **whole** request fail with a bare `returnValue: false`,
  naming nothing. Asked alone it answers `There is no matched result from DB`.
  The integration falls back to asking key by key.
- `blackLevel` is an object (one value per analog signal type), not a string.

`settings/getSystemSettingDesc` returns the values a model offers for a few
keys: sound output (all three), and picture mode on B, where the list follows
the current signal (HDR modes are hidden while SDR plays).

The integration asks for the union and drops what the TV refuses, so entities
follow the firmware of each TV.

## Writing settings: the alert trick, and its limits

`ssap://system.notifications/createAlert` is forwarded unmodified to
`luna://com.webos.notification/createAlert`. An alert may carry luna calls for
its buttons and for its close event; creating one and closing it fires the
close call. There is no return path.

REA on `notificationmgr` (A) shows the gate: every URI in the alert is checked
with `luna://com.webos.service.bus/isCallAllowed`, with the caller
(`com.webos.service.apiadapter.pub`, ACG group `public`) as requester. A refused
URI fails the alert at creation with
`Not allowed to call method specified in the uri`.

That gives a **side-effect-free capability probe**: put the URI only in a button
(never pressed), create the alert, close it. Live on A:

| Accepted | Refused |
|---|---|
| `settingsservice/setSystemSettings`, `getSystemSettings` | every `tvpower` method (reboot, screen saver, power off) |
| `service.config/getConfigs` | `service.config/setConfigs` |
| `applicationManager/launch` | `applicationManager/closeByAppId` |
| `notification/createToast`, `createAlert` | `surfacemanager/showInputPicker` |
| `service.audio/master/setVolume` | `networkinput/sendSpecialKey`, `ime/insertText` |
| `bluetooth2/adapter/setState` | `wifi/setstate`, `update/*`, `capture/*`, `devmode/*` |

B and C give the same answers as A (C additionally accepts
`tv.display/set3DOn`). So on webOS 5.6, 23 and 24 the well-known "reboot via
luna" and "screen saver via luna" calls do not work; settings writes do, for
any category and key. Verified with read-back on B and C: pictureMode,
energySaving, sharpness, eyeComfortMode, dynamicContrast, soundMode,
homePromotion, homeAutoLaunch, quickStartMode, automaticUpdate,
uhdDeepColorHDMI1. A picture-mode change pushes the new mode and then that
mode's own backlight/contrast/sharpness to subscribers. The integration probes
once per firmware version and only creates the buttons the TV accepts.

## Other findings

- **Pointer socket** (`network-input-service`, REA): message types `move`,
  `scroll`, `click`, `button`; 456 key names, including service-menu keys
  (`IN_START`, `EZ_ADJUST`...) that should not be sent casually.
- **Power**: a magic packet to either MAC wakes all three (6-16 s). With
  Quick Start+ on (B) the TV keeps 3001 open in standby and reports itself off
  through the power state; A and C close the socket.
- **webOS 24 only**, live on B: `tvpower/power2/getPowerState`,
  `applicationManager/getForegroundApps`, `panelcontroller/getPanelResolution`,
  `surfacemanager/getForegroundVideoWindow`, `getRecentsAppList`,
  `com.palm.systemservice/time/getSystemTime` all answer.
  `devicereset/requestReboot {"reason": "reset"}` returns success and does
  **not** restart the TV (the firmware describes it as "reboot for changing
  broadcast system").
- **Network standby** (B, Quick Start+ on): an SSAP connection opened while
  the TV was awake survives `Active Standby`; settings can be read and written
  through it and pushes keep coming, without waking the TV. A new connection
  attempted during standby is closed with websocket code 1008.
- **Channels**: a TV with no tuned channels reports a placeholder channel with
  an empty name; the channel list is empty, so there is nothing to subscribe to.
- **LG IP Control** (TCP 9761, `tvlink-network-proxy`): off by default, enabled
  by `option.enableIpControl`, AES key derived with PBKDF2-SHA256 (16384
  rounds) from `option.IPControlSecureKey`. Command table includes power, keys,
  input, picture mode. Not used here; wire framing was not decompiled.
- **Other listeners**: DIAL 36866/18181, SSDP 1900, HbbTV 8000/8001 (B).

## Extra permissions (live, A)

A client that re-registers with its existing client key and a manifest asking
for more non-SECURE permissions gets them **without a prompt**. With
`CONTROL_TIMER_INFO`, `READ_STORAGE_DEVICE_LIST`, `CHECK_BLUETOOTH_DEVICE`,
`READ_TV_CONTENT_STATE`, `CONTROL_RECORDING`, `CONTROL_USER_INFO` and
`CONTROL_INPUT_JOYSTICK` added, these started answering: `timer/getSettings`
(only as a subscription, a plain request never answers), `timer/setSettings`,
`attachedstoragemanager/listDevices`, `bluetooth/gap/isRadioOn`,
`tv/getContentState`, `utp.dvr/record/isRecording`, `user/getUserData` and
`networkinput/getGamepadInputSocket`. Timer writes were verified with
read-back.

The same silent grant happened on B (webOS 24) when the integration
reconnected with the extended manifest.

## HDMI-CEC (firmware + live, A)

The EIM service exposes `cec/setCECUniqueId {uniqueId, hdmiPort}` (choose the
target device) and `cec/sendKeyEvent {key}` (press a key on it). Both pass the
alert gate; `requestVendorCommand` (raw opcodes), `cec/powerOn` and
`cec/powerOff` do not. `key` is a webOS key code that `CKeyCode` (REA on
`/usr/sbin/eim`) maps to a CEC UI command: 101 entries, e.g. `0x1000053` →
Root Menu, `0x1202000` → Power, `0x1000004` → Select. Device unique ids come
from `getAllInputStatus` (`subList[].id == "SIMPLINK"`). Verified on a Fire TV
behind HDMI 3 with its own `dumpsys hdmi_control`: the key arrives as
`<User Control Pressed>` only when that device is the selected target.

## LG IP Control (firmware + live, A)

`tvlink-network-proxy` listens on TCP 9761 once `option.enableIpControl` is
`on`. It is started at boot, or on demand by any luna call to
`com.webos.tnp` (a D-Bus dynamic service): `luna://com.webos.tnp/com/palm/luna/private/ping`
passes the alert gate. The key comes from the setting
`option.IPControlSecureKey`, read when the service starts, so a key written
through the settings service works. Protocol, verified live: AES-128 key =
PBKDF2-HMAC-SHA256(key code, fixed salt, 16384 rounds, 16 bytes); request =
AES-ECB(IV) ‖ AES-CBC(IV, command + CR, PKCS#7-style padding); answer
decrypted the same way, ending in LF. Queries `CURRENT_VOL`, `MUTE_STATE`,
`CURRENT_APP`, `GET_MACADDRESS wired`, `GET_IPCONTROL_STATE` answer; writes
answer `OK`; a command missing its argument gets no answer at all. There is
no query for picture mode, so it cannot fill the webOS 5 read gap. The same
enable-by-settings path worked on B (webOS 24); the service needs a few
seconds after the ping before it answers.

## Writing while the TV is off (live, A)

Right after a wake-on-LAN the TV accepts alerts but drops their luna calls,
and it switches back to its last input a few seconds later. A write sent in
that window does nothing. Waiting for `Active` plus ~8 s works; the TV then
pushes the new value on the settings subscription, which is how the
integration confirms it. Picture settings belong to the current input and
picture mode, so while the TV changes input or powers down, the subscription
can push the values of another context.

## Not known

- `media.viewer/open` returned success on A but the result on screen was not
  conclusive, so media URLs are not offered as a feature.
- `com.webos.service.bosp/*` (picture mode list) times out on A and B.
- Live TV with tuned channels (none of the three has any).
- Whether a third party can obtain a signed manifest.
