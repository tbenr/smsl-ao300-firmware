# SMSL AO300 firmware work

Reverse engineering of the SMSL AO300 amplifier's control-MCU firmware (STC8C2K64S2,
8051 core) and custom features built on top of it.

## Layout

Firmware is not in this repository. The vendor updater, the extracted and patched images
(`*.bin`, `*.exe`, `*.hex`), the stock disassembly `flash.asm`, the Ghidra project and
all `build/` outputs are ignored by git. The "Workflow" section below recreates them.
Entries marked * in this tree exist only locally.

```
original/                       * vendor files and what was extracted from them
  SMSL_AO300_UPDATE_VER0A5_EN.exe * vendor updater (STC-ISP "release project", v0A5, Dec 2023)
  extracted/container.bin         * decrypted record container from the updater
  extracted/flash.bin             * stock firmware image (37799 bytes, loads at 0x0000)
  extracted/flash.asm             * disassembly of the stock image (d51.py output)

tools/
  pe/stc_release.py               unpack / repack / rebuild the updater's firmware container
  disasm/d51.py                   small recursive 8051 disassembler
  disasm/SmslAo300Labels.java     Ghidra script that names routines, globals and tables
  flash/flash_ao300.py            guarded stcgal-based flasher for macOS/Linux (see below)
  flash/ser2net/                  ser2net in Docker: forward a remote adapter as rfc2217://
  emu/emu8051.py                  full 8051 emulator with STC8 clock counts and an ST7789
                                  model of the LCD bus (renders the screen to PNG); the
                                  Python reference implementation
  emu/core8051.c, emu/cemu8051.py the same emulator in C, loaded through ctypes and
                                  compiled on first use; what Emu8051() runs, ~100x faster
  emu/test_core.py                differential test: C core against the Python reference
  build.py                        builds every feature image in dependency order and checks
                                  them; --graph prints the feature tree (see "Feature graph")
  run_tests.py                    builds, then runs every features/*/emu_test.py, the UI
                                  kit's test and the installer's test in parallel
  release.py                      packs the user-facing bundle, dist/ao300-custom-*.zip, and
                                  self-tests it (see "Release for users")
  installer/                      the bundle's wizard (ao300_installer.py: stock check, theme
                                  and config questions, build, port detection, flash through
                                  flash_ao300.py), install.sh, the bundle's README and tests
  emu/ao300.py                    harness: boot the whole firmware, press remote keys, log
                                  audio-chip writes and pins per 10 ms tick
  emu/i2c.py                      I2C slave model for the harness: the chips answer, and
                                  every transfer is logged with its call site
  emu/bus_trace.py                runs stock through every input and setting and prints the
                                  registers and pins it touches (source of docs/bus-map.md)
  emu/panel_video.py              60 fps video of what the glass shows: samples panel memory
                                  line by line at the 60 Hz refresh (needs ffmpeg)
  emu/uitest.py                   shared helpers for UI tests: screen access, the stock
                                  glyph painters, uk_paint calls, the firmware's strings
  patch/asm51.py                  label-resolving 8051 assembler used by the build scripts
  patch/uikit.py                  shared building blocks for UI themes (see "UI themes")
  patch/features.py               the feature graph: each feature's BASE and INCLUDES
  patch/uikit_test.py             the kit's own emulator tests, on fast-lcd + the kit
  patch/pfont.py                  proportional fonts for uk_text, packed from tools/fonts/raster
  fonts/                          the UI mock's typefaces as glyph coverage, the font bench
                                  server and the shared rasteriser glyphs.js (see its README)

features/
  status-line-flicker/            analysis of the "flickering C" display bug (no build yet)
    NOTES.md, evidence/           findings, ruled-out causes, fix candidate, video crops
  direct-select/                  direct input selection and idempotent power over IR: a fix,
                                  included by the images meant for the amp; standalone on
                                  stock (see its README)
    direct_select.py              the fix: HOOK and emit(a), for any build pipeline
    build_patch.py                the standalone image, build/flash_patched.bin
    direct_select.asm             generated listing of the routine placed at 0x9400
    emu_test.py                   emulator test of the standalone image, or of the fix in
                                  any image that includes it (--in)
    build/flash_patched.bin     * patched firmware image
    build/SMSL_AO300_UPDATE_VER0A5_EN_directselect.exe * rebuilt updater carrying it
  ui-theme/                       design stage: visual themes for the home and volume
                                  screens; two of them are built (house-numerals, phosphor-panel)
    ui_themes.html                interactive theme designs and the stock screen map
  fast-lcd/                       the stock UI through the tuned pixel path, on top of
                                  stock; emulator-verified, see its README
    build_patch.py, emu_test.py   build build/flash_fastlcd.bin, lockstep UI tour vs stock
  phosphor-panel/                 Phosphor Panel (study 2 of the mock: a VFD look) home and
                                  volume page, on top of fast-lcd, built with tools/patch/uikit.py;
                                  pp1 on the amp since 2026-10-10 (works), pp2 fixes the dot
                                  matrix's O and C edges; see its README
    build_patch.py, emu_test.py   build build/flash_phosphor_panel.bin (the dot-matrix name,
                                   the row of lamps, the seven-segment cells with afterglow,
                                   the bar, the sequenced fades driven by a per-tick level
                                   engine), home, page and engine models, lockstep tour,
                                   keys during the transitions, INT1 sweep, 256-command sweep
    phosphor_panel.asm            generated listing
  house-numerals/                 House Numerals home and volume page, on top of fast-lcd,
                                  built with tools/patch/uikit.py; hn10 to hn12 tried on the amp
                                  on 2026-09-30, hn13 and the pop fixes' builds (hn14, hn15)
                                  on 2026-10-02, hn16 the same day; see its README
    build_patch.py, emu_test.py   build build/flash_house_numerals.bin (hn10: the mock's home
                                   and volume page in its own typefaces, non-blocking wipes
                                   with the mock's cubic ease, the number roll and the line's spring), home and
                                   page models, lockstep UI tour, keys during wipes and on the
                                   page, INT1 sweep, 256-command sweep vs fast-lcd plus the
                                   same fixes (the reference the test builds)
    layout.json, sizing.html      the home layout the build reads, and the page that edits it
                                   (preview exact to the firmware; served by tools/fonts/rasterize.py)
    house_numerals.asm            annotated listing of the patch code at 0x9800
  strings/                        stock texts corrected in place ("Disconnected" for ARC's
                                  "No Connected"), includable like a fix; see its README
  fix-auto-off/                   stock-bug fix, ported from the AO300 PRO V1.2: Dimmer Auto
                                  OFF also times out after a cold power-up. Standalone on
                                  stock; other builds include it (see its README)
    fix_auto_off.py               the fix: HOOK and emit(a), for any build pipeline
    build_patch.py, emu_test.py   build build/flash_fixautooff.bin, hook test, 256-command
                                   sweep, cold power-up / standby scenarios vs stock
    fix_auto_off.asm              generated listing
  start-volume/                   the volume at power-on capped at limits set at build time,
                                  one for speakers and one for headphones. Standalone on
                                  stock; house-numerals includes it (see its README)
    start_volume.py               the config (SPEAKER_LIMIT, HEADPHONE_LIMIT) and the fix:
                                   HOOK and emit(a)
    build_patch.py, emu_test.py   build build/flash_startvolume.bin; hook and config tests,
                                   256-command sweep, cold power-up / standby scenarios vs
                                   stock on an EEPROM model
    start_volume.asm              generated listing
  fix-volume-pop/                 stock-bug fix: a volume key on Optical or Coaxial without
                                  a signal no longer moves the mute pins or opens the
                                  NJW1194 (the pop on the first key). Standalone on stock;
                                  house-numerals includes it (see its README)
    fix_volume_pop.py             the fix: HOOK, PATCHES and emit(a)
    build_patch.py, emu_test.py   build build/flash_fixvolumepop.bin; the four handlers
                                   against stock, 256-command sweep through dispatch_key,
                                   no-signal / signal-drop / mute-key scenarios vs stock
    fix_volume_pop.asm            generated listing
  fix-menu-input/                 stock-bug fix: an input chosen in the menu is switched as
                                  the Source key switches it, without stock's 3 s supply
                                  cycle on P4.0 and second chip setup (a pop). Standalone
                                  on stock; house-numerals includes it (see its README)
    fix_menu_input.py             the fix: HOOK and emit(a)
    build_patch.py, emu_test.py   build build/flash_fixmenuinput.bin; hook test, 256-command
                                   and 256-key sweeps, all 30 input pairs through the menu
                                   against stock and against the Source key
    fix_menu_input.asm            generated listing
  auto-switch/                    stage 1 of the auto-switch (docs/probing-plan.md): to HDMI
                                  when the TV comes on, from any input, only while the
                                  selected input is silent (Bluetooth sensed, not enabled). A
                                  fix on stock with the six fixes; as1 flashed and the TV wake
                                  confirmed on 2026-10-05 (see its README)
    auto_switch.py                the fix: ENABLED, HOLD, HOOK and emit(a)
    build_patch.py, emu_test.py   build build/flash_autoswitch.bin; the tick hook per phase,
                                   256-command sweep vs stock + the same fixes, whole-firmware
                                   scenarios against direct-select's switches
    auto_switch.asm               generated listing
  probe/                          layer 2 of docs/probing-plan.md: FN on the home page sends
                                  a read-only register dump (I2C address scan, expander,
                                  receiver and clock-generator registers, ports, RAM) over the
                                  programming header at 115200 baud. Standalone on stock with
                                  the six fixes; pr1 flashed 2026-10-05, pr2 (FN) emulator-
                                  verified (see its README)
    probe.py                      the fix: HOOK and emit(a)
    build_patch.py, emu_test.py   build build/flash_probe.bin; hook test on the I2C model,
                                   256-command sweep vs stock + the same fixes, cold power-up
                                   scenario with the dump, standby and a menu
    probe.asm                     generated listing

ghidraPRG/                    * Ghidra project (import original/extracted/flash.bin as
                                8051:BE:16:default, block CODE at 0)
```

## Requirements

