# Development

How the repository is laid out, and how to build, test and flash an image by hand. To put
the firmware on an amp, [install.md](install.md) is enough. The rules for working here are
in [AGENTS.md](../AGENTS.md).

## Requirements

- Python 3.8 or newer.
- `pefile` for the container tools (`tools/pe/stc_release.py`).
- `stcgal` 1.10 for the flasher (`tools/flash/flash_ao300.py`); it pulls in `pyserial`. Both
  are pinned in `requirements.txt`.
- A USB-C data cable to the amp. The amp's USB socket carries the serial port the flasher
  uses (the computer sees a CH340) as well as USB audio.
- The disassembler, the patch builder and the emulator tests need only the standard
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

`./install.sh` creates the same `.venv` from the same `requirements.txt`, so either way works.

Activate it (`source .venv/bin/activate`) in every new shell before running the commands
below; `python3` then resolves to the venv's interpreter. `deactivate` leaves it. The
`.venv` folder is local and can be deleted and recreated at any time.

Do not run the tools with `sudo`: it resets the environment, so `python3` becomes the
system interpreter and the venv's packages are missing. On macOS the serial device is
world-writable and no elevation is needed. On Linux, add yourself to the serial group
once instead (`sudo usermod -aG dialout "$USER"`, `uucp` on Arch) and log in again. If
elevation is ever unavoidable, call the venv interpreter by path, which works without
activation: `sudo .venv/bin/python tools/flash/flash_ao300.py ...`.

## Workflow

Firmware is not in this repository and never goes into it (see [AGENTS.md](../AGENTS.md)).
Get SMSL's updater `SMSL_AO300_UPDATE_VER0A5_EN.exe` ([install.md](install.md), "Getting
SMSL's updater", says where it was published and gives its sha256) and put it in `original/`,
which git ignores. Then extract the stock firmware, using the file's name as you saved it:

```bash
python3 tools/pe/stc_release.py unpack original/SMSL_AO300_UPDATE_VER0A5_EN.exe original/extracted
```

The extracted `flash.bin` must have sha256 `85e8ac50ffcf47ea…` (full value in
`KNOWN_IMAGES` in `tools/flash/flash_ao300.py`); every address in these docs and in the
patches refers to that image. "Stock v1.4" in these docs always means this image: other AO300
firmwares also show `v1.4` on the RESET page (a "factory 1.4" updater posted in the same
forum thread carries a 35972-byte image, this one is 37799 bytes). `tools/build.py` stops with a message when it is missing.

Disassemble it, if you want the listing:

```bash
python3 tools/disasm/d51.py original/extracted/flash.bin original/extracted/flash.asm 106d 0fc8 10fc 0f93 1006 10be 0ce9 0d03 0ed2 1047 0cd2 10e1 0f62 0d83 0e2a 144e 126f 135a 14e3
```

The trailing addresses are the key handlers reached only through the dispatcher's
inline switch table, which the disassembler cannot follow on its own.

Build every feature image (bases first), then test them all:

```bash
python3 tools/build.py
python3 tools/run_tests.py
```

`python3 tools/build.py house-numerals` builds only that image and the ones it stacks on.

### Windows updater

An image can be packed into a copy of the vendor updater, to flash from Windows:

```bash
python3 tools/pe/stc_release.py rebuild original/SMSL_AO300_UPDATE_VER0A5_EN.exe features/direct-select/build/flash_patched.bin features/direct-select/build/SMSL_AO300_UPDATE_VER0A5_EN_directselect.exe
```

The installer's menu does the same for the image it built (`--action exe`, output in
`build/out`). `rebuild` output was verified by unpacking it again and by checking the PE
structure with `pefile`: only the firmware resource differs from the vendor updater. It is
used exactly like the vendor one: connect the amp, click the start button, then put the amp
in standby and press Source on the remote, or power it up from cold. It needs Windows, real or
in a VM with the amp's USB serial port passed through.

A rebuilt updater contains SMSL's program and firmware code. It is for your own amp: do not
share it, and it never goes into git or into a bundle. A hand-made one was confirmed to start
and validate its image on Windows; no amp has been flashed through one
([status.md](status.md)).

## Layout

Entries marked * exist only locally: git ignores them, and "Workflow" above recreates them.

