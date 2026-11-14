# SMSL AO300 firmware work

Reverse engineering of the SMSL AO300 amplifier's control-MCU firmware (STC8C2K64S2,
8051 core) and custom features built on top of it.

## Status

What was verified on hardware, and when: [docs/status.md](docs/status.md).

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