- Python 3.8 or newer.
- `pefile` for the container tools (`tools/pe/stc_release.py`).
- `stcgal` 1.10 or newer for the flasher (`tools/flash/flash_ao300.py`); it pulls in
  `pyserial`. A USB-to-serial adapter (3.3 V logic) on the amp's 4-pin header.
- The disassembler, the patch builder and the emulator test need only the standard
  library, plus a C compiler (`cc`; on macOS the Xcode command-line tools) for the
  emulator's C core. Without one the emulator falls back to the Python reference,
  about 100 times slower.
- Optional: Ghidra (with a JDK 17 or newer) for `tools/disasm/SmslAo300Labels.java`.

Use a virtual environment so the tools don't touch the system Python. From the project
root:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` pins stcgal and pefile (pyserial comes with stcgal); the release bundle
installs the same file.

Activate it (`source .venv/bin/activate`) in every new shell before running the commands
below; `python3` then resolves to the venv's interpreter. `deactivate` leaves it. The
`.venv` folder is local and can be deleted and recreated at any time.

Do not run the tools with `sudo`: it resets the environment, so `python3` becomes the
system interpreter and the venv's packages are missing. On macOS the serial device is
world-writable and no elevation is needed. On Linux, add yourself to the serial group
once instead (`sudo usermod -aG dialout "$USER"`, `uucp` on Arch) and log in again. If
elevation is ever unavoidable, call the venv interpreter by path, which works without
activation: `sudo .venv/bin/python tools/flash/flash_ao300.py ...`.

The rebuilt vendor updater (`.exe`) needs Windows, real or in a VM with the serial
adapter passed through; nothing else here does.

## Workflow

Download the vendor updater `SMSL_AO300_UPDATE_VER0A5_EN.exe` (firmware v1.4) from
SMSL's support pages and put it in `original/`. Then extract the stock firmware:

```bash
python3 tools/pe/stc_release.py unpack original/SMSL_AO300_UPDATE_VER0A5_EN.exe original/extracted
```

Disassemble it:

```bash
python3 tools/disasm/d51.py original/extracted/flash.bin original/extracted/flash.asm 106d 0fc8 10fc 0f93 1006 10be 0ce9 0d03 0ed2 1047 0cd2 10e1 0f62 0d83 0e2a 144e 126f 135a 14e3
```

The extracted `flash.bin` must have sha256 `85e8ac50ffcf47ea…` (full value in
`KNOWN_IMAGES` in `tools/flash/flash_ao300.py`); every address in this README and in the
patches refers to that image.

The trailing addresses are the key handlers reached only through the dispatcher's
inline switch table, which the disassembler cannot follow on its own.

Build every feature image (bases first), then test them all:

```bash
python3 tools/build.py
python3 tools/run_tests.py
```

`python3 tools/build.py house-numerals` builds only that image and the ones it stacks on.
To package an image into the vendor updater:

```bash
python3 tools/pe/stc_release.py rebuild original/SMSL_AO300_UPDATE_VER0A5_EN.exe features/direct-select/build/flash_patched.bin features/direct-select/build/SMSL_AO300_UPDATE_VER0A5_EN_directselect.exe
```

The rebuilt updater is flashed exactly like the vendor one: connect the serial adapter,
click the start button, then either power the amp on from cold or press Source on the
remote while the amp is in standby.

### Feature graph

Each image is a feature stacked on another image, and can link in fixes. Every
`features/<name>/build_patch.py` declares where it sits:

```python
BASE = "fast-lcd"                  # the image it stacks on: another feature, or "stock"
INCLUDES = ["direct-select", "fix-auto-off", "strings", "start-volume", "fix-volume-pop",
            "fix-menu-input"]      # fixes linked into its own code
BASE_IMAGE = features.image(BASE)  # tools/patch/features.py resolves the path
BASE_SHA = "30c1e6fe…"             # still pinned: a changed parent must be re-checked
```

`python3 tools/build.py --graph` prints the tree. `──` is BASE (builds on), and `+` is
INCLUDES (a fix linked into that image):

```
stock                       85e8ac50…
├── direct-select           'v1.4 tbenr ds4'    0x9400..0x9473  4b5dcfce… known  [fix, hook 0x5D10; included by house-numerals, phosphor-panel]
│     = config              WAKE_ON_INPUT 0..1 (default 1)
├── fast-lcd                'v1.4 tbenr fast3'  0x9700..0x977C  30c1e6fe… known
│   ├── house-numerals      'v1.4 tbenr hn19'   0x9800..0xDD41  8cf34756… known
│   │     + direct-select   fix linked into house-numerals
│   │     + fix-auto-off    fix linked into house-numerals
│   │     + strings         fix linked into house-numerals
│   │     + start-volume    fix linked into house-numerals
│   │     + fix-volume-pop  fix linked into house-numerals
│   │     + fix-menu-input  fix linked into house-numerals
│   └── phosphor-panel      'v1.4 tbenr pp4'    0x9800..0xDC34  cc2292e7… known
│         + direct-select   fix linked into phosphor-panel
│         + fix-auto-off    fix linked into phosphor-panel
│         + strings         fix linked into phosphor-panel
│         + start-volume    fix linked into phosphor-panel
│         + fix-volume-pop  fix linked into phosphor-panel
│         + fix-menu-input  fix linked into phosphor-panel
├── fix-auto-off            'v1.4 tbenr aof3'   0x9680..0x969D  1fb64470… known  [fix, hook 0x55B9; included by house-numerals, phosphor-panel]
├── fix-menu-input          'v1.4 tbenr mi1'    0x9650..0x9675  693bdef6… known  [fix, hook 0x5892; included by house-numerals, phosphor-panel]
├── fix-volume-pop          'v1.4 tbenr vp1'    0x96D6..0x96FC  e2075861… known  [fix, hook 0x0F4A, patch 0x0D0F, patch 0x0D8F, patch 0x0E36, patch 0x0EDE; included by house-numerals, phosphor-panel]
├── start-volume            'v1.4 tbenr sv1'    0x96B0..0x96D5  50ad4119… known  [fix, hook 0x5596; included by house-numerals, phosphor-panel]
└── strings                 'v1.4 tbenr str3'   0x96A0..0x96AF  6c5611ad… known  [fix, patch 0x91ED; included by house-numerals, phosphor-panel]
```

Stacking (BASE) is for code that changes how the stock UI is drawn: fast-lcd on stock, a
theme on fast-lcd. The two themes both stack on fast-lcd and both put their code at 0x9800:
they are alternatives, never in one image, so the slot warning `tools/build.py` prints for
them is expected. Everything else is a fix on stock, with its own small standalone image,
and is linked into the image meant for the amp through INCLUDES. House-numerals then
depends on fast-lcd (its base, and so on down to stock) and on direct-select, fix-auto-off,
strings, start-volume, fix-volume-pop and fix-menu-input (included). An image has exactly one BASE, because
images stack, but can include any number of fixes. Including a fix uses the fix's source, not its standalone
image; that image stays a separate branch of the tree, and a change to a fix only moves
the shas of the images that include it. (Until 2026-09-30 every image stacked on
direct-select instead, so a change to it rebuilt everything: hn11 and hn11.1 are from
that shape, hn12 is the same firmware in this one.)

A fix is a feature whose folder also holds `<name>.py` (dashes as underscores) exporting
`HOOK` and `emit(a)` (code at a hook), or `PATCHES` (in-place byte changes of the same
length, `[(address, original, new, note)]`; `features/strings` corrects stock texts this
way), or both (`features/fix-volume-pop`). Its own image is only a standalone build on stock. A build that
lists it in `INCLUDES` links it in three places: `HOOKS += features.hooks(INCLUDES)`,
`patches += features.patches(INCLUDES)` and `features.emit(a, INCLUDES)` in `assemble()`.

`tools/build.py` builds in order and checks every image:

- **Pins.** A feature whose `BASE_SHA` no longer matches its rebuilt parent is reported as
  a stale pin, and nothing below it is built.
- **Byte conflicts.** A feature may not change bytes an ancestor already changed; the
  version pointer is the one exception.
- **Includes.** Every included fix's hook must jump into the including image's own code,
  and its in-place patches must be applied.
- **Known images.** Each sha is looked up in `KNOWN_IMAGES`, and a new one is reported.
- **Code slots.** Features outside one chain are warned if their code areas share
  addresses, so the Ghidra labels stay one name per address.
- **XDATA.** Each feature, and each fix, declares the XDATA its code uses:
  `XDATA = [(0x0100, 0x01A7, "what")]`, or `[]`. Declarations of everything in one image
  must not overlap. That matters once a fix with its own state is included in a theme.
- **Configs.** An image with build-time configs (below) is built once more with every option
  at a non-default value; it must keep its size and move only the declared bytes.

#### Build-time configs

A feature may declare values that are safe to change at build time. start-volume's limits are
the example (`features/start-volume/start_volume.py`):

```python
CONFIG = {
    "SPEAKER_LIMIT":   features.Option(default=25, lo=0, hi=60, bytes=2, help="..."),
    "HEADPHONE_LIMIT": features.Option(default=20, lo=0, hi=60, bytes=2, help="..."),
}
SPEAKER_LIMIT = features.setting("start-volume", "SPEAKER_LIMIT", CONFIG)
```

`features.setting()` returns the default, or the value of the environment variable
`AO300_START_VOLUME_SPEAKER_LIMIT` when it is set (checked against the range). The
declaration is a promise: the value is an 8-bit immediate; every value in range builds code
of the same length that differs from the default build only in the `bytes` places holding
the value; and the feature's own tests cover the behaviour over the range. `tools/build.py`
checks the first two parts on every build (`build.config_check`, through
`features.config_diff`), and always builds the defaults itself; `build.variant(name, values)`
builds an image with other values without touching the feature's `build/`. The graph shows
configs on a `= config` line under the feature. Because of the promise, an image that differs
from a registered one only by config values is the one exception to the `KNOWN_IMAGES` rule:
no entry, no new `VERSION_TEXT`, no new tests. The release installer (below) builds users'
images this way.

Byte checks can't tell whether an included fix still works in its new image, for example
because it jumps into stock code another layer changed. Integration tests check that
instead: a layer has to keep working in the final image. A feature whose
`emu_test.py` sets `INTEGRATION = True` also accepts `--in <feature>`. With it, the test
checks, in that feature's image, what must stay true wherever it is built on or included.
`run_tests.py` runs it for every image that contains the feature, as jobs such as
"direct-select in house-numerals" and "fix-auto-off in house-numerals":

- direct-select: the six direct commands, the two power commands (on the whole firmware:
  from standby, when on, twice, from a menu page), an input command in standby powering the
  amp on on that input with one source setup, and the stock translation of the other 248.
- fix-auto-off: Auto OFF times out after power-on as after a key; Always ON is untouched.
- strings: the corrected texts are in the image, and the status loader shows them.
- start-volume: after a cold power-up and after standby the volume is at most the limit, on
  speakers and on headphones, and the home screen shows it.
- fix-volume-pop: on Optical and Coaxial without a signal the volume keys change no mute
  pin and leave the NJW1194 and the DAC muted; the signal then unmutes at the new volume.
- fix-menu-input: an input chosen in the menu leaves P4.0 and the chip setup alone, and the
  amp sees the same events as after the Source key.

## Flashing from macOS or Linux

`tools/flash/flash_ao300.py` wraps [stcgal](https://github.com/grigorig/stcgal) and
refuses to write unless the chip reports exactly what a factory AO300 reports: magic
0xF7DC, bootloader 7.2 or newer, 24 MHz clock, option bytes `FF BF BC F7 F4`, code area
ending at 0xF400, no download password, and bootloader pin detection off. Those values
were read from a real amp and match the vendor container. Options are written back
unchanged; the clock is calibrated to 24.000 MHz like the vendor tool does.

```bash
python3 tools/flash/flash_ao300.py -p /dev/cu.usbserial-10 identify     # read-only
python3 tools/flash/flash_ao300.py -p /dev/cu.usbserial-10 dryrun       # read-only, full handshake
python3 tools/flash/flash_ao300.py -p /dev/cu.usbserial-10 flash features/direct-select/build/flash_patched.bin
python3 tools/flash/flash_ao300.py -p /dev/cu.usbserial-10 recover original/extracted/flash.bin
```

When it says "Waiting for MCU", put the amp in standby and press Source on the remote,
or unplug and replug the mains. `flash` asks you to type FLASH first, before it waits
for the bootloader, so there is no pause between the handshake and the erase; `-y`
after the image path skips the question. On Linux the port is usually `/dev/ttyUSB0`;
if it vanishes mid-run (`Errno 5`), check `dmesg` for brltty or ModemManager
grabbing the CH340. `-p` also takes a pyserial URL, so an adapter on another machine
can be reached through a forwarder such as `rfc2217://host:4000` (stock stcgal opens
device paths only; the flasher routes URLs through `serial_for_url`). A ready-made
ser2net setup in Docker is in `tools/flash/ser2net/`. `identify` passed this way on
2026-10-05 (ser2net 4.6 on a Linux box, flasher on a Mac on the same LAN), and so did
`dryrun` and `flash` the same day (hn17, 56832 bytes in 15 s at about 3.8 kB/s): the switch to
115200 baud travels as an RFC 2217 control command and works through ser2net. If a
flash fails after the erase, the amp has no firmware until `recover` is run from a cold
power-up; the bootloader is in ROM and survives. Every run is appended to
`tools/flash/flash_ao300.log`, with raw packets when `-D` is given.