```
original/                       * the vendor updater and what was extracted from it
  extracted/flash.bin           * stock firmware image (37799 bytes, loads at 0x0000)
  extracted/flash.asm           * its disassembly (d51.py output)
ghidraPRG/                      * Ghidra project (import flash.bin as 8051:BE:16:default,
                                  block CODE at 0)

install.sh                      one-step installer: venv, dependencies, then the wizard
docs/                           install guide, this file, hardware and research notes
docs/internal/                  * local notes, not for the repository

tools/
  build.py                      builds every feature image in dependency order and checks
                                them; --graph prints the feature tree
  run_tests.py                  builds, then runs every test in parallel
  release.py                    packs and self-tests the bundle, dist/ao300-custom-*.zip
  installer/                    the wizard (ao300_installer.py), port detection, stock
                                detection, its tests
  flash/flash_ao300.py          guarded stcgal-based flasher ("Flashing by hand")
  flash/ser2net/                ser2net in Docker: reach the amp's serial port from another
                                computer as rfc2217://
  pe/stc_release.py             unpack / repack / rebuild the updater's firmware container
  disasm/d51.py                 small recursive 8051 disassembler
  disasm/SmslAo300Labels.java   Ghidra script that names routines, globals and tables
  patch/asm51.py                label-resolving 8051 assembler used by the build scripts
  patch/features.py             the feature graph: BASE, INCLUDES, CONFIG
  patch/uikit.py                shared building blocks for UI themes (ui-kit.md)
  patch/uikit_test.py           the kit's own emulator tests, on fast-lcd + the kit
  patch/pfont.py                proportional fonts for uk_text, packed from tools/fonts/raster
  fonts/                        the themes' typefaces as glyph rasters, the font bench
                                server and the shared rasteriser glyphs.js (see its README)
  emu/emu8051.py                8051 emulator with STC8 clock counts and an ST7789 model of
                                the LCD bus (renders the screen to PNG); the Python reference
  emu/core8051.c, cemu8051.py   the same emulator in C, loaded through ctypes and compiled
                                on first use; what Emu8051() runs, about 100 times faster
  emu/test_core.py              differential test: C core against the Python reference
  emu/ao300.py                  harness: boot the whole firmware, press remote keys, log
                                audio-chip writes and pins per 10 ms tick
  emu/i2c.py                    I2C slave model for the harness: the chips answer, and
                                every transfer is logged with its call site
  emu/bus_trace.py              runs stock through every input and setting and prints the
                                registers and pins it touches (source of bus-map.md)
  emu/panel_video.py            60 fps video of what the glass shows (needs ffmpeg)
  emu/uitest.py                 shared helpers for UI tests

features/                       one folder per feature
  direct-select/                fix: input selection and power over IR
  fix-auto-off/                 fix: Dimmer Auto OFF also times out after a cold power-up
  fix-menu-input/               fix: an input chosen in the menu, without the supply cycle
  fix-volume-pop/               fix: no pop from the volume keys without a signal
  start-volume/                 fix: the volume at power-on capped at build-time limits
  strings/                      fix: stock texts corrected in place
  fast-lcd/                     the stock UI through a faster pixel path; the themes' base
  house-numerals/               theme: large numerals, a sliding volume page
  phosphor-panel/               theme: a VFD look
  ui-theme/                     the themes' design mock (ui_themes.html)
  auto-switch/                  experimental: to HDMI when the TV comes on
  probe/                        research: a read-only register dump on the FN button
  status-line-flicker/          analysis of a stock display bug (no build)
```

A feature folder holds `build_patch.py` (builds `build/flash_*.bin` *), the generated
listing `<name>.asm`, `emu_test.py` and `README.md`. A fix also has `<name>.py` with `HOOK`
and `emit(a)`, so other builds can include it.

