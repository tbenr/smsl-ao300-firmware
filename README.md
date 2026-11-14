# SMSL AO300 firmware work

Reverse engineering of the SMSL AO300 amplifier's control-MCU firmware (STC8C2K64S2,
8051 core) and custom features built on top of it.

## Status

Flashed on 2026-11-14 over the ser2net tunnel and confirmed by the user the same day:
`features/house-numerals/build/flash_house_numerals.bin` (hn19, `v1.4 tbenr hn19`, sha256
`8cf34756…`), House Numerals with direct-select ds4. It all works: the RESET page, the
idempotent power commands 0x16 and 0x17 (ds3, on the amp for the first time), and an input
command waking the amp from standby on that input (ds4). No pop on the wake was reported. The
amp runs hn19; before it, pp2. pp4, as4, pr5 and the standalone ds3 and ds4 images have not
been flashed.

Built on 2026-11-14 and emulator-verified: direct-select ds4 (`v1.4 tbenr ds4`,
sha256 `4b5dcfce…`). An input command (NEC 0x10..0x15) in standby now powers the amp on, on
that input: the hook writes the input and returns the Power key, and stock's power-on does its
one source setup on it. With the amp on nothing changed. It is a build-time config,
`direct-select.WAKE_ON_INPUT` (default 1; 0 keeps ds3's "ignored in standby"), which the
installer asks about. Rebuilt on it with nothing else changed: house-numerals hn19
(`8cf34756…`), phosphor-panel pp4 (`cc2292e7…`), auto-switch as4 (`8e0602f5…`) and probe pr5
(`0fc654e4…`), all in `KNOWN_IMAGES`. In the emulator the input mux moves only while the
outputs are muted, as at a cold power-up; on the amp (hn19, above) the wake works.

Built on 2026-10-16 and emulator-verified: direct-select ds3 (`v1.4 tbenr ds3`,
sha256 `425460c3…`) adds idempotent power over IR, NEC 0x16 (on) and 0x17 (off), each a no-op
in the state it names ("Direct input selection and idempotent power over IR" below). Every
image that includes the fix was rebuilt on it with nothing else changed: house-numerals hn18
(`b3455f2b…`), phosphor-panel pp3 (`273edf8f…`), auto-switch as3 (`aa43a3e5…`) and probe pr4
(`e4a5bd1e…`), all in `KNOWN_IMAGES`. None of these was flashed; the power commands reached
the amp with hn19 (above).

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
