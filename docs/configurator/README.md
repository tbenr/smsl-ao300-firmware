# Configurator and flasher: ideas

Status: ideas only, written 2026-09-30. Nothing here is decided or built.

## Goal

One tool for an AO300 owner who is not a developer:

1. They give it the vendor firmware (the tool ships none).
2. They pick and customize visually: theme, sizes, colours, alternative source names,
   fixes to include.
3. They flash the result to the amp.

Wanted: end to end in one place, no installation, cross-platform, ideally one artifact.

## What the repo gives us today

- **The build is pure Python stdlib**, about 4.8k lines: `tools/patch/asm51.py` (the
  assembler), `tools/patch/uikit.py`, `tools/patch/pfont.py`, `tools/build.py` and the
  `features/*/build_patch.py` files. No external tools.
- **Unpacking the vendor updater** (`tools/pe/stc_release.py`) needs `pefile` only to find
  one PE resource. The README also mentions that SMSL ships a plain Intel HEX of the
  image; no parser for that exists yet.
- **Flashing** (`tools/flash/flash_ao300.py`) uses stcgal's `Stc8dProtocol` as a library
  over a plain UART: 2400 baud handshake, 115200 transfer, even parity, no DTR/RTS.
  All flashing goes through the STC mask-ROM ISP; there is no vendor bootloader.
- **The amp has no onboard USB-UART bridge.** The user needs a 3.3 V USB-serial adapter
  (a CH340 was used) on the internal 4-pin header.
- **A browser configurator exists in part**: `features/house-numerals/sizing.html` with
  `tools/fonts/glyphs.js` previews pixel-exact and writes `layout.json`.
  `features/ui-theme/ui_themes.html` mocks six themes; only house-numerals is built.
- **The emulator can render the LCD**: `LCD.save_png` in `tools/emu/emu8051.py`, and
  `Amp` in `tools/emu/ao300.py` boots a full image. The fast core is C
  (`tools/emu/core8051.c`), compiled at runtime and loaded with ctypes.
- **Almost nothing is parametrized.** Only the home layout comes from a file
  (`layout.json`). Colours, the volume-page layout and `VERSION_TEXT` are module
  constants. Images are pinned by `BASE_SHA` and `KNOWN_IMAGES`.
- **There is no source-rename feature.** `uikit.INPUT_NAMES` lists the stock strings and
  house-numerals asserts and renders them.

## Packaging options

| Option | Reuses the Python build | Install | Artifacts | Main problem |
|---|---|---|---|---|
| Web page: Pyodide + Web Serial | Yes, unchanged | None | One URL, or one offline HTML | Chrome/Edge only; the flasher must be ported to JS |
| PyInstaller single file + local web UI | Yes, including stcgal as proven on the amp | None, but unsigned-binary warnings | 4–5 binaries | Gatekeeper and SmartScreen warnings, antivirus false positives, a CI matrix |
| Go monolith | No: full rewrite | None, same warnings | 4–5 binaries | Two implementations while themes still change; the emu tests drive the Python builders |
| Electron | No: rewrite in JS or bundle Python | None, same warnings | 4–5 binaries of 100 MB+ | The costs of both of the above |

A middle option: the web configurator and in-browser build, with flashing left to the
existing Python script or a small PyInstaller binary. It avoids the Web Serial risk but
is not zero-install.

### Favoured: a static web page

- The build runs in the browser as-is under Pyodide (CPython compiled to WASM), so the
  tested Python stays the only implementation.
- The firmware never leaves the user's machine: they drop in the vendor `.exe`, and it is
  unpacked, sha-checked and patched client-side. This fits "firmware never goes into git".
- The preview can be the real firmware: `core8051.c` compiled to WASM, booting the built
  image and drawing the emulated LCD on a canvas.
- Nothing to sign or notarize; one artifact covers Windows, macOS, Linux and ChromeOS.

Costs:

- Web Serial works in Chrome and Edge on desktop, not in Firefox or Safari.
- The flasher is a port, not a reuse. No browser STC flasher turned up in a search, so
  `Stc8dProtocol` and the `check_chip` safety checks would be rewritten in JS.
- "Zero install" has a hardware limit on every option: the user still opens the amp,
  connects an adapter, and on Windows may need the CH340 driver.

## Is Web Serial reliable enough to flash?

The transport is. This chip over it is untested.

Why the transport is fine:

- Chrome hands bytes to the same OS serial driver pyserial uses. Bit timing on the wire
  comes from the adapter's UART, not from JavaScript.
