# Start volume: a cap on the volume at power-on

Stock comes back at the volume it was left at, however loud. This feature caps the volume
when the amp turns on: it starts at min(last volume, limit). The limits are set at build
time, one for speakers and one for headphones. The standalone image is stock plus the cap;
the RESET page shows `v1.4 tbenr sv1`.

## Status

Verified on the amp on 2026-10-02, as part of house-numerals hn13 (limits 25 / 20): works.
Emulator-verified (all tests pass, including "start-volume in house-numerals"). The standalone
image itself has not been flashed.

## Setting the limits

The config is two constants at the top of `start_volume.py`. Each is set on its own:

```python
DISABLED = None        # no cap for that output: it starts at the last volume, as stock

SPEAKER_LIMIT = 25     # a volume step 0..60, or DISABLED
HEADPHONE_LIMIT = 20   # a volume step 0..60, or DISABLED
```

| SPEAKER_LIMIT | HEADPHONE_LIMIT | Speakers at power-on | Headphones at power-on | Code |
|---|---|---|---|---|
| 25 | 20 | min(last, 25) | min(last, 20) | 23 bytes (the default) |
| 25 | DISABLED | min(last, 25) | last, as stock | 13 bytes |
| DISABLED | 20 | last, as stock | min(last, 20) | 13 bytes |
| DISABLED | DISABLED | last, as stock | last, as stock | 3 bytes (only the jump) |

- The values are the steps the display shows. The main README's "Volume scale" section has
  their dB values: step 25 is 39.5 dB below maximum, step 20 is 47 dB below.
- The two limits need not be related; the headphone limit may be the higher one.
- Any other value (61, -1, "25", 25.0) stops the build with a message.
- The limits are part of the image. After changing them, rebuild (`python3 tools/build.py`),
  run the tests, give the images that contain the cap a new `VERSION_TEXT`, and add their
  sha256 to `KNOWN_IMAGES` in `tools/flash/flash_ao300.py`.

## What stock does

- Speaker volume is `g_volume` (RAM 0x31), headphone volume `g_volume_hp` (RAM 0x52), both
  0..60. `g_output` (0x2B) says which one is in use.
- `settings_load_eeprom` (0x2F46) reads them from EEPROM 0x0201 and 0x0209 at a cold boot and
  only clamps them to 0..60. Standby keeps RAM, so a wake uses the values as they are.
- Nothing on the power-on path lowers them. The one cap in stock is on an output switch
  (0x5296 calls 0x5CF6): the headphone volume is cut to 30 if it was higher.
- Cold power-up and the wake from standby both run `post_power_on` (0x5585). It calls
  `audio_chips_init` (0x50D1) at 0x5596, with the outputs muted. `audio_chips_init` makes
  the first volume write: `volume_apply` (0x4DDC) at 0x510A.

## The patch

One hook: `post_power_on`'s `lcall audio_chips_init` (0x5596) becomes `lcall sv_limit`.

```
sv_limit:  mov A,#25 ; clr C ; subb A,0x31 ; jnc sv_hp ; mov 0x31,#25
sv_hp:     mov A,#20 ; clr C ; subb A,0x52 ; jnc sv_go ; mov 0x52,#20
sv_go:     ljmp 0x50D1                     ; audio_chips_init, returns to 0x5599
```

- Both volumes are capped at every power-on, whichever output is active. A loud value
  stored for the other output cannot come back after an output switch.
- The compare is unsigned (volumes are 0..60): `limit - volume` borrows only when the volume
  is above the limit.
- `sv_limit` ends in a jump, so `audio_chips_init` returns straight to 0x5599 and the stack
  is as deep as in stock. It uses A and the carry, which `audio_chips_init` sets itself
  (`clr A` first). There are no new variables.
- The capped value is the volume from then on: stock shows it, sends it to the NJW1194, and
  saves it. (`filter_apply` inside `audio_chips_init` arms the settings save at every
  power-on.)
- The volume keys are untouched. The cap acts at power-on only.

## Including it in another build

`start_volume.py` holds the fix on its own (`HOOK`, `emit(a)`, `XDATA = []`); `build_patch.py`
here is only its standalone image. A build lists it in `INCLUDES` (README, "Feature graph"),
as house-numerals does since hn13. `tools/build.py` checks that the hook is installed, and
`run_tests.py` runs "start-volume in <that image>": this test's `integration()` on the
including image.

`emit(a, speaker, headphone)` takes the limits as arguments; they default to the config.
The test uses that to build the other configurations in memory.

## Tests (`emu_test.py`)

- **Image diff.** Only 0x5597, 0x5598 and the version pointer change. The code sits at
  0x96B0, a slot no other feature uses.
- **Hook.** The hook site run up to its return, with `audio_chips_init` recorded instead of
  run: for every volume 0..60 on both outputs it sees min(volume, limit), and all other RAM,
  XDATA and SP match stock.
- **Config.** The same on images built in memory for 25/20, 25/DISABLED, DISABLED/20,
  DISABLED/DISABLED, 10/40, 0/60 and 60/0. A disabled side leaves its volume alone and emits
  no code (3, 13, 13 and 23 bytes). Six bad values stop the build.
- **IR sweep.** All 256 NEC commands through 0x5D10, in standby and on pages 0..3, match
  stock.
- **Full firmware, stock and patch side by side.** Both boot from reset on `Amp` with the real
  timer ISRs. The test models the EEPROM behind the stock IAP routines (read 0x5970, write
  0x58AF, erase 0x59D0), with the magic byte and the power-on flag set. So a cold power-up
  turns the amp on by itself, as the real one does, and the stock save can be checked.
  - Stored 55 / 45, speakers: stock applies step 55 (NJW1194 code 0x2C). The patch applies
    25 (0x72) and never sends a louder code. The save then stores 25 / 20.
  - The same with the headphone output stored: stock 45 (0x40), the patch 20 (0x81).
  - Five Vol+ afterwards reach 30 (25 on headphones): the cap does not hold the keys back.
  - Standby and on again: back at 25 (20), and no louder code is sent. Stock keeps the
    volume.
  - Volumes that stay at or below the limits (stored at the limit; two below and raised to
    it; seven below): the same audio events as stock in the same order, each within two
    main ticks, and the same volumes, EEPROM and screen. The hook's own clocks can move a
    tick-driven action into the next 10 ms tick.
- **Integration** (`--in <feature>`). Cold power-up and standby wake on that image, as above.
  Then the home screen after a capped wake must equal the home screen of an amp that was
  left at the limit. That covers a theme with its own volume display.

The test reads the limits from the config, so it also passes with other values or with a
side disabled.