## Feature graph

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
├── auto-switch             'v1.4 tbenr as4'    0xF000..0xF202  8e0602f5… known  [fix, hook 0x3438; included by none yet]
│     + direct-select       fix linked into auto-switch
│     + fix-auto-off        fix linked into auto-switch
│     + strings             fix linked into auto-switch
│     + start-volume        fix linked into auto-switch
│     + fix-volume-pop      fix linked into auto-switch
│     + fix-menu-input      fix linked into auto-switch
├── direct-select           'v1.4 tbenr ds4'    0x9400..0x9473  4b5dcfce… known  [fix, hook 0x5D10; included by auto-switch, house-numerals, phosphor-panel, probe]
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
├── fix-auto-off            'v1.4 tbenr aof3'   0x9680..0x969D  1fb64470… known  [fix, hook 0x55B9; included by auto-switch, house-numerals, phosphor-panel, probe]
├── fix-menu-input          'v1.4 tbenr mi1'    0x9650..0x9675  693bdef6… known  [fix, hook 0x5892; included by auto-switch, house-numerals, phosphor-panel, probe]
├── fix-volume-pop          'v1.4 tbenr vp1'    0x96D6..0x96FC  e2075861… known  [fix, hook 0x0F4A, patch 0x0D0F, patch 0x0D8F, patch 0x0E36, patch 0x0EDE; included by auto-switch, house-numerals, phosphor-panel, probe]
├── probe                   'v1.4 tbenr pr5'    0xF100..0xF37F  0fc654e4… known  [fix, hook 0x3DA9; included by none yet]
│     + direct-select       fix linked into probe
│     + fix-auto-off        fix linked into probe
│     + strings             fix linked into probe
│     + start-volume        fix linked into probe
│     + fix-volume-pop      fix linked into probe
│     + fix-menu-input      fix linked into probe
├── start-volume            'v1.4 tbenr sv1'    0x96B0..0x96D5  50ad4119… known  [fix, hook 0x5596; included by auto-switch, house-numerals, phosphor-panel, probe]
│     = config              HEADPHONE_LIMIT 0..60 (default 20), SPEAKER_LIMIT 0..60 (default 25)
└── strings                 'v1.4 tbenr str3'   0x96A0..0x96AF  6c5611ad… known  [fix, patch 0x91ED; included by auto-switch, house-numerals, phosphor-panel, probe]
```

Stacking (BASE) is for code that changes how the stock UI is drawn: fast-lcd on stock, a
theme on fast-lcd. The two themes both stack on fast-lcd and both put their code at 0x9800:
they are alternatives, never in one image, so the slot warning `tools/build.py` prints for
them is expected. Everything else is a fix on stock, with its own small standalone image,
and is linked into the image meant for the amp through INCLUDES. House-numerals then
depends on fast-lcd (its base, and so on down to stock) and on direct-select, fix-auto-off,
strings, start-volume, fix-volume-pop and fix-menu-input (included). An image has exactly one BASE, because
images stack, but can include any number of fixes. Including a fix uses the fix's source, not
its standalone image; that image stays a separate branch of the tree, and a change to a fix
only moves the shas of the images that include it.

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

## Build-time configs

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

## Testing

Every feature has an `emu_test.py`. It runs the patched image in the emulator
(`tools/emu/emu8051.py`), which executes the stock routines with clocks counted from the STC8
instruction table and decodes the LCD bus into an ST7789 model that can be saved as PNG. Each
test covers the new behaviour at the hook, a sweep of all 256 IR commands against the base
image in every power and page state the patch reads, and an image diff limited to the bytes
the patch is meant to change. [AGENTS.md](../AGENTS.md) has the rules.

`python3 tools/run_tests.py` builds every image (`tools/build.py`), then runs all the feature
tests, the integration tests (below), the UI kit's test and the installer's test at once, on
the C core, in about 3 minutes; most of that is the two themes' 256-command sweeps.
`python3 tools/run_tests.py uikit` runs only the kit's test (about 3 s), and a feature's name
runs only that feature's jobs. The Python reference (`EMU8051=py`) gives the same results
about 100 times slower. After changing the emulator, `python3 tools/emu/test_core.py` checks
the C core against the Python reference: every opcode from random states, random programs,
and a boot scenario of the stock firmware compared at every 10 ms tick.

Without the stock image nothing builds, so only `tools/emu/test_core.py --no-firmware` and the
parts of `tools/installer/test_installer.py` that do not need it can run.

### Whole-firmware scenarios

Scenarios run on `Amp` (`tools/emu/ao300.py`), which boots the firmware from reset and fires
both timer interrupts stock enables: the Timer0 ISR every 10 ms and `timer3_isr` (0x5040)
every 0.5 ms, on one grid with Timer0 first when both are due. Timer3 matters. Without it the
encoder key 0x2D stays 0 instead of 0xFF, and `read_key` hands `dispatch_key` a phantom key 0
on every idle main-loop pass on every powered page; among other things that re-arms the Auto
OFF countdown 0x2F:0x30 (0x0BBD) on every pass, which hides the bug fix-auto-off fixes.

With Timer3 the idle home page makes about 280,000 main passes a second. A test hook on a
per-pass address (such as house-numerals' wipe watcher on 0x5B2D) is therefore expensive: arm
such hooks only while they are needed. The ISR takes about 131 clocks every 12,000, about 1%
of the CPU, and costs about 7% of emulator time. The deepest stack in the house-numerals tour
is 0xB3: stock's own delay leaves at SP 0xA0 with `timer3_isr`'s frame on top.

`Amp.press` sets what a finished frame leaves for the main loop: the command in 0x6A and bit
0x20.4. It does not run the decoder, so the release timer 0x34 is not armed and 0x6A keeps the
command until the next press or settings save. A press on the tick of a settings save (50 main
ticks after a setting change: 0.50 s after a Vol+ on house-numerals, 0.52 s on fast-lcd, 0.67 s
on stock) is lost to a stock race, see [open-questions.md](open-questions.md); a wait of whole
ticks ends just after a Timer0 tick, inside the window, so in a scenario this is not rare but
certain. Keep presses off that tick unless the race is what the test is about.

`Amp` has no EEPROM: reads return 0, so the emulated amp boots into standby with every
setting at its clamp. Tests seed single reads through a hook on 0x5970 (fix-auto-off), or
model the whole EEPROM behind the stock IAP routines (start-volume: read 0x5970, write
0x58AF, erase 0x59D0), which also makes a cold power-up turn the amp on by itself, as the
real one does.

### Integration tests

Byte checks can't tell whether an included fix still works in its new image, for example
because it jumps into stock code another layer changed. Integration tests check that
instead: a layer has to keep working in the final image. A feature whose
`emu_test.py` sets `INTEGRATION = True` also accepts `--in <feature>`. With it, the test
checks, in that feature's image, what must stay true wherever it is built on or included.
`run_tests.py` runs it for every image that contains the feature, as jobs such as
"direct-select in house-numerals" and "fix-auto-off in house-numerals":

- direct-select: the six input commands, the two power commands (on the whole firmware:
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

## Flashing by hand

[install.md](install.md) is the guide for putting an image on an amp; this section is the
flasher underneath it. Never start anything that opens the serial port without the person at
the amp ready for it (see [AGENTS.md](../AGENTS.md)).

`tools/flash/flash_ao300.py` wraps [stcgal](https://github.com/grigorig/stcgal) and
refuses to write unless the chip reports exactly what a factory AO300 reports: magic
0xF7DC, bootloader 7.2 or newer, 24 MHz clock, option bytes `FF BF BC F7 F4`, code area
ending at 0xF400, no download password, and bootloader pin detection off. Those values
were read from a real amp and match the vendor container. Options are written back
unchanged; the clock is calibrated to 24.000 MHz like the vendor tool does. It checks the
image too (size, reset vector) and says whether its sha256 is in `KNOWN_IMAGES`.

```bash
python3 tools/flash/flash_ao300.py -p PORT identify     # read-only
python3 tools/flash/flash_ao300.py -p PORT dryrun       # read-only, full handshake
python3 tools/flash/flash_ao300.py -p PORT flash features/house-numerals/build/flash_house_numerals.bin
python3 tools/flash/flash_ao300.py -p PORT recover original/extracted/flash.bin
```

`PORT` is the amp's serial device: `/dev/cu.usbserial-XXXX` on macOS (`ls /dev/cu.usbserial*`),
usually `/dev/ttyUSB0` on Linux. When the flasher says "Waiting for MCU", put the amp in
standby and press Source on the remote, or unplug and replug the mains. `flash` asks you to
type FLASH first, before it waits for the bootloader, so there is no pause between the
handshake and the erase; `-y` after the image path skips the question.

- **The port vanishes mid-run on Linux** (`Errno 5`): check `dmesg` for brltty or
  ModemManager grabbing the CH340.
- **The amp is on another computer.** `-p` also takes a pyserial URL such as
  `rfc2217://host:4000` (stock stcgal opens device paths only; the flasher routes URLs
  through `serial_for_url`). `tools/flash/ser2net/` has a ready-made ser2net setup in Docker.
  The switch to 115200 baud travels as an RFC 2217 control command and works through it.