- Production flashers use it (Espressif's esptool-js, ESPHome and similar).
- The STC protocol detects corruption: a 16-bit checksum and even parity on every packet,
  and each flash block is acknowledged before the next one is sent.
- The host drives the exchange. A slow browser makes the flash slower, not wrong.

Risks specific to this chip:

- **Baud switch.** Web Serial cannot change baud on an open port; it must close and
  reopen between the 2400 handshake and the 115200 transfer. From a read of stcgal's
  source (to confirm against the file itself), the chip acknowledges the switch at 2400
  and the host then speaks first with the "prepare" packet, so a reopen only delays the
  host. How long the bootloader waits idle is unknown.
- **Sync and calibration pulses.** The host sends `0x7F`, then `0xFE`, about every 30 ms
  until the chip answers. Background tabs throttle timers, so the flasher should run in
  a Worker and the tab should stay in front.
- **Interrupted flash.** A closed tab, a sleeping laptop or a pulled cable leaves the amp
  without firmware, as with the Python flasher. The ISP is in ROM: a cold power-up and a
  second flash recover it.
- **Option bytes** are the only path to a real brick. The port must refuse any chip whose
  option bytes differ from `FF BF BC F7 F4` and write the same bytes back, as
  `check_chip` does.

How to make a port trustworthy:

- **Replay test.** Record a full stcgal session with `-D` and make the JS flasher
  reproduce the host side byte for byte against a mock port.
- **Stepwise on the amp**, like the existing subcommands: `identify` (writes nothing),
  then `dryrun` (handshake and baud switch, disconnect before erase), then a real flash.

## Mobile

| Step | Android (Chrome) | iPhone / iPad |
|---|---|---|
| Configure, build, preview | Yes | Yes |
| Flash | Possible, with extra work | No |

- Configure and build only need a responsive layout; Pyodide and WASM run in mobile
  Chrome and Safari.
- Android, native Web Serial: added in Chrome 148 (April 2026), but USB serial ports work
  only on a limited set of devices so far.
- Android, WebUSB: the dependable route. The page drives the CH340 itself through a
  USB-OTG cable. The JS CH340 drivers found only do 8N1, so we would write a small one
  with even parity and 2400 baud. Only the adapter chips we implement would work. Baud is
  a plain control request there, so no close-and-reopen.
- iOS: no browser has Web Serial or WebUSB. A user could configure and build, save the
  image, and flash from a computer or an Android phone.

Consequence: put the flasher behind a small transport interface. Web Serial on desktop
first; a WebUSB CH340 transport can follow. The protocol code and the replay test are
shared.

## Needed whatever the packaging

- **Config as input.** The build becomes a function of a config (theme, sizes, colours,
  names, fixes) instead of module constants pinned by `BASE_SHA` and `KNOWN_IMAGES`.
- **Source renaming** is a new firmware feature, not only UI. Flash is tight
  (house-numerals has about 2.2 KB left), and its glyph sets derive from the stock names.
- **A safety story for unpinned images.** Every user config gives a sha no test has seen.
  Ideas: constrain each parameter to a validated range, and run an emulator smoke test on
  the built image (boot, key sweep, recovery path intact) before offering to flash.
- **More than one theme.** Today a "theme selection" has one entry.

## Open questions

- Does the STC8 bootloader tolerate the close-and-reopen gap? Needs the spike on the amp.
- Could the handshake run at the transfer baud, so no switch is needed at all?
- How large is the config space we can honestly call tested?
- Hosted page, a single offline HTML file, or both? Pyodide adds roughly 10 MB.
- Is the vendor `.exe` the only input, or also the Intel HEX?
- Windows and the CH340 driver: what does a first-time user actually hit?

## Possible order of work

1. Spike: JS `identify` and `dryrun` over Web Serial on the amp.
2. Make the build a function of a config; keep the pinned images as named presets.
3. Run the build under Pyodide; unpack the vendor updater in the browser.
4. Live preview from the emulator core compiled to WASM.
5. JS flasher with the replay test, then a real flash on the amp.
6. Later: WebUSB CH340 transport for Android; source renaming; more themes.

## Sources

- stcgal: https://github.com/grigorig/stcgal
- Chrome, Web Serial guide: https://developer.chrome.com/docs/capabilities/serial
- MDN, `SerialPort.open()`: https://developer.mozilla.org/en-US/docs/Web/API/SerialPort/open
- Web Serial reopen pattern: https://github.com/jasiek/webchirp/pull/129
- Chrome 148 Beta for Android adds Web Serial:
  https://www.notebookcheck.net/Chrome-148-Beta-for-Android-adds-Web-Serial-SharedWorker-support.1269721.0.html
- blink-dev PSA, Web Serial on Android:
  https://groups.google.com/a/chromium.org/g/blink-dev/c/yGhvQ6mEmcY
- JS WebUSB serial adapters and their gaps: https://github.com/jasiek/webchirp/issues/130
- Google's WebUSB serial polyfill (CDC-ACM only): https://github.com/google/web-serial-polyfill