## Status

Built on 2026-11-14, emulator-verified, not flashed: direct-select ds4 (`v1.4 tbenr ds4`,
sha256 `4b5dcfce…`). An input command (NEC 0x10..0x15) in standby now powers the amp on, on
that input: the hook writes the input and returns the Power key, and stock's power-on does its
one source setup on it. With the amp on nothing changed. It is a build-time config,
`direct-select.WAKE_ON_INPUT` (default 1; 0 keeps ds3's "ignored in standby"), which the
installer asks about. Rebuilt on it with nothing else changed: house-numerals hn19
(`8cf34756…`), phosphor-panel pp4 (`cc2292e7…`), auto-switch as4 (`8e0602f5…`) and probe pr5
(`0fc654e4…`), all in `KNOWN_IMAGES`. To confirm on the amp: no pop when it wakes onto an input
other than the one it was left on (the emulator shows the input mux moving only while the
outputs are muted, as at a cold power-up).

Built on 2026-10-16, emulator-verified, not flashed: direct-select ds3 (`v1.4 tbenr ds3`,
sha256 `425460c3…`) adds idempotent power over IR, NEC 0x16 (on) and 0x17 (off), each a no-op
in the state it names ("Direct input selection and idempotent power over IR" below). Every
image that includes the fix was rebuilt on it with nothing else changed: house-numerals hn18
(`b3455f2b…`), phosphor-panel pp3 (`273edf8f…`), auto-switch as3 (`aa43a3e5…`) and probe pr4
(`e4a5bd1e…`), all in `KNOWN_IMAGES`. The amp still runs pp2.

Flashed on 2026-10-10 over the ser2net tunnel and confirmed by the user the same day:
`features/phosphor-panel/build/flash_phosphor_panel.bin` (pp1, `v1.4 tbenr pp1`, sha256
`38a1499e…`), the second UI theme (study 2 of the mock, a VFD look: a dot-matrix name, a row of
lamps, a seven-segment volume page with afterglow), with the six fixes. It works; the left edge
of O and C looked cut off in the dot matrix, which pp2 (`f5ca8bba…`) corrects: flashed the same
day and confirmed by the user, the edges look right. See its README.

Flashed on 2026-10-05 and confirmed by the user the same day: `features/auto-switch/build/flash_autoswitch.bin`
(`v1.4 tbenr as1`), auto-switch stage 1. From Optical with nothing playing, the amp went to
HDMI about a second after the TV came out of standby. The Bluetooth half cannot fire: the
module is off whenever another input is selected, so a phone cannot connect there; as2 (not
flashed) enables HDMI only.

Flashed on 2026-10-05: `features/probe/build/flash_probe.bin` (pr2, `v1.4 tbenr pr2`), the
read-only register dump on the FN button, over the forwarded serial port
(`rfc2217://`). The amp came back, and the first dump arrived on the header at 115200 baud:
1204 bytes, the format the emulator predicted, every register stock writes reading back as
written. Thirteen dumps were taken that day across HDMI, Optical, Coaxial and Bluetooth, with
and without streams, and with headphones in (`docs/bus-map.md`, "Hardware read-back"). pr1
(the same on NEC 0x16) was flashed the same day and replaced by pr2 before a dump was taken.


Verified on hardware on 2026-09-28: `features/direct-select/build/flash_patched.bin`
flashed with `tools/flash/flash_ao300.py` over a USB-serial adapter from macOS. All six
direct-select commands switch to the right input, the stock remote works unchanged, and
the RESET page shows `v1.4 tbenr`. The rebuilt vendor updater was also confirmed to
start and validate the same image on Windows.

Also verified on 2026-09-28, flashed from Linux (`/dev/ttyUSB0`): the tuned-blit test
build (`features/blit-test`). The colour bars are correct through both paths, the
full-screen fill times match the emulator's STC8 prediction (about 15 ms tuned against
147 ms stock), and the result holds for 5 s. fast-lcd superseded it, and the folder was
removed on 2026-09-29 (last present at commit c28c4dc). fast-lcd's README keeps the bus
timing.

Flashed on 2026-09-28 and working so far: `features/fast-lcd/build/flash_fastlcd.bin`,
the stock UI through the fast pixel path. Longer listening tests are still to come.

