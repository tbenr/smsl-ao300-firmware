# Status: what was verified on hardware

A row is added here only after the person who flashed an image confirms the result on the
amp, with the date of that confirmation. Emulator results never appear in tables A and B.
Everything was done on one AO300 (stock firmware v1.4), the author's. Shas are the first eight
digits of the image's sha256; the full values are in `KNOWN_IMAGES` in
`tools/flash/flash_ao300.py`.

**On the amp now:** House Numerals `v1.4 tbenr hn19` (`8cf34756`), since 2026-11-14.

## A. Verified behaviour, by feature

| Feature | What was confirmed on the amp | First image, date | Latest image, date | Standalone image flashed |
|---|---|---|---|---|
| direct-select: the six input commands | each selects its input; the stock remote works unchanged | `v1.4 tbenr`, 2026-09-28 | hn19, 2026-11-14 | yes (the first version only) |
| direct-select: same input ignored (ds2) | a command for the current input no longer interrupts the audio | hn11, 2026-09-30 | hn19, 2026-11-14 | no |
| direct-select: power on and off (ds3) | 0x16 and 0x17 work | hn19, 2026-11-14 | hn19, 2026-11-14 | no |
| direct-select: wake on an input command (ds4) | an input command in standby powers on, on that input; no pop reported | hn19, 2026-11-14 | hn19, 2026-11-14 | no |
| fast-lcd | the stock UI draws correctly through the fast path; no audible effect in daily use since 2026-09-30 inside every theme image (confirmed 2026-11-14) | `v1.4 tbenr fast`, 2026-09-28 | hn19, 2026-11-14 | yes (the first version only) |
| fix-auto-off | with Dimmer on Auto OFF the display goes dark after a cold power-up | hn7, 2026-09-29 | hn19, 2026-11-14 | no |
| strings | "Disconnected" on HDMI ARC without a link | hn10.1, 2026-09-30 | hn19, 2026-11-14 | no |
| start-volume | the amp starts at the capped volume | hn13, 2026-10-02 | hn19, 2026-11-14 | no |
| fix-volume-pop | no pop on the first volume key on Optical without a signal | branch build `d39d321c`, 2026-10-02 | hn19, 2026-11-14 | no |
| fix-menu-input | no pop on an input change through the menu, the Source key or direct-select | branch build `7a4af92f`, 2026-10-02 | hn19, 2026-11-14 | no |
| House Numerals | home, volume page, wipes, number roll, spring, MUTE state, the fonts in the stock big font's area | `v1.4 tbenr hn`, date not recorded | hn19, 2026-11-14 | — |
| Phosphor Panel | home, volume page, fades; the dot-matrix name reads well | pp1, 2026-10-10 | pp2, 2026-10-10 | — |
| auto-switch, stage 1 | from Optical with nothing playing, the amp went to HDMI about a second after the TV woke | as1, 2026-10-05 | as1, 2026-10-05 | yes (as1) |
| probe | the register dump arrives as the emulator predicted; the amp is unaffected | pr2, 2026-10-05 | pr3, 2026-10-05 | yes (pr1 to pr3) |

## B. Images flashed

Route: **USB** is the flasher on the computer the amp is plugged into; **RFC 2217** is the
flasher on another computer, through `tools/flash/ser2net/`.