- **A flash fails after the erase.** The amp has no firmware until `recover` is run from a
  cold power-up; the bootloader is in ROM and survives.
- **The log.** Every run is appended to `tools/flash/flash_ao300.log`, with raw packets when
  `-D` is given. It holds the chip's unique ID and stays local.
- **The vendor updater against this flasher.** The updater sends no download password and
  uses no user key, which is why stcgal's `stc8d` protocol can talk to the chip. The vendor
  tool rewrites the option bytes and the clock trim from its own container every time; this
  flasher reads the chip first, checks it, and writes the options back unchanged.

## Release bundle

`tools/release.py` packs `dist/ao300-custom-<version>.zip` from a whitelist: `install.sh`,
`README.md`, `docs/install.md`, the licence and notices, the wizard, the build tools and, for
each theme the wizard offers, the code and data of the features it stacks on or links in. No
tests, no listings, no feature READMEs and never firmware: the script refuses to write
otherwise. It ends with a self-test that extracts the zip and builds both themes from inside
it. A clone of the repository works the same way as the bundle (`./install.sh`); the bundle
is the same thing without the development files. Bundles stay local, in `dist/`.

The wizard (`tools/installer/ao300_installer.py`) asks for the vendor updater (to be put in
`original/`), checks its sha, asks for the theme and for every build-time config the theme's
features declare, builds the image, finds the amp's serial port and runs
`tools/flash/flash_ao300.py` as a child process with the terminal attached (with `-y`: the
menu choice is the confirmation). It hard-codes no option name or default: a feature that
gains a `CONFIG` entry is asked for with no change to the wizard.

