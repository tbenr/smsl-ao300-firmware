# Working rules for this repository

Custom firmware for the SMSL AO300 amplifier's control MCU (STC8C2K64S2, 8051). The
README has the hardware map, memory budget, open questions and flashing guide. These
rules apply to anyone working here, human or agent.

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

## The amp

- Never start anything that talks to the serial port (`identify`, `dryrun`, `flash`,
  `recover`, plain stcgal) until the user says go. First say what the command does and
  what they must do at the amp: standby, then Source on the remote, or a cold power-up.
  When the user flashes from another machine, give the command and don't run it.
- Flash only through `tools/flash/flash_ao300.py`. Add every new image's sha256 to
  `KNOWN_IMAGES` with a one-line description. Never change the option bytes, the
  24 MHz clock target or the code/EEPROM split.
- Keep the recovery path intact. Don't touch the reset vector, the standby key handler
  (0x59B2), or `read_key`'s Source-in-standby jump to the bootloader (0x3DB8).
- Record something as working on hardware (README "Status", feature README) only after
  the user confirms it, with the date.

## Building features

- All addresses refer to the stock v1.4 image, sha256 `85e8ac50ffcf47ea…`.
- One folder per feature: `features/<name>/` with `build_patch.py`, an annotated or
  generated `.asm` listing, `emu_test.py`, `README.md`, and outputs in `build/`.
- `build_patch.py` checks the base image's sha256 and asserts the original bytes at every
  hook before it changes them. Hooks use as few bytes as possible (an LJMP or a
  repointed branch). New code is appended after the current end of the patch area and
  stays below 0xF400.
- Internal RAM is full. New variables go in XDATA from 0x0100. Leave the EEPROM
  sectors in use (offsets 0x0000, 0x0200, 0x0400) alone.
- Each build sets its own `VERSION_TEXT` (20 characters at most), so the RESET page
  shows which image is running.
- Build on top of direct-select unless the user asks otherwise.
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
  timers, also needs a full-firmware scenario. Boot from reset with the real Timer0 ISR,
  then run the main loop (see `boot_scenario` in `features/blit-test/emu_test.py`).
  Hook-only tests once missed `read_key`'s tail at 0x3DD6, which turns keys on page 2
  into "go home".
- Run the tests (`python3 tools/run_tests.py` runs them all in parallel) and report
  their output before calling a build ready.

## Documentation

- **Always update `tools/disasm/SmslAo300Labels.java` when new sections of the firmware
  get discovered**: routines, labels inside routines, RAM variables, tables, fonts. Keil
  stores 16-bit values high byte first; name the bytes `_hi` and `_lo` accordingly.
- Keep the README current: the hardware map, memory budget, open questions and status.
  When a claim turns out wrong, fix it where it is written.
- Scratch files (video frames, trial builds, traces) go outside the repository.