| Date | RESET page | sha | Route | Result |
|---|---|---|---|---|
| 2026-09-28 | `v1.4 tbenr` | `bb468b29` | USB, macOS | direct-select: all six commands work, RESET page shows the version |
| 2026-09-28 | `v1.4 tbenr blit` | `eae8f6ed` | USB, Linux | blit test: colours right, fill time as the emulator predicted (about 15 ms against 147 ms stock) |
| 2026-09-28 | `v1.4 tbenr fast` | `b292a648` | USB | fast-lcd on direct-select: works |
| not recorded | `v1.4 tbenr hn` | `deada16a` | USB | first House Numerals image: works |
| 2026-09-29 | `v1.4 tbenr hn4.1` | `5eddb6df` | USB | looks OK |
| 2026-09-29 | `v1.4 tbenr hn5` | `510fd138` | USB | looks great; tags, status line and volume too small |
| 2026-09-29 | `v1.4 tbenr hn7` | `41ce9807` | USB | looks good; Auto OFF times out after a cold power-up |
| 2026-09-30 | `v1.4 tbenr hn8` | `122a963c` | USB | works; status stayed reddish for a few seconds after an input change (fixed in hn10.1) |
| 2026-09-30 | `v1.4 tbenr hn9` | `b45331a8` | USB | good |
| 2026-09-30 | `v1.4 tbenr hn10` | `45c22bf1` | USB | looks good |
| 2026-09-30 | `v1.4 tbenr hn10.1` | `89a6ed99` | USB | works |
| 2026-09-30 | `v1.4 tbenr hn11` | `6050a846` | USB | works; same-input command no longer interrupts the audio |
| 2026-09-30 | `v1.4 tbenr hn11.1` | `3aa0f2d6` | USB | works |
| 2026-09-30 | `v1.4 tbenr hn12` | `5f406b5d` | USB | works |
| 2026-10-02 | `v1.4 tbenr hn13` | `e91e3a20` | USB | works; the volume cap holds |
| 2026-10-02 | `v1.4 tbenr hn13` (branch build) | `1e5691d8` | USB | the MUTE state works |
| 2026-10-02 | `v1.4 tbenr hn14` (branch build) | `d39d321c` | USB | the volume-key pop is gone |
| 2026-10-02 | `v1.4 tbenr hn15` (branch build) | `7a4af92f` | USB | no pop on an input change |
| 2026-10-02 | `v1.4 tbenr hn16` | `7ee88992` | USB | the fixes work |
| 2026-10-05 | `v1.4 tbenr hn17` | `782eb508` | RFC 2217 | first flash by this route; every screen as before |
| 2026-10-05 | `v1.4 tbenr pr1` | `24bd8f2e` | not recorded | amp came back; replaced by pr2 before a dump was taken |
| 2026-10-05 | `v1.4 tbenr pr2` | `280c3f99` | RFC 2217 | thirteen dumps, the first 1204 bytes as predicted |
| 2026-10-05 | `v1.4 tbenr pr3` | `b4836c46` | not recorded | the FS line (`docs/bus-map.md`, "Layer 3, item 1"); flash confirmed on 2026-11-14 |
| 2026-10-05 | `v1.4 tbenr as1` | `d0146e35` | not recorded | the TV wake switches to HDMI |
| 2026-10-10 | `v1.4 tbenr pp1` | `38a1499e` | RFC 2217 | works; left edge of O and C cut in the dot matrix |
| 2026-10-10 | `v1.4 tbenr pp2` | `f5ca8bba` | RFC 2217 | the edges look right |
| 2026-11-14 | `v1.4 tbenr hn19` | `8cf34756` | RFC 2217 | everything works: RESET page, power commands, wake on input |

Before 2026-10-05 every flash was direct; the RFC 2217 route was first used that day, for
hn17.

## C. Built and emulator-verified, no flash on record

- **Standalone fixes:** direct-select ds2 to ds4, fast2, fast3, fix-auto-off aof1 to aof3,
  strings str1 to str3, start-volume sv1, fix-volume-pop vp1, fix-menu-input mi1.
- **House Numerals:** hn2, hn3, hn4, hn6, hn6.1, hn14 (as that image), hn18.
- **Phosphor Panel:** pp3, pp4. pp4 is pp2 rebuilt on direct-select ds3 and then ds4; nothing
  of the theme changed.
- **auto-switch:** as2 to as4. **probe:** pr4, pr5.

## D. Tooling

| What | Verified | Date |
|---|---|---|
| `tools/flash/flash_ao300.py` from macOS and from Linux | identify, dryrun and flash | 2026-09-28 onwards |
| The RFC 2217 route (`tools/flash/ser2net/`, ser2net 4.6) | identify, dryrun and flash; 56832 bytes in 15 s; the switch to 115200 baud works through it | 2026-10-05 |
| The release bundle, end to end on Linux | `install.sh`, the wizard, build and flash (bundle `ao300-custom-1c4dbd4-dirty-20261011`) | 2026-10-11 |
| A rebuilt Windows updater (made by hand with `stc_release.py rebuild`) | starts and validates its image on Windows | 2026-09-28 |
| A rebuilt Windows updater flashing an amp | **not done**, neither a hand-made one nor one made by the wizard | — |
