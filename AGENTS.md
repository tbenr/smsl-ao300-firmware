# Working rules for this repository

Custom firmware for the SMSL AO300 amplifier's control MCU (STC8C2K64S2, 8051).
`README.md` is the page for users and `docs/install.md` their install guide;
`docs/development.md` explains how to build, test and flash by hand, and its last table says
where every other topic lives. These rules apply to anyone working here, human or agent.

## Firmware never goes into git

- **Never commit any firmware, original or custom.** That covers vendor updaters,
  extracted and patched images (`*.bin`, `*.exe`, `*.hex`), anything under `build/`,
  and the stock firmware in any other form. That includes its disassembly
  (`original/extracted/flash.asm` or any copy), the Ghidra project (`ghidraPRG/`), and
  dumps of its fonts or tables. `.gitignore` covers the known paths. Before every commit,
  check `git status` for new files of these kinds.
- Annotated listings of our own patch code (`features/*/*.asm`) are fine, as are short
  quotes of stock instructions in docs to explain a hook.
- The flasher log `tools/flash/flash_ao300.log` stays local. It holds the chip UID.
- Release bundles (`tools/release.py`, in `dist/`) and installer builds (`build/out/`) stay
  local too. A bundle never contains firmware: whoever installs it supplies the vendor
  updater.
- Nothing of one person's setup goes into tracked files: no home paths, host names, network
  addresses, device names of one machine or chip UIDs. Such notes, and working plans and
  specs, go in `docs/internal/`, which git ignores. No tracked file links into it.

## The amp

- Never start anything that talks to the serial port (`identify`, `dryrun`, `flash`,
  `recover`, plain stcgal) until the person at the amp says go. First say what the command
  does and what they must do at the amp: standby, then Source on the remote, or a cold
  power-up. When they flash from another machine, give the command and don't run it.
- Flash only through `tools/flash/flash_ao300.py`. Add every new image's sha256 to
  `KNOWN_IMAGES` with a one-line description. Never change the option bytes, the
  24 MHz clock target or the code/EEPROM split.
- Keep the recovery path intact. Don't touch the reset vector, the standby key handler
  (0x59B2), or `read_key`'s Source-in-standby jump to the bootloader (0x3DB8).
- Record something as working on hardware (`docs/status.md`; a feature README's Status
  section links to it) only after the person who flashed it confirms it, with the date and
  the image's sha. A report from someone else's amp is recorded as theirs.

## Building features

- All addresses refer to the stock v1.4 image, sha256 `85e8ac50ffcf47ea…`.
- One folder per feature: `features/<name>/` with `build_patch.py`, an annotated or
  generated `.asm` listing, `emu_test.py`, `README.md`, and outputs in `build/`.
- Every `build_patch.py` declares its place in the feature graph: `BASE` (the image it
  stacks on: another feature, or "stock"), `INCLUDES` (fixes it links in) and
  `BASE_IMAGE = features.image(BASE)` (`tools/patch/features.py`). Build with
  `tools/build.py`. It builds bases first and fails on stale pins, on a feature re-patching
  bytes an ancestor changed, and on an included fix whose hook isn't installed.
- Every feature and fix declares the XDATA its code uses (`XDATA = [...]`, empty if none);
  `tools/build.py` rejects overlapping declarations within one image.
- A feature whose behaviour must survive in images built on it or including it gives its
  `emu_test.py` an integration mode (`INTEGRATION = True`, `--in <feature>`). It checks only
  what must stay true there, not this layer's exact bytes.
- Fixes for stock bugs live in `features/fix-<name>/`. They export `HOOK` and `emit(a)` from
  `<name>.py` (dashes as underscores), so other builds can include them. Their own
  `build_patch.py` is a standalone image on stock.