- **Trust in the build.** The wizard rebuilds the theme with its defaults (that sha must be
  in `KNOWN_IMAGES`) and checks that the user's image differs from it only in the configs'
  bytes (`features.config_diff`). The flasher then reports the image as "not a registered
  image", which the wizard explains.
- **Flags.** Every answer has one (`--theme`, `--set FEATURE.OPTION=VALUE`, `--port`,
  `--action`, `--build-only`), so the wizard also serves as a one-line build tool.
- **Ports.** When several serial ports are listed, the wizard proposes the only known USB
  serial chip among them (a CH340 next to an Arduino, say).
- **Windows updater.** The menu item "Make a Windows updater (.exe)" (`--action exe`) opens no
  port: it writes a copy of the vendor updater carrying the built image into `build/out`
  (`stock.rebuild_updater`, through `stc_release.rebuild_exe`), unpacks it again and requires
  the image back byte for byte. It needs the vendor `.exe` in `original/`. See "Windows
  updater" above for what may be done with the result.
- **Tests.** `python3 tools/run_tests.py installer` runs `tools/installer/test_installer.py`:
  the config API, port filtering, stock detection, the bundle's contents, and unattended
  builds of both themes checked against the default images.

## Version string

The RESET menu page shows the image's `VERSION_TEXT` instead of stock's `v1.4`: `v1.4 tbenr`
and a build tag, for example `v1.4 tbenr hn19`. Each `build_patch.py` sets its own, 20
characters at most, so the page always says which image is running. A new image gets a new
tag and a `KNOWN_IMAGES` entry; an image that differs only by build-time config values does
not ("Build-time configs").

## The screenshots in the README

`docs/images/*.png` are emulator renders of the built themes, written by the unit tests:

```bash
python3 features/house-numerals/emu_test.py unit    # build/unit_home.png, build/unit_volpage.png
python3 features/phosphor-panel/emu_test.py unit    # build/unit_home.png, build/unit_volume.png
```

Copy them to `docs/images/` under the names the README uses when a theme's look changes.

## Where each topic lives

Each topic has one home. Other files link to it and do not restate it.

| Topic | Home |
|---|---|
| What the firmware adds, the IR commands, the disclaimer | [README.md](../README.md) |
| Installing, flashing with the wizard, recovery | [install.md](install.md) |
| Build, test, flash by hand, the bundle | this file |
| Rules for changing anything | [AGENTS.md](../AGENTS.md) |
| What was verified on hardware | [status.md](status.md) |
| Hardware map, volume scale, memory budget, stock firmware facts | [hardware.md](hardware.md) |
| Registers and pins, read back from the amp | [bus-map.md](bus-map.md) |
| What is not known yet | [open-questions.md](open-questions.md), [probing-plan.md](probing-plan.md) |
| The stock menu's internals | [menu-system.md](menu-system.md) |
| The theme kit, sizing a home screen | [ui-kit.md](ui-kit.md) |
| How one feature works | `features/<name>/README.md` |
| Reaching the amp's serial port from another computer | `tools/flash/ser2net/README.md` |
| Fonts and their licences | `tools/fonts/README.md`, [NOTICE.md](../NOTICE.md) |