Tried on 2026-09-29 and looks OK: `features/house-numerals/build/flash_house_numerals.bin`
(hn4.1, `v1.4 tbenr hn4.1`), the House Numerals home and volume page with the non-blocking
eased wipe. Longer use is still to come. Its successor hn5 (`v1.4 tbenr hn5`, the mock's
home screen in the mock's typefaces) was tried on 2026-09-29: it looks great and the
anti-aliased text works on the panel, but the tags, status line and volume are too small.
hn6 (`v1.4 tbenr hn6`) has them larger, sized in `features/house-numerals/sizing.html`; it is
emulator-verified and not yet tried on the amp. hn6.1 (`v1.4 tbenr hn6.1`) is hn6 with
fix-auto-off included, so Dimmer Auto OFF also times out after a cold power-up. hn7
(`v1.4 tbenr hn7`) is hn6.1 with the sizes redone in `sizing.html` (status line 28 px, name
54, tags 16). Both are emulator-verified, including the fix's integration test. hn7 was tried on
the amp on 2026-09-29: it looks good, and Auto OFF times out after a cold power-up. hn8
(`v1.4 tbenr hn8`) adds the mock's volume page (name, status line, "VOL", 84-px numerals, a
288-px line, the level in dB and "max 60"), rounded tag corners and a reddish status line
without a signal; tried on the amp on 2026-09-30, works, except that the status stayed reddish
for a few seconds after an input change from an input without a signal (fixed in hn10.1). hn9 (`v1.4 tbenr hn9`)
adds the volume page's two animations from the mock, the number roll and the spring on the
position line; hn10 (`v1.4 tbenr hn10`) gives both wipes the mock's cubic ease, 0.32 s each
way. Both were tried on the amp on 2026-09-30: good. hn10.1 (`v1.4 tbenr hn10.1`) fixes the
status tint after an input change (only the status loader's own text is reddish) and links
in `features/strings` ("Disconnected" for ARC's "No Connected"); tried on the amp on
2026-09-30: works.

Verified on the amp on 2026-09-29, as part of hn7: the Auto OFF fix (`features/fix-auto-off`). With
Dimmer on Auto OFF the display goes dark after a cold power-up. Its standalone image
`features/fix-auto-off/build/flash_fixautooff.bin` (`v1.4 tbenr aof3`, stock plus the
fix) has not been flashed.

Verified on the amp on 2026-09-30, as hn11: direct-select v2 (`v1.4 tbenr ds2`), which
ignores a direct command for the input already selected instead of re-initialising it.
Every image was rebuilt on it that day (`fast2`, `aof2`, `str2`, `hn11`, then `hn11.1` once
hn10.1's fixes were merged in), all emulator-verified. hn11.1 was flashed on 2026-09-30 and
works; the standalone ds2, fast2, aof2 and str2 images have not been flashed.

Flattened graph, 2026-09-30: direct-select became a fix on stock (its standalone image is
byte-identical to ds2), fast-lcd, fix-auto-off and strings moved onto stock (`fast3`,
`aof3`, `str3`), and house-numerals includes direct-select (`hn12`, hn11.1 with the same
code at other addresses). All emulator-verified; hn12 was flashed on 2026-09-30 and works.

Verified on the amp on 2026-10-02, as hn13: start-volume (`features/start-volume`), which caps
the volume at power-on at limits set at build time, speakers 25 and headphones 20 by default.
House-numerals includes it as hn13 (`v1.4 tbenr hn13`, hn12 otherwise); hn13 was flashed on
2026-10-02 and works. The standalone image (`v1.4 tbenr sv1`) is emulator-verified and has not
been flashed.

The MUTE state of the volume page (2026-10-02): the mute key toggles as stock and then shows
the volume page (red speaker, "MUTE", the line empty) instead of staying home, and it also
toggles while the page is open, where stock only closed the page. Tried on the amp on
2026-10-02 as a branch build on hn12 (sha256 `1e5691d8…`, without start-volume; its RESET page
also says `v1.4 tbenr hn13`): works. hn14 (`v1.4 tbenr hn14`) is that merged with hn13, so it
has start-volume and the MUTE state; emulator-verified, not yet flashed as this image.

Heard on the amp on 2026-10-02 (hn13; stock code, so not new): on Optical with nothing
connected the first volume key pops, later ones do not, and going round the sources arms it
again. The emulator shows the cause, a volume key moving the mute pins when the receiver has
no lock, and predicted that Coaxial right after Optical would be silent, which the amp
confirmed. `features/fix-volume-pop` removes it (`v1.4 tbenr vp1`), and house-numerals
included it in a branch build on hn13 (sha256 `d39d321c…`; its RESET page says
`v1.4 tbenr hn14`, like the MUTE state's hn14 above). That build was flashed on 2026-10-02: the
pop is gone. The standalone image is emulator-verified and has not been flashed.

Also heard on 2026-10-02 (on that build; stock code): a pop when an input is chosen in the menu. The
menu switches by another path than the Source key: it turns P4.0 off for 3 s and sets every
audio chip up again with the speaker path open. `features/fix-menu-input` makes the menu
switch as the Source key does (`v1.4 tbenr mi1`). The same branch's next build has both fixes
(`v1.4 tbenr hn15`, sha256 `7a4af92f…`). It was flashed on 2026-10-02: no pop on an input
change any more, through the menu, the Source key or direct-select. The standalone image is
emulator-verified and has not been flashed.

hn16 (`v1.4 tbenr hn16`) is hn14 with both fixes: start-volume, the MUTE state, fix-volume-pop
and fix-menu-input in one image. Flashed on 2026-10-02: the fixes work.

hn17 (`v1.4 tbenr hn17`, sha256 `782eb508…`) is hn16 with the stock big font's area reclaimed:
every big text is drawn by the theme, so nothing reads the stock big glyphs any more, and 5015
bytes of the theme's fonts sit in their place (0x6A23..0x7DB9). The image ends at 0xDD19, 5054
bytes earlier than hn16; the screens are unchanged. The tests trap the stock big-font painters
on every run. Flashed on 2026-10-05 over the ser2net tunnel and checked on the amp: the RESET
page, every big text at home, the moved fonts (tags, home volume, the volume page's name, label,
status and caption), every menu page and a power cycle all look as before.

## What the custom firmware adds

### Volume cap at power-on

Stock comes back at the volume it was left at, up to 60. With `features/start-volume` the
amp starts at min(last volume, limit), after a cold power-up and after standby. The volume
keys are not limited. The two limits are build-time configs ("Feature graph" above), each a
volume step 0..60 where 60 is no cap; the defaults are 25 for speakers and 20 for headphones:

```bash
AO300_START_VOLUME_SPEAKER_LIMIT=30 AO300_START_VOLUME_HEADPHONE_LIMIT=60 python3 features/phosphor-panel/build_patch.py
```

An image built this way is the registered one with four bytes changed, which
`tools/build.py` verifies for every value; it needs no new `VERSION_TEXT` or `KNOWN_IMAGES`
entry. The feature's README has the details. A menu setting was considered instead and set
aside as too much for a choose-once value; `docs/menu-system.md` keeps what was learned about
the stock menu.

### No pop from the volume keys without a signal

Stock mutes Optical and Coaxial by register when the signal goes, and leaves the mute pins
where they were. The first volume key then moves them (P2.7 and P2.2 high on speakers, P2.5
low on headphones) and opens the NJW1194 for a tick, which pops. With
`features/fix-volume-pop` a volume key without a signal changes only the number and the
display; the unmute that follows the signal applies the volume. With a signal, and on the
other inputs, the keys are stock. The feature's README has the stock code and the patch.

### Input changes in the menu without the supply cycle

Stock handles an input chosen in the menu differently from the Source key: it mutes by
register only, turns P4.0 (a supply enable) off for 3 s, and then runs the power-on chip
setup again, with the speaker mute pin released nearly all the way through. The amp pops.
With `features/fix-menu-input` the menu's choice runs the Source key's steps instead: mute,
`input_set_hw`, unmute 2 s later. P4.0 is only switched at power-on and standby. The
feature's README has the stock code, the timeline and what the emulator can and cannot say
about P4.0.

### Direct input selection and idempotent power over IR

Eight new NEC commands, sent with the stock remote's address bytes 0x12 0x34:

| Command | Input |
|---|---|
| 0x10 | 1 USB audio |
| 0x11 | 2 Optical |
| 0x12 | 3 Coaxial |
| 0x13 | 4 Bluetooth |
| 0x14 | 5 HDMI (ARC) |
| 0x15 | 6 AUX IN |
| 0x16 | power on |
| 0x17 | power off (standby) |

With the amp on, the input commands act only on the home screen; on a menu page they are
ignored. A command for the input that is already selected is ignored as well (since
`v1.4 tbenr ds2`): re-applying an input runs the stock source switch again, which
re-initialises it and interrupts the audio.

In standby an input command powers the amp on, on that input (since `v1.4 tbenr ds4`), so
one command is enough to get "on, playing HDMI" from any state. The hook only writes the input
number and returns the stock Power key: the power-on sequence is stock, and its chip setup
reads the input for its one source setup while the outputs are still muted. Selecting first
and powering on second costs one source setup; the other order would run two and interrupt
the audio a few seconds after the wake. The home screen shows the new input, and the settings
save that follows every power-on stores it. This is the build-time config
`direct-select.WAKE_ON_INPUT` (default 1): with 0 the input commands are ignored in standby
and only 0x16 or the Power key wake the amp. The installer asks for it; by hand,
`AO300_DIRECT_SELECT_WAKE_ON_INPUT=0` in the environment of a `build.variant()` build.

The power commands (since `v1.4 tbenr ds3`) are for a controller that gets nothing back from
the amp, so the stock Power toggle (0x01) would leave it guessing: 0x16 powers on and is
ignored when the amp is already on, 0x17 powers off and is ignored in standby. Each becomes the
stock Power key only when that key does what the command says, so the power-on and power-off
sequences themselves are stock. On a menu page the stock Power key only goes home; 0x17 runs
that go-home step itself first, so it powers off from any page with one command. In standby
neither command can turn into the Source key, which would reset the MCU into the bootloader.

Every other command behaves exactly as in stock, including the ones the remote never sends.
The mechanism is described in `features/direct-select/direct_select.py`; `direct_select.asm`
is the generated listing.

### Version string

The RESET menu page shows `v1.4 tbenr ds4` instead of `v1.4`. Change `VERSION_TEXT` in
`build_patch.py` to alter it; the row fits 20 characters.

## Release for users

`tools/release.py` packs `dist/ao300-custom-<version>.zip`, a bundle for someone who only
wants the firmware on their amp: `install.sh` creates a venv, installs `requirements.txt`
and runs the wizard `tools/installer/ao300_installer.py`, which asks for the vendor updater
(to be put in `original/`), checks its sha, asks for the theme and the build-time configs,
builds the image, finds the USB serial adapter and runs `tools/flash/flash_ao300.py` with the
terminal attached (with `-y`: the menu choice is the confirmation). The bundle holds the wizard, the build tools and the features the two
themes need, and no firmware; the user guide inside it is `tools/installer/README-release.md`.
The wizard trusts a build by rebuilding the theme with its defaults (the sha must be in
`KNOWN_IMAGES`) and checking that the user's image differs from it only in the configs'
bytes (`features.config_diff`); the flasher then reports it as "not a registered image",
which the wizard explains. `release.py` ends with a self-test that extracts the zip and builds
both themes from inside it. `python3 tools/run_tests.py installer` runs the wizard's tests
(`tools/installer/test_installer.py`: the config API, port filtering, stock detection, the
release contents, and unattended builds of both themes checked against the default images).
The menu's fourth item, "Make a Windows updater (.exe)" (`--action exe`), opens no port: it
writes a copy of the vendor updater carrying the built image next to it in `build/out`
(`stock.rebuild_updater`, through `stc_release.rebuild_exe`), unpacks it again and requires
the image back byte for byte. It needs the vendor `.exe` in `original/`. An updater made by
the wizard has not been run on Windows yet. The hand-made direct-select one was confirmed
to start and validate its image there on 2026-09-28 (see "Status"); no flash through a
rebuilt updater is on record.
Every answer has a flag (`--theme`, `--set FEATURE.OPTION=VALUE`, `--port`, `--action`,
`--build-only`), so the wizard also serves as a one-line build tool. The bundle
`ao300-custom-1c4dbd4-dirty-20261011` was run on a Linux machine on 2026-10-11 and worked
end to end (the user's report). When several ports are listed, the wizard proposes the only
known adapter among them (a CH340 next to an Arduino, say).

## UI themes

The designs in `features/ui-theme/ui_themes.html` are built as features on top of fast-lcd.
The parts every theme needs live in `tools/patch/uikit.py`, extracted from house-numerals
(which builds byte-identical with it):

- **Routines** (a `Kit` emits them into the theme's code; XDATA for them is passed in):
  - `uk_fill`: rectangle fill in any colour, about 9 clocks per pixel.
  - `uk_paint`: streaming text painter for the stock fonts. It takes ink and background
    colours, an x clip window and scale 1 or 2, and is pixel-identical to the stock text
    renderers. `uk_home_x` gives a string's page-1 start x.
  - `uk_text`: painter for proportional fonts made from the UI mock's typefaces
    (`tools/patch/pfont.py`, `tools/fonts/`). Glyphs are 1-bit, or anti-aliased with 4 levels
    stored run-length (background, 1/4, 3/4 and ink colour, mixed on the amp by `uk_avg`).
    It takes left, right or centred alignment, letter spacing and an x clip window, and
    reports the last column drawn. About 12 clocks per pixel on the 84 px numerals.
    `uk_textc` is the same with a row clip (`TP_YC0`..`TP_YC1`, for text that slides): cells cut
    by it go through a separate decoder (`tx_yclip`, both formats, or format 2 only with
    `emit_text(one_bit=False)`), about 20 clocks per drawn pixel; `uk_text` itself sets every
    row and stays on the fast decoders (a few clocks more per call).
  - `uk_acc`: the accent colour (the COLOR tint, or the theme's own colour on White).
  - `uk_tasks`: the per-tick driver. It is hooked on `main_tasks_on`'s call to
    `main_tick_tasks` (0x5B2A) and runs the theme's step routine once per 10 ms tick,
    after the stock tick work and only while the amp is on. Animations never block the
    main loop. It serves `main_tick_tasks`' re-mute request itself before it tests the tick
    flag, so no tick is handled without the step.
- **Fonts:** descriptors and character maps of the two stock fonts for `uk_paint`; for
  `uk_text`, a `pfont.PFont` cuts a rasterised face down to the characters a theme needs and
  emits it. Sizes, for example: the 84 px numerals (digits) about 2.2 KB, the 52 px display face
  (the input-name letters) 1.3 KB, 11 px mono (all of ASCII) 1.7 KB at 1 bit or 3.3 KB
  anti-aliased.
- **Stock facts:** the stock routines, buffers and variables themes use, and a catalogue of
  hook sites with their original bytes (`STOCK_SITES`, and `VOL_ENTRY_SITES`, where the
  volume keys open page 2).
- **Helpers:** `ease_in_out()` (cosine), `ease_cubic()` / `ease_cubic_in_out()` (the UI mock's
  cubic ease, `ui_themes.html`'s `ease`, as a table of positions; it barely moves at both ends,
  so consecutive positions can be equal or 1 apart), `rgb565()`, and assembly written as text
  lines (`S`).
- **`build_image()`:** the common build, from the base sha check through to the listing.

`tools/patch/uikit_test.py` tests the kit on its own. It builds fast-lcd plus the kit and
compares `uk_paint` against the stock glyph painters and text renderers for every character
and every string in the firmware, and `uk_text` against `PFont.render` (every glyph of five
test fonts in both formats, alignment, spacing, tints, clip windows through the middle of
glyphs and runs, and `uk_textc`'s row clips: above, below, both, one row, outside, empty,
combined with x clips). `tools/emu/uitest.py` holds the helpers theme tests share.
`tools/emu/panel_video.py` renders what the glass shows, with the panel's 60 Hz line-by-line
refresh, for checking animations.

Not in the kit yet: the wipe's step engine and page-element model (still in house-numerals),
Phosphor Panel's level engine and seven-segment cell painter (still in phosphor-panel), and
per-pixel transitions. House Numerals' spring (a fixed-point spring as a per-tick matrix) and
its roll could move to the kit when a second theme needs them; the hook plumbing the two
themes share (the refresh hold, the stock-clear cancel, the flag path, the name guard, the
signal check, the mute key) is the first candidate.

Two themes are built: House Numerals (`features/house-numerals`, study 3) and Phosphor Panel
(`features/phosphor-panel`, study 2: the name as a dot matrix baked into its font, the
seven-segment cells as one run-length map streamed through a per-segment palette, and the
mock's afterglow crossfade as a sequenced fade run by a per-tick level engine). Both include
the six fixes; only one goes on the amp at a time.

### Sizing a theme's home screen

House Numerals takes its home layout from `features/house-numerals/layout.json`: every
element's font (by raster id), position, the tag boxes, the status colour and the bar.
`features/house-numerals/sizing.html` edits it. The page shows the home exactly as the
firmware draws it (same rasteriser, packing and anti-aliasing; checked pixel for pixel against
the emulator). It also shows each text's cap height on the panel in millimetres and each
font's exact size in flash, and flags overlaps and texts wider than the screen.

1. Start the font bench, a local server for the page (127.0.0.1 only; it builds nothing):

       python3 tools/fonts/rasterize.py

2. Open the sizing page at the address it prints
   (`http://127.0.0.1:8767/features/house-numerals/sizing.html`). Pick a starting point or
   `layout.json`, set the amp's state (input, status, tags, volume, mute, tint) and move
   the sliders until the checks under the screen are clear.
3. Press **Save layout and fonts**. It writes the fonts at the chosen sizes
   (`tools/fonts/raster/<id>.json`, added to `tools/fonts/specs.json`) and `layout.json`.
4. Rebuild and test by hand:

       python3 features/house-numerals/build_patch.py
       python3 tools/run_tests.py house-numerals

5. Before flashing, add the new image's sha256 (the build prints it) to `KNOWN_IMAGES` in
   `tools/flash/flash_ao300.py`, set a new `VERSION_TEXT` in `build_patch.py`, and commit
   `layout.json` with the new rasters.

The build stops with a message when `layout.json` names a font that has no raster, and asserts
that the elements don't overlap. The page needs the font bench to save; opened any other way it
previews only.

## Testing

`emu_test.py` runs the patched image's IR-translate routine in a small 8051 interpreter:

- the six new commands select the right input, and only when on and on the home screen;
- all 256 possible commands are compared against the stock image, and must match outside
  the six new ones;
- the version pointer resolves to a valid string;
- the only bytes changed inside the stock image range are the three-byte hook at 0x5D10
  and the two pointer bytes at 0x22CB and 0x22CD.

The other feature tests run their images in the full emulator (`tools/emu/emu8051.py`).
It executes the stock routines with clocks counted from the STC8 instruction table. The
LCD bus is decoded into an ST7789 model and saved as PNG.

`python3 tools/run_tests.py` builds every image (`tools/build.py`), then runs all the feature
tests, the integration tests (see "Feature graph") and the UI kit's test at once, on
the C core, in about 3 minutes, most of it the two themes' 256-command sweeps (before
house-numerals the run took about 5 s; the Python reference, `EMU8051=py`, took about 8
minutes). `python3 tools/run_tests.py uikit` runs only the kit's test (about 3 s). After changing
the emulator, `python3 tools/emu/test_core.py` checks the C core against the Python
reference: every opcode from random states, random programs, and a boot scenario of
the stock firmware compared at every 10 ms tick.

Whole-firmware scenarios run on `Amp` (`tools/emu/ao300.py`), which fires both timer
interrupts the stock firmware enables: the Timer0 ISR every 10 ms and `timer3_isr` (0x5040)
every 0.5 ms, on one grid with Timer0 first when both are due. Until 2026-09-29 `Amp` ran
Timer0 only. The encoder key 0x2D then stayed 0 instead of 0xFF, and `read_key` handed
`dispatch_key` a phantom key 0 on every idle main-loop pass on every powered page. Among
other things that re-armed the Auto OFF countdown 0x2F:0x30 (0x0BBD) on every pass and made
each idle pass about 640 clocks instead of about 85. With Timer3 the idle home page makes
about 280,000 main passes a second, not 38,000. A test hook on a per-pass address (such as
house-numerals' wipe watcher on 0x5B2D) costs 7.5 times as much, so arm such hooks only
while they are needed. Absolute times in the scenarios moved by up to about 0.07 s (the ISR
takes about 131 clocks every 12,000, about 1% of the CPU). The fast-lcd and house-numerals
comparisons against their base images came out the same. The deepest stack in the
house-numerals tour went from 0xAF to 0xB3: stock's own delay leaves at SP 0xA0 with
`timer3_isr`'s deeper frame on top. Running Timer3 at the real rate costs about 7% more
emulator time than not running it.

`Amp.press` sets what a finished frame leaves for the main loop: the command in 0x6A and bit
0x20.4. It does not run the decoder, so the release timer 0x34 is not armed and 0x6A keeps the
command until the next press or settings save. A press on the tick of a settings save (50 main
ticks after a setting change: 0.50 s after a Vol+ on hn16, 0.52 s on fast-lcd, 0.67 s on stock)
is lost to a stock race, see "Open questions"; a wait of whole ticks ends just after a Timer0
tick, inside the window, so in a scenario this is not rare but certain. Keep presses off that
tick unless the race is what the test is about.

`Amp` has no EEPROM: reads return 0, so the emulated amp boots into standby with every
setting at its clamp. Tests seed single reads through a hook on 0x5970 (fix-auto-off), or
model the whole EEPROM behind the stock IAP routines (start-volume: read 0x5970, write
0x58AF, erase 0x59D0), which also makes a cold power-up turn the amp on by itself, as the
real one does.

`stc_release.py rebuild` output was verified by unpacking it again and by checking the
PE structure with `pefile`. Only the firmware resource differs from the vendor updater.

## Hardware map, as seen from the MCU

What the control MCU (STC8C2K64S2) talks to, and how. Chip identities come from the
firmware's bus traffic, silkscreen labels on board photos (ASR thread page 25) and
retailer listings; pin roles come from the code. `docs/bus-map.md` has the full register
and pin tables, from an emulator trace of the stock image (`tools/emu/bus_trace.py`).

Two buses share the pins P3.7 (data) and P4.1 (clock):
- a 3-wire write-only bus with latch P2.0 for the NJW1194;
- a bit-banged I2C master (clock stretching, ACK check) for everything else.

| Subsystem | Chip | MCU interface | Notes |
|---|---|---|---|
| Volume, bass, treble, EQ presets, speaker/headphone volume | NJW1194 analogue volume/tone controller | 3-wire, 16-bit words (0x54EA / 0x54DA): data byte D15..D8, select D7..D4 (0=vol1, 1=vol2, 2=input sel, 3=treble, 4=bass), chip addr D3..D0 | Volume code n = 32 - n/2 dB, 0xFF = mute; steps vs dB in the "Volume scale" section. Tone byte: D15 boost/cut, D14..D11 level 0..10 dB, D10 tone on/off (0x22.4 = bypass) |
| DAC and its filter modes | CS43131 | I2C address 0x62, write-only (`dac_write` 0x4D8A, 5 tries); reset on MCU P3.4 | The five filter menu options are the CS43131's own modes: `dac_set_filter` (0x4ECD) writes register 0x090000 = 0x02, 0x42, 0x82, 0xC2, 0xE2 for settings 1..5. Mute is register 0x090003 (0xA3 / 0xA0). Full register list in `docs/bus-map.md` |
| GPIO expander | one AW9523B (silkscreen RST_AW9523) | I2C address 0xB0; pin ids 0x10..0x1F; register write 0x51AD, write-pin 0x1A7C, read-pin 0x2302, init 0x47BA. The routines can address four chips, but every call uses the first | Four outputs in use: 0x10 and 0x14 to the Bluetooth module, 0x17 (set low once), 0x18 high on HDMI. Six inputs: Bluetooth status and the signal-present lines. The mutes, relays, resets and mux lines are MCU pins. Pin table in `docs/bus-map.md` |
| Clock generator | Si5351 register layout (part not seen) | I2C address 0xC0, write-only; one 43-register table (0x92C6) sent at power-on by `clkgen_load` (0x5089) | Output 0 at twice the reference frequency, the other outputs off, never changed afterwards. Reference and destination unknown |
| Digital interface receiver | TI PCM9211 (fits: I2C 0x80, regs 0x38/0x39, net DIR_RST) | I2C read of sample-rate registers for optical, coax and Bluetooth | Bluetooth audio therefore arrives as SPDIF; lock pin on MCU P4.2 |
| USB audio | XMOS XU-316, own firmware | UART1 receive-only (ISR 0x55F2, `uart1_init` 0x59ED: 115200 baud from Timer2). `standby_power_step` (0x55BC) moves UART1 with the power state through P_SW1: on P3.6 (RxD_2; TxD_2 would be P3.7, the shared bus data pin, so never write SBUF while the amp is on) when powered, back on the header pins P3.0/P3.1 in standby (pin pairs per the STC8G manual's S1_S table). USB activity on P4.5; USB_DET net | Incoming messages feed the PCM / DSD / DoP / MQA display |
| HDMI ARC | receiver near the HDMI socket (QFP-48, 1.2 V core; part not readable) | signal-present via expander pin 0x1C; routing shares the USB path, differing on P2.4 | Read by the signal-present routine 0x5232 |
| Bluetooth | separate module board | expander pin 0x10 (high only on the Bluetooth input; "BT Reconnect" pulses it low) and 0x14 ("BT list clear" pulses it low); status via expander pins 0x11..0x13; signal-present via expander pin 0x15 | own stack, out of reach |
| Signal presence per input (0x5232) | | USB: P4.5; optical/coax/AUX: P4.2 lock; Bluetooth: expander 0x15; HDMI: expander 0x1C; USB detect also expander 0x1D | Drives the on-screen status and a mute on signal loss (P2.5, after 1 s, digital inputs and headphone mode). There is no auto-standby; "Always ON / Auto OFF" is the display Dimmer timeout |
| Input routing | mux control + NJW1194 selector | P0.1, P0.2, P4.6, P2.4, expander pin 0x18, five receiver registers (0x24D6) | Per-input table in `docs/bus-map.md` |
| Power amplifier | MA5332MS, analogue in | mute on MCU P2.2 (high while muted and in headphone mode; role inferred from the trace) | no control interface |
| Speaker and headphone relays | two speaker relays, one headphone relay | P2.5 and P2.7, high in headphone mode (`p2_mute_pins_by_output`); which pin drives which relay is not known | |
| Display | ST7789-class colour LCD, 320 × 170 as drawn | bit-banged 8-bit bus on P1 (WR P0.5, CS P0.7, D/C P0.3), byte writes 0x567A / 0x5C9C with a delay call per byte; full clear 0x51EE | column offset 0x23. Window 0x4437: firmware y + 0x23 → CASET, firmware x → RASET, so pixels stream one 170-px vertical line at a time; P0 and P1 are push-pull (init 0x45CE). Two 1-bit fonts, stored rotated (glyph rows = screen columns): small 14 × 24 at 0x5DAB (42 bytes/glyph, painter 0x2DF8, status line and menus) and big 32 × 30 at 0x6A23 (120 bytes/glyph, painter 0x3F3C, input name and other centre-line text); glyph index = digits 6..15, A-Z 0x10.., a-z 0x2A.. (small font only); the big font's bytes hold house-numerals' fonts since hn17 (nothing there draws with the stock big glyphs, see "Memory budget"). Text colour from the theme table 0x9241 (RGB565: FFFF F800 07E0 33BF CFA0 07FF FC00 F81F). Home (refresh 0x5C8B): output/mute icon at 15,8 (0x5744), volume as two digits at 48,9 (0x5916; speaker volume 0x31 or headphone volume 0x52), format tag at 208,10, EQ tag at 266,10, input name centred at y 75, status line centred at y 135. Page variable 0x45 (1 home, 2 volume, 3+ menus; renderer 0x2101, jump table `ui_page_table` at 0x2143, page 2 entry `volpage_render` at 0x2167). Volume page (page 2): full clear, two digits at 130,75, "volume" at y 135, back home when the Timer0 countdown 0x3F:0x40 (200 ticks, armed by the key tail 0x0F48) runs out (0x3ED9 sets page 1 and 0x22.3); the next render only clears, and the periodic refresh 0x3FE3 draws home 10 main ticks later (0x27:0x28 is that refresh countdown: 10 after a render, 50 after each refresh). The volume keys (`key_volume_up` 0x0D03, `key_volume_up2` 0x0D83, `key_volume_down4` 0x0E2A, `key_volume_down` 0x0ED2) each set page 2 and open it directly, inline right after `mov 0x45,#0x02` (four sites: 0x0D33, 0x0DB3, 0x0E5A, 0x0F02, each `lcall ui_clear_screen` then the "volume" caption); the page-2 renderer at 0x2167 is only a second way in, not the path the keys use |
| Backlight | LED on GPIO P0.6 | on/off only; "Auto OFF" (0x29 = 2) clears it when the countdown 0x2F:0x30 runs out (0x33DB, main ticks), armed to 500 by every key (0x0BBD): about 6 s in the emulator, as main-loop passes miss some 10 ms ticks | no PWM peripheral on this MCU. Stock never arms it at power-on, see "AO300 PRO firmware" |
| Front panel | buttons / encoder (nets RE_A, RE_B) | P4.7, P5.4, P5.5, P2.6, P7.4 | Encoder scanned by Timer3 (0x5040, every 0.5 ms) through 0x396D into RAM 0x2D (0xFF idle); when no IR or panel key is pending, `read_key`'s tail (0x3E37) returns 0x2D on every powered page (menu pages other than 7 and 8 swap 0x1A and 0x1B first), so `dispatch_key` sees 0xFF (no key) on an idle pass. `tools/emu/ao300.py` runs Timer3 as well as Timer0 (see Testing) |
| Programming header | 4-pin header next to the HDMI receiver | 5V, TXD, RXD, GND (bottom silkscreen also shows RXD TXD GND) | the serial update port |
| Settings | MCU EEPROM area above 0xF400 | IAP routines 0x5956 (read) / 0x58AF (write) / 0x59D0 (erase) | Sector 0: magic 0x45 at 0x0001, power-on flag at 0x0002 (RAM 0x26; non-zero: a cold power-up turns the amp on). Sector 0x0200: the record 0x0201..0x020C = volume, input, output, 0x4A, EQ, 0x35, 0x2A, colour, headphone volume, 0x33, dimmer, filter. Loaded only at a cold boot (`settings_load_eeprom` 0x2F46), saved whole by `settings_save_eeprom` (0x492B) about 0.5 s after a change and after every power-on. Sector 0x0400 is erased by `key_power_off` (0x0CDA); no read or write of it was found |

Things the MCU firmware cannot change, because they happen elsewhere: USB decoding,
Bluetooth, SPDIF/ARC extraction, the DAC's conversion and filters themselves, and the
class-D amplification. The MCU only selects modes and values in those chips.

## Volume scale: 0–60 steps and dB

The number on screen is a step count; the dB value behind it is fixed by a table.

- **State.** Speaker volume is RAM 0x31 and headphone volume is RAM 0x52. RAM 0x2B picks
  which one is active: 1 is speakers, 2 is headphones. Both run from 0 to 60; the
  increment stops at 0x3C.
- **Power-on.** Both volumes are loaded from EEPROM at a cold boot and only clamped to
  0..60; standby keeps them in RAM. Stock therefore starts at the last volume on either
  output. Its only cap is on an output switch (0x5296): the headphone volume is cut to 30.
  `features/start-volume` caps both at power-on.
- **Hardware write.** 0x4DDC looks up code = table[60 − step] in the 61-byte table at
  0x9289 and sends it to the NJW1194 volume registers through 0x54DA / 0x54EA.
- **NJW1194 encoding** (from its datasheet): code n gives 32 − n/2 dB, in 0.5 dB steps;
  0xFF is mute.
- **Display.** Stock only ever shows the step, as two digits: at 48,9 on the home screen
  (0x5916) and at 130,75 on the volume page (0x5936). There is no dB text anywhere in
  the firmware. House Numerals (from hn8) shows the level below step 60 as a caption on its volume
  page ("−39.5 dB"), computed from the code table: `code − 35` half-dB steps.

The stock curve:

| Step | Code | NJW1194 gain | Relative to step 60 |
|---|---|---|---|
| 60 | 0x23 | +14.5 dB | 0.0 dB |
| 59 | 0x24 | +14.0 dB | −0.5 dB |
| 50 | 0x36 | +5.0 dB | −9.5 dB |
| 45 | 0x40 | 0.0 dB | −14.5 dB |
| 40 | 0x4A | −5.0 dB | −19.5 dB |
| 35 | 0x54 | −10.0 dB | −24.5 dB |
| 30 | 0x63 | −17.5 dB | −32.0 dB |
| 20 | 0x81 | −32.5 dB | −47.0 dB |
| 10 | 0x9F | −47.5 dB | −62.0 dB |
| 1 | 0xBA | −61.0 dB | −75.5 dB |
| 0 | 0xFF | mute | −∞ |

Shape of the curve:
- 60→59 is a 0.5 dB step;
- 59→35 is 1 dB per step;
- 35→1 is 1.5 dB per step.

Steps 1 to 60 cover 75.5 dB in total. The NJW1194 is at unity gain at step 45 and adds
gain above it.

Showing dB instead of steps is a display-only change. The volume code, the table and the
EEPROM format stay as they are:

- **Text table.** Replace the two-digit calls at 0x5916 and 0x5936 with a lookup that
  formats a dB string. Stored as twice the dB value, one byte per step fits, so the table
  is 61 bytes. The formatting code adds about 60 bytes.
- **Width.** A dB string is up to 6 cells ("−75.5" plus a unit), 84 px in the 14 × 24
  font. The home spot at 48,9 has room up to the format tag at x 208. The volume page
  needs the text re-centred.
- **Reference point.** Relative to step 60 (0 dB at maximum, negative below) is the usual
  hi-fi convention and is what the UI theme designs use. The NJW1194's own gain
  (+14.5 to −61 dB, 0 dB at step 45) is the alternative.
- **Curve, optional.** Making the steps even is a separate change: rewrite the 61 bytes
  at 0x9289. Evening it out changes how loud each step is, not just the label, so it
  should be a deliberate choice.

## Memory budget for custom features

Measured from the images; the code/EEPROM split is the chip's own setting (0xF400).

| Region | Size | Used | Free |
|---|---|---|---|
| Code flash, 0x0000..0xF3FF | 62464 bytes | 56642 bytes (features/house-numerals hn19) | 5822 bytes after the image, plus 988 unused inside it (0x93A7..0x96FF and 0x977D..0x97FF: the fixes' standalone slots, which an image that includes them leaves as 0xFF) and 25 at 0x7DBA..0x7DD2 (the end of the stock big font's area, below) |
| EEPROM area, 0xF400..0xFDFF | 2560 bytes, 5 sectors of 512 | sectors at offsets 0x0000, 0x0200, 0x0400 | 2 sectors, 1 KB |
| Internal direct RAM, 0x00..0x7F | 128 bytes | all (registers, bit flags, variables up to 0x7F) | none |
| Internal indirect RAM, 0x80..0xFF | 128 bytes | stack from 0x88 (`mov SP,#0x88` at 0x44A5) | stack headroom only |
| External RAM (XDATA) | 2 KB by chip naming, not measured | page 0 (0x0000..0x00FF): display cell buffers, locals | ~1.7 KB from 0x0100 |

The stock big font (`font_big_32x30`, 0x6A23..0x7DD3, 5040 bytes) is dead in house-numerals
since hn17 and in phosphor-panel: `big_text_render`'s hook goes straight to the theme's name
painter and the stock number painters are unreachable, so the theme keeps its own data there
(house-numerals 5015 bytes of fonts, phosphor-panel 4520 bytes: the status and icon fonts and
the cell map; `features/house-numerals/README.md`, "Memory"; the tests trap `big_glyph_paint`
and `bignum_digit` on every run). Phosphor Panel pp4 ends at 0xDC34 (56373 bytes); its
dot-matrix name font alone is 9711 bytes, three times the plain face, because the grid breaks
the run-length runs every third row. The stock small font (0x5DAB..0x6A23, 3192 bytes) is still drawn
by the menus, the Treble and Bass pages and the RESET page; drawing those with a theme font
(mono16 and mono28 cover every firmware string but `W` and `+`) would free it too.

Rules of thumb: new code appends after the existing patch area (0x9400 upward); new
state goes in XDATA, preferably 0x0100..0x0400 so it is safe even if the XRAM size
assumption is wrong; new settings can use the two free EEPROM sectors. Rough cost of the
features discussed so far: screen-off re-arm 14 bytes (built, fix-auto-off); power-on volume cap 23 bytes
(built, start-volume); volume keys without a signal 24 bytes (built, fix-volume-pop); menu input switch 23 bytes (built, fix-menu-input); a settings menu layer ~270 bytes once and ~45 per setting (sketched in
`docs/menu-system.md`); status-line redraw skip ~40 bytes
+ 26-byte XDATA buffer; backlight PWM a few hundred bytes + menu + 1 EEPROM byte; HDMI
auto-switch ~60 bytes. Space is not the limit; the hand-assembled hook method and the
emulator coverage are.

## Display flicker on the input name (stock bug, present since v1.1)

Symptom: a one-cell-wide strip (~14 px) of a big input-name letter goes dark for a few
milliseconds, occasionally, on optical/coax. Two videos show it on the C of OPTICAL and
on the second A of COAXIAL: in each case the strip sits directly above the small-font
cell of the status line ("44.1kHz", "No signal") being written at that moment, and it
recurs at the status line's 500 ms refresh when a stream is playing.

Code facts: the status line is fully re-rendered on each refresh (margin cells cleared
by 0x5119, glyphs painted by 0x2DF8 in 14 x 24 windows, renderer 0x3A53); the big line
(renderer 0x298B, glyph painter 0x3F3C, 30 x 32 windows, glyphs stored rotated at
0x6A23 + index * 0x78) is not redrawn then; all small-line windows lie in their own
column band; no interrupt touches the LCD's 8-bit parallel bus (data P1, control P0.3 /
P0.5 / P0.7, one byte per chip-select pulse). The Pro build has the same display code.
So the code never addresses the big line; the disturbance is a panel/interface
transient. Root cause needs a logic analyser or test builds.

Workaround that removes the trigger: skip the status-line render when its text and
position are unchanged since the last render (shadow copy in XDATA). Not yet built.

## AO300 PRO firmware (V1.2, package AO300PROFW20260507)

Same MCU, same clock and EEPROM split, and the same codebase with eARC additions. The
package ships a plain Intel HEX of the image next to the updater (identical to the
updater's payload). The updater is a newer STC-ISP build (6.96A) whose cipher table sits
elsewhere; `stc_release.py` now locates the table by search, so it unpacks both.

Differences from AO300 v1.4: eARC with a CEC on/off menu (different HDMI receiver, not
portable), an `AT+GETCODEC` query to the Bluetooth module (the Pro transmits on UART1,
the AO300 never does), and the fix named in SMSL's note: with Dimmer set to Auto OFF,
the screen-off countdown was not armed after a power-on, so the display stayed lit until
the next key press. The AO300 v1.4 code has the same omission (the countdown at RAM
0x2F:0x30 is only armed inside the key dispatcher; the power-on routine at 0x5585 ends
without arming it). The Pro arms it at the end of its post-power-on routine. The IR
command table is identical, so no new remote codes exist.

Backported in `features/fix-auto-off`: post_power_on's tail (0x55B9) arms the countdown
to 500 when RAM 0x29 == 2, the same value a key press loads. In the emulator the bug only
shows after a cold power-up. Entering standby with the remote's Power key goes through the
key dispatcher, which arms the countdown; it freezes in standby and drains after the next
power-on, so stock times out there too.

## Open questions

Things still worth investigating to complete the picture of what the MCU code can do.
`docs/probing-plan.md` has the plan for finding out on the amp: a read-only probe build
first (`features/probe`; pr1 flashed on 2026-10-05, no dump captured yet), single writes after it.

- **HDMI auto-switch feasibility.** The ARC receiver's signal-present line reaches the
  MCU through expander pin 0x1C and is already polled for the status display. The first
  probe dumps of 2026-10-05 read it high on Optical and on HDMI with the TV in standby
  and on, while the screen said "Digital Input" throughout, with a brief "Disconnected" as
  the TV woke: the line is the ARC link, which the TV keeps up in standby, not audio
  activity. An auto-switch on it would switch to HDMI whenever the TV is plugged in. An
  activity signal exists: with HDMI selected, the receiver's register 0x7D read 0x00 with
  the TV in standby, 0x10 with the TV on and muted, 0x50 with ARC audio arriving, and
  nothing else in the dump moved; and on Optical it read 0x00 with the TV muted and 0x60
  with the TV playing; but by the PCM9211 datasheet 0x7D samples the pin levels of its AUX
  output port, toggling clock and data lines, and the seventh dump read the bit 0 with ARC
  playing: those matches were chance, and no ARC activity indicator exists on Optical
  (`docs/bus-map.md`, "Hardware read-back"). What does exist: the HDMI receiver's S/PDIF
  output is wired to the receiver's RXIN3, and on USB and AUX the firmware parks the DIR
  there, so register 0x39 reports lock and rate when ARC audio arrives, with no write. An
  auto-switch from USB or AUX is therefore a read-only poll. Better, and settled by probe
  pr3 on 2026-10-05 (`docs/bus-map.md`, "Layer 3, item 1"): the receiver's sample-rate
  calculator, pointed at the HDMI receiver's I2S port with one register write outside the
  audio path, reports 44.1 kHz from Optical whenever the TV is awake (muted or playing) and
  no result when the TV is in standby. "TV on" is readable from any input; an auto-switch to
  HDMI can poll it every tick at under 1 ms of main-loop time, with the target restored
  before stock's own read of the result register on Bluetooth, and left alone on HDMI.
  Built as `features/auto-switch` stage 1 (the HDMI activation, a 1 s hold-off, no switch
  away from a playing input); the TV wake confirmed on the amp on 2026-10-05. Bluetooth
  stays out: its module is off on the other inputs, and keeping it on would let phones
  reconnect on their own.
- **Pin roles on the board.** `docs/bus-map.md` lists every expander and MCU pin the
  firmware drives or reads, with roles inferred from when they change. Matching them to
  the silkscreen nets (MUTE_AMP, MUTE_PRE, MUTE_HP, DIR_RST, DAC_MCK_SEL, relays) needs a
  board photo or a meter. Still needed before touching power sequencing.
- **Clock generator.** The chip at I2C 0xC0 (Si5351 register layout): which part, which
  crystal, and what its output clocks. Its status register read 0x71 on the amp: by the
  Si5351 datasheet, crystal present and PLL A unlocked. Either the part reports status
  differently or the output it is programmed for is not what runs the audio.
- **DAC bits stock never sets.** Register 0x090000 bit 0 and bit 1, the PCM volume
  registers 0x090001/0x090002 and the path controls 0x090003/0x090004: check each against
  the CS43131 datasheet before a patch uses it (digital volume, de-emphasis).
- **PCM9211 confirmation.** Verify the receiver identity (register 0x38/0x39 semantics
  match the datasheet) and whether the ARC receiver's output also passes through it.
- **HDMI ARC receiver part number.** Still unreadable in photos; a close-up of the QFP-48
  next to the HDMI socket would settle it and its status-pin behaviour.
- **Backlight drive.** What P0.6 connects to (transistor, resistor, or driver enable).
  Determines whether software PWM dimming is viable; listen for audio buzz in any test.
- **UART1 message values.** A message is two bytes and a 0xFF terminator: format class,
  then rate index 1..12 (`uart1_isr`, `xmos_format_take` 0x408B). The meaning of each class
  and index is in the jump tables after 0x408B and still to be tabulated.
- **Key handlers, resolved in the emulator.** 0x1047 (key 0x1C, NEC 0x09) is the mute
  toggle (it goes home first; it runs on page 1 only: in a menu `dispatch_key` turns the key
  into "home" at 0x0C23, and on the volume page `read_key` does at 0x3DD6, so there the key
  closes the page without muting; house-numerals hn14 changes both, see its README), 0x10BE (key 0x14, NEC 0x08) toggles Dimmer, 0x106D (key 0x0A, NEC 0x0E) is "BT
  Reconnect", 0x10E1 (four-press combo 0x38) is "BT list clear", 0x0F62 (key 0x59) steps
  the EQ. None is a hidden service function.
- **Pop on an input change through the menu.** Heard on the amp on 2026-10-02 (the `d39d321c…`
  build; stock code). `input_menu_select` (0x588B), unlike the Source key, mutes by register only, sets
  P4.0 low for 3 s and then runs `expander_init` and `audio_chips_init` again (main loop,
  0x3375, countdown 0x41:0x42). The speaker mute pin P2.2 stays low until the very end of
  that, and on the digital inputs the format poll opens the NJW1194 and the DAC again about
  0.5 s after Enter, so the supply returns and the chips are reset with the path open. What
  P4.0 powers, which of these moments is the pop, and why SMSL cycles the supply here are not
  known. The path also leaves expander P0_4 (inferred: the Bluetooth module's clear-pairings
  line) low afterwards; whether that matters on the amp is untested (`docs/bus-map.md`).
  `features/fix-menu-input` takes the whole cycle out; if an input ever needs it, that is where
  it will show.
- **Pop at power-off.** A small pop on the Power key, heard on the amp on 2026-10-02 (hn16), the
  same at volume 0 and with the mute key on; the mute key itself is silent. With mute on, the
  only pins power-off moves are the supply enables: P4.4 low, then P0.0 and P4.0 low 100 ms
  later; P2.7 stays low, so the speakers stay connected. So the pop comes with the supplies
  going. Whether stock pops too is not known. One difference from stock: fast-lcd's quick
  clear shortens the time from the amp mute (P2.2) to P4.4 low from 150 ms to 11 ms, which
  cannot be the whole cause, since the pop is there when the amp was muted long before.
  Tried on the amp the same day: with Output on Headphones (P2.7, P2.5 and P2.2 high) the
  speakers pop at power-off just the same, and the switch to Headphones itself is silent. So
  P2.7 does not take the speakers off the amplifier, and no pin the MCU drives is known to.
  What is left is the order and spacing of the supply enables, which should not be changed
  before the supplies are identified on the board. A build that holds P0.0 and P4.0 for 2 s
  after P4.4 would at least tell which step pops; the amp is in that state for 5 s at every
  power-on (`docs/bus-map.md` has the order).
- **Which part makes the volume-key pop.** On Optical or Coaxial without lock, stock's first
  volume key sets P2.7 and P2.2 and opens the NJW1194 for a tick (`features/fix-volume-pop`
  removes all three). Which of them is audible is not known; it would tell P2.7's and
  P2.2's roles apart. A test build that does one at a time would answer it.
- **Volume key during the unmute countdown.** On Optical and Coaxial with lock, every volume
  key runs `unmute_now` (0x5A5E) first. Pressed while the unmute countdown 0x43:0x44 still
  runs (the last 2 s of a power-on, the 1 s after a stream locks), it unmutes at once, up to
  1.9 s early in the emulator, right after the DAC setup. On USB, Bluetooth and AUX the key
  only writes the volume and the mute holds. Stock behaviour, not reported as audible, and
  not changed by fix-volume-pop.
- **A key lost to the settings save (stock race).** Found in the emulator on 2026-10-02, not
  yet looked for on the amp. `settings_save_eeprom` (0x492B) starts with `lcall ir_cmd_clear`
  (0x5DA1: `g_ir_cmd` 0x6A = 0) and leaves the new-command bit 0x20.4 alone. It runs from the
  main loop (0x3446) when the save countdown 0x37:0x38 runs out, 50 main ticks after a setting
  change such as a volume step. A command whose last bit `nec_decode` takes in that one
  main-loop pass, after `read_key` tested 0x20.4 (0x3DA4) and before the clear, keeps its bit
  and loses its code: the next pass looks up command 0, which is 0xFF in the table at 0x9398.
  On the volume page `read_key` turns that into key 0x15 at 0x3DD6, so the page closes and the
  volume does not step; on the other pages 0xFF is no key and the press does nothing (read from
  the listing, not run). Shown with whole NEC frames sent through the INT0 handler, on the
  stock image as on hn16. On hn16 a second Vol+ whose last edge comes 0 to 760 clocks into the
  save's tick goes home; 20 clocks before the tick or 800 into it, the volume steps (stock: the
  same at 100-clock steps). Nothing in the decoder's state guards it (`g_ir_state`,
  `g_ir_repeat_cnt`, the release timer 0x34), so `Amp.press`, which sets only 0x6A and the bit,
  shows the same thing. The window is the part of that pass before the save: 32 us when the
  pass is otherwise idle, and 2.9 ms when the 100 ms format poll (inputs 1..5, I2C) falls on
  the same tick, as it does on fast-lcd for a Vol+ 9.0 s after Power. The save comes 0.67 s
  after the Vol+ on stock (the volume page's draw swallows ticks), 0.52 s on fast-lcd and 0.50
  s on hn16. So on the amp it takes a second key about that long after the first, timed to
  within 32 us, or 3 ms on a format-poll tick: rare, and it would look like a remote glitch.
  Not known: why stock clears the command there, whether it has ever happened on the amp, and
  what the erase itself costs. STC's IAP is believed to hold the CPU while it erases and writes
  (milliseconds for a sector erase; not checked against the STC8G manual, and `Amp` does it in
  no time), and `eeprom_write` masks interrupts per byte, so a frame under way then may lose
  edges and be dropped by the decoder. A fix would replace the call at 0x492B with one that
  keeps a pending command.
- **Power-on sequence timing.** The delays in `post_power_on` (0x5585), `audio_chips_init`
  (0x50D1), 0x24D6 and 0x5D66 govern switching speed and the click that SMSL fixed once;
  worth tabulating if faster switching is wanted. (0x5AAB, named here before, has no delay:
  it only rewrites EEPROM sector 0.)
- **Input-name flicker root cause.** See the flicker section: the code never writes the
  big line during status refreshes, so the transient is at the panel/interface level.
  Candidates: chip-select toggled per byte on the 8-bit bus, or writes landing during
  the panel's own refresh. A logic analyser on P0/P1, or test builds that change the
  byte strobe sequence, would settle it. The redraw-skip workaround sidesteps it.
- **XRAM size.** 2 KB assumed from the part name; confirm before placing buffers above
  0x0400.
- **Audio level metering.** The MCU sees no audio level today. The stock firmware never
  touches the ADC registers (ADC_CONTR 0xBC, ADC_RES/ADC_RESL 0xBD/0xBE, ADCCFG 0xDE),
  and no chip on the audio path reports one: the NJW1194 bus is write-only, the CS43131
  and PCM9211 are only configured or read for ID / sample rate, the MA5332MS has no
  interface, and the XMOS messages carry format only. The one level-like input is the
  binary signal presence per input (0x5232). A meter would need a hardware tap (rectifier
  + RC envelope from an analogue node such as the NJW1194 output) into a spare MCU pin.
  Open: whether the STC8C2K64S2 has an ADC at all (datasheet), and which pins are free
  (see the expander pin map).

## Key facts about the firmware

- Container obfuscation: fixed-key byte cipher, key 0x4C, permutation table inside the
  updater. Records are `0x70, type, u16 checksum, u32 length, data`; the checksum is the
  negated byte sum. Record 0xFF is the flash image.
- IR path: NEC decoder in the INT0 handler (0x2681) stores the command byte at RAM 0x6A;
  `ir_cmd_to_key` (0x5D10) maps it through the 15-byte table at 0x9398; the dispatcher
  (0x0BB4) switches on the result through a Keil switch helper at 0x2072. The decoder times
  the falling edges with Timer1, checks the address bytes 12 34 and sets bit 0x20.4 for
  `read_key`. A held Vol+, Vol-, Up or Down sets the bit again on every repeat code but the
  first. NEC 0x08 acts on release (200 ms after its last repeat, `inject_key_08`) and becomes
  0x0E at its tenth repeat. 300 ms after the last frame or repeat the Timer0 ISR clears 0x6A
  (0x34, 0x3EAC), which ends the repeats.
- Inputs live in RAM 0x47 (1..6); `input_apply` (0x5640) switches the hardware via
  `input_set_hw` (0x24D6) and saves the setting to EEPROM.
- Power flag is RAM 0x4F (0 = standby). Source on the remote while in standby resets the
  MCU into the STC bootloader.
- The updater sends no download password and uses no user key, so stcgal's `stc8d`
  protocol can also talk to the chip. The official updater is still the safer flashing
  route because it reprograms the same option bytes and clock trim every time.
- Flash can't be read back over ISP; `original/extracted/flash.bin` is the only copy of
  the stock image, so keep it.