- `build_patch.py` checks the base image's sha256 and asserts the original bytes at every
  hook before it changes them. Hooks use as few bytes as possible (an LJMP or a
  repointed branch). New code is appended after the current end of the patch area and
  stays below 0xF400. Data may also take a stock area the image provably no longer reads
  (house-numerals keeps fonts in the stock big font's place): the build asserts the stock
  bytes it overwrites, and the tests trap every stock reader of that area on every run.
- Internal RAM is full. New variables go in XDATA from 0x0100. Leave the EEPROM
  sectors in use (offsets 0x0000, 0x0200, 0x0400) alone.
- Each build sets its own `VERSION_TEXT` (20 characters at most), so the RESET page
  shows which image is running.
- **Build-time configs.** A feature may declare values that are safe to change at build time:
  `CONFIG = {"NAME": features.Option(default=, lo=, hi=, bytes=, help=)}`, read with
  `features.setting()` (the default, or the environment variable `AO300_<FEATURE>_<NAME>`).
  The declaration is a promise: the value is an 8-bit immediate; every value in range builds
  code of the same length that differs from the default build only in the `bytes` places
  holding the value; and the feature's own tests cover the behaviour over the range (its
  `emu_test.py` sweeps values through `emit()`'s arguments). `tools/build.py` checks the first
  two parts on every build and fails when they break. A config may not change code size,
  control flow or any byte outside its own. Because of this promise, an image that differs
  from a registered one only by config values is the **one exception** to the `KNOWN_IMAGES`
  rule: it needs no entry, no new `VERSION_TEXT` and no new tests. `tools/build.py` itself
  always builds the defaults (it ignores the variables); only `build.variant()` and the
  release installer set them.
- An image meant for the amp includes direct-select, fix-auto-off, strings, start-volume,
  fix-volume-pop and fix-menu-input (INCLUDES) unless the maintainer decides otherwise. Only a UI
  theme stacks on fast-lcd; fixes stack on stock.
- UI themes build on fast-lcd and `tools/patch/uikit.py`. Code more than one theme can use goes
  into the kit, with tests in `tools/patch/uikit_test.py`. After a kit change, rebuild every
  theme: an image whose sha changes needs its tests run again and a new `KNOWN_IMAGES` entry.
  Animations run from the kit's per-tick driver (`uk_tasks`) and never block the main loop.

## Testing

- Use `tools/emu/emu8051.py`. Its clock counts come from the STC8 instruction table in
  the STC8G manual: bit operations and most MOVs take 1 clock. Don't estimate timing
  from classic 8051 or from memory.
- `Emu8051(...)` runs the C core (`tools/emu/core8051.c` through `cemu8051.py`);
  `PyEmu8051` in `emu8051.py` is the reference. Any change to the emulator goes into
  both, and `tools/emu/test_core.py` must pass before the tests count.
- Every patch test includes:
  - the new behaviour, run at the hook;
  - a sweep of all 256 IR commands against the base image, in every power and page
    state the patch reads;
  - an image diff limited to the bytes the patch is meant to change.
- Anything in the key path or the main loop, or anything that changes the page or the
  timers, also needs a full-firmware scenario. Boot from reset on `Amp` (`tools/emu/ao300.py`:
  the real Timer0 and Timer3 ISRs), then run the main loop (see `Run` and
  `scenario_auto_off` in `features/fix-auto-off/emu_test.py`).
  Hook-only tests once missed `read_key`'s tail at 0x3DD6, which turns keys on page 2
  into "go home".
- Run the tests (`python3 tools/run_tests.py` runs them all in parallel) and report
  their output before calling a build ready.

## The release bundle

- `tools/release.py` packs a user-facing zip from a whitelist, every file at its repository
  path: `install.sh`, `README.md`, `docs/install.md`, `docs/status.md`, the screenshots, the
  licence and notices, the wizard (`tools/installer/`), the build tools, and the code and
  data of the features the two themes contain (no feature READMEs). The bundled docs link
  only to bundled files; the README's "For developers" section is the exception. Its
  self-test builds both themes from the extracted zip. Run it (and `tools/run_tests.py`)
  before publishing a bundle; a bundle whose reference images are not in `KNOWN_IMAGES`
  refuses to flash.
- The wizard hard-codes no default, option name or variable: it reads every feature's
  `CONFIG`. When a feature gains a config, the wizard asks for it with no change of its own.
- The wizard never opens the serial port itself: it runs `tools/flash/flash_ao300.py` as a
  child process with the terminal attached, so the chip checks, the "Waiting for the
  bootloader" line and the recovery message stay the flasher's. Choosing flash or recover in
  the wizard's menu is the confirmation: it passes `-y`, so the typed `FLASH` question is
  not asked twice.
- The wizard's Windows updater (`--action exe`) is a copy of the vendor `.exe` with the built
  image inside. It is firmware: it stays in `build/out/` and never goes into git or a bundle,
  and the wizard and the guide tell the user not to share it.

## Documentation

- **Always update `tools/disasm/SmslAo300Labels.java` when new sections of the firmware
  get discovered**: routines, labels inside routines, RAM variables, tables, fonts. Keil
  stores 16-bit values high byte first; name the bytes `_hi` and `_lo` accordingly.
- Keep the docs current: `docs/hardware.md` (hardware map, memory budget),
  `docs/open-questions.md`, `docs/status.md`, and the README's feature list, IR table and
  Status paragraph. Each topic has one home (the table at the end of `docs/development.md`);
  elsewhere link to it and don't restate it. When a claim turns out wrong, fix it where it
  is written.
- The README is for someone who owns the amp: plain language, no addresses. Its screenshots
  (`docs/images/`) are emulator renders; make them again when a theme's look changes.
- Scratch files (video frames, trial builds, traces) go outside the repository. Evidence a
  doc cites is the exception, as tight crops that show the display only.
