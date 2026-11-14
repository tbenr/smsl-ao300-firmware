# Development

How the repository is laid out, and how to build, test and flash an image by hand. To put
the firmware on an amp, [install.md](install.md) is enough. The rules for working here are
in [AGENTS.md](../AGENTS.md).

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
`KNOWN_IMAGES` in `tools/flash/flash_ao300.py`); every address in these docs and in the
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

## Layout

Firmware is not in this repository. The vendor updater, the extracted and patched images
(`*.bin`, `*.exe`, `*.hex`), the stock disassembly `flash.asm`, the Ghidra project and
all `build/` outputs are ignored by git. "Workflow" above recreates them.
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
  flash/flash_ao300.py            guarded stcgal-based flasher for macOS/Linux ("Flashing by hand")
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
                                  self-tests it (see "Release bundle")
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
  patch/uikit.py                  shared building blocks for UI themes (docs/ui-kit.md)
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
tests, the integration tests (below) and the UI kit's test at once, on
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
is lost to a stock race, see `docs/open-questions.md`; a wait of whole ticks ends just after a Timer0
tick, inside the window, so in a scenario this is not rare but certain. Keep presses off that
tick unless the race is what the test is about.

`Amp` has no EEPROM: reads return 0, so the emulated amp boots into standby with every
setting at its clamp. Tests seed single reads through a hook on 0x5970 (fix-auto-off), or
model the whole EEPROM behind the stock IAP routines (start-volume: read 0x5970, write
0x58AF, erase 0x59D0), which also makes a cold power-up turn the amp on by itself, as the
real one does.

`stc_release.py rebuild` output was verified by unpacking it again and by checking the
PE structure with `pefile`. Only the firmware resource differs from the vendor updater.

### Integration tests

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

## Flashing by hand

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

## Release bundle

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
to start and validate its image there on 2026-09-28 (`docs/status.md`); no flash through a
rebuilt updater is on record.
Every answer has a flag (`--theme`, `--set FEATURE.OPTION=VALUE`, `--port`, `--action`,
`--build-only`), so the wizard also serves as a one-line build tool. The bundle
`ao300-custom-1c4dbd4-dirty-20261011` was run on a Linux machine on 2026-10-11 and worked
end to end (the user's report). When several ports are listed, the wizard proposes the only
known adapter among them (a CH340 next to an Arduino, say).

## Version string

The RESET menu page shows `v1.4 tbenr ds4` instead of `v1.4`. Change `VERSION_TEXT` in
`build_patch.py` to alter it; the row fits 20 characters.
