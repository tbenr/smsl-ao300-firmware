# House Numerals

A reduced first build of study 3 ("House Numerals", after SMSL's SU and DO series
screens) from `features/ui-theme/ui_themes.html`. Built on top of fast-lcd. The RESET
page shows `v1.4 tbenr hn3`.

This is the third image ("v3", sha256 `2c4809ab…`): the 200 ms wipe, drawn after the
volume write, now also runs on Bluetooth, on inputs without signal and while the unmute
countdown still has time to go; it keeps counting that countdown down while it runs. The
second image (`v1.4 tbenr hn2`, sha256 `2819e0b0…`) skipped the wipe whenever the countdown
was non-zero, so Bluetooth and no-signal inputs never wiped. The first image
(`v1.4 tbenr hn`, sha256 `deada16a…`, 47 ms wipe) was flashed by the user; nothing about
v2 or v3 is confirmed on hardware yet.

## Status

Emulator-verified (all tests pass), not yet tried on hardware (v3, `v1.4 tbenr hn3`).

## What the build shows

Kept from the mockup (the rest — number roll animation, spring on the line, dB
readout and captions, MUTE state on the volume page, status text on the volume page,
a true reveal wipe, an exit wipe — is cut for later passes; return home uses the stock
fast clear):

| Element | First build |
|---|---|
| Home: input name | stock big font and y (75), left-aligned at x 16 on page 1 only |
| Home: status line | stock small font and y (135), left-aligned at x 16 on page 1 only |
| Home: accent bar | 28 x 3 at 18,114 (under the name) |
| Home: icon, volume, tags | stock, unchanged |
| Volume page: entry | 2-px accent edge sweeps from x 318 to x 0 in about 200 ms (160 steps), black behind it; then content is drawn. Drawn after the key handler has written the volume, so the sound changes at once. Only when the unmute countdown (RAM 0x43:0x44) is due within 250 ms does the page open with the fast clear instead (see "The wipe and the unmute") |
| Volume page: name | small font, white, at 16,30 |
| Volume page: divider | 1 x 104 at 140,14, colour 0x2104 |
| Volume page: label | "VOL" in accent, small font, at 158,14 |
| Volume page: number | stock big digits at 2x (60 x 64 each), white, at 184,42 and 244,42; leading zero blank |
| Volume page: position line | 240 x 3 at 40,136: accent for 4 px per step, 0x18E3 for the rest |
| Accent | theme colour (RAM 0x48:0x49); SMSL orange 0xFC43 when the theme is White (0xFFFF) |

Everything goes through the fast pixel path of fast-lcd; `hn_fill` and `hn_digit2x`
stream bytes themselves, text goes through the stock glyph painters (`small_glyph_paint`
0x2DF8, `big_glyph_paint` 0x3F3C via the stock font at 0x6A23).

## Hooks

Ten hook sites: six in the drawing routines, plus the four places the volume keys
actually open the volume page.

| Address | Stock bytes | Now | What |
|---|---|---|---|
| 0x2106 | `12 5D 42` lcall `ui_clear_screen` | `12 9A 7C` lcall `hn_clear` | `ui_render_page`'s page clear. On page 2 it does the accent-edge wipe (via `hn_wipe`; or the fast clear when the unmute is due within 250 ms); on every other page it falls through to the stock clear |
| 0x2143 | `02 21 67` ljmp `volpage_render` | `02 9A 6A` ljmp `hn_volpage` | page-2 jump-table entry (`ui_page_table`) — a second way into the volume page, alongside the four sites below |
| 0x5936 | `AB 07 E5` (start of `volpage_draw_volume`) | `02 99 99` ljmp `hn_draw_volume` | replaces the volume digits/line draw entirely, so knob and remote steps redraw only the number and the line |
| 0x2A25 | `E4 78 02` (`big_text_render`'s start-x store) | `02 9B 2E` ljmp `hn_align_big` | on page 1, moves the stored start x to 16; page 3 (menus) unchanged |
| 0x3A82 | `E4 78 02` (`small_text_render`'s start-x store) | `02 9B 48` ljmp `hn_align_small` | same, for the status line |
| 0x5C99 | `02 59 16` ljmp `home_draw_volume` | `02 9B 10` ljmp `hn_home_tail` | `home_refresh`'s tail: draws the volume as stock, then adds the accent bar |
| 0x0D33 (in `key_volume_up`) | `12 5D 42 7B FF …` | `12 9A 75 80 11` (lcall `hn_enter_vol` ; sjmp 0x0D49) | volume-key entry site A |
| 0x0DB3 (in `key_volume_up2`) | `12 5D 42 7B FF …` | `12 9A 75 80 11` (lcall `hn_enter_vol` ; sjmp 0x0DC9) | volume-key entry site B |
| 0x0E5A (in `key_volume_down4`) | `12 5D 42 7B FF …` | `12 9A 75 80 11` (lcall `hn_enter_vol` ; sjmp 0x0E70) | volume-key entry site C |
| 0x0F02 (in `key_volume_down`) | `12 5D 42 7B FF …` | `12 9A 75 80 11` (lcall `hn_enter_vol` ; sjmp 0x0F18) | volume-key entry site D |

The four volume-key sites are inline in the key handlers, right after `mov 0x45,#0x02`
(labelled `volpage_enter_a`..`d` in `SmslAo300Labels.java`): stock, each ran
`lcall ui_clear_screen`, loaded "volume" (0x9347) via `small_text_load` (0x4D3A) and
drew it with `small_text_render` (0x3A53) at y 135. The patch replaces the first 5
bytes with `lcall hn_enter_vol ; sjmp site+0x16`, which skips past that stock caption.
`hn_enter_vol` draws nothing: it only sets the XDATA flag `HN_PEND`. Every path from the
four sites ends in the common tail at 0x0F48 (`vol_key_tail`): it writes the volume
(`volume_apply` 0x4DDC, which sends it to the NJW1194) and then calls 0x5936, which is
hooked to `hn_draw_volume`. That routine sees `HN_PEND`, clears it, runs `hn_wipe` and
`hn_vol_static`, and then draws the number and the line. So the sound changes right
away and only the picture takes its time. The 0x2106/0x2143 hooks stay in as a second
way in (the page-2 renderer, `volpage_render` at 0x2167); that path wipes too and does not
use the flag. `hn_home_tail` clears `HN_PEND` (XDATA is not guaranteed zero at power-on,
and the home screen is always drawn before any volume page).

## The wipe and the unmute

The wipe blocks the main loop for 200 ms. The main loop counts the unmute countdown (RAM
0x43:0x44) down once per 10 ms tick flag (bit 0x20.7, set by Timer0, one bit, so ticks
that come while the loop is blocked are lost) and unmutes (`mute_state_set(1)` at 0x33FB)
when it reaches 0. hn2 therefore skipped the wipe whenever the countdown was non-zero.
But on several inputs the firmware keeps re-arming it, and it never reaches 0:

| Input / output | Who holds the countdown (emulator, no stream) | Value |
|---|---|---|
| Bluetooth (0x47 = 4) | `bt_hold_mute_poll` 0x583F, from the format poll every 10 ticks (0x341B): register 0x0038 of the I2C device at 0x80, low nibble 0, raises it to 50 | 40..50 |
| Optical, coax (2, 3) without lock | Timer0 0x3E92: P4.2 high, sets 0x21.4 and 100 on every tick | 100 |
| Headphone output (0x2B = 2), P2.6 low | Timer0 0x3EE9: clears P2.5, sets 300 on every tick | 300 |
| After power-on, input switches | counts down to the unmute (200 ticks, 300 held first at power-on) | 200 .. 0 |

(INT1 also sets 30 on optical/coax receiver events; `format_poll` raises it to 30 on a
format change; `mute_and_arm_unmute` 0x5A92 sets 10 or 100 from menu and key actions.)
A state rule that tells "held" from "running out" would have to repeat those checks,
one of them an I2C read, so hn3 counts the ticks instead:

- `hn_wipe` starts with the two buffer clears of `ui_clear_screen`. It does `ljmp 0x51EE`
  (`lcd_clear_black`, the fast clear) and returns to its caller, as hn2 did, in two cases:
  - the countdown is 1..24 (`HN_CD_MIN` = 25 ticks): the unmute falls due within the wipe
    (at most 21 ticks, plus one pending) and the page drawn after it. That only happens in
    the last 250 ms before an unmute;
  - bit 0x20.3 is set: `post_power_on` (0x5585) is still to run. A key pressed during the
    power-on logo (`power_on_display` 0x5975, about 3 s) waits and is dispatched in the
    main loop's first pass, just before `main_tasks_on` runs `post_power_on`, which starts
    the audio sequence and arms the countdown at 200. A wipe there delayed that whole
    sequence, and the unmute, by 0.18 s.
- Otherwise it wipes. `hn_tick` runs at the start of each of the 160 steps (every 1.25 ms,
  so no tick is missed) and stands in for the main loop:
  - When the tick flag is set and the countdown is 2 or more, it clears the flag and
    counts the countdown down, never below 1. The first tick it takes is not counted: at
    the end `hn_wipe` sets the flag again, and the main loop counts it. So the countdown
    sees every tick once, the main loop still runs the expiry (and the unmute) itself, and
    its other countdowns get the one tick they got before. At 0 (not running) or 1 it
    leaves the flag alone.
  - When the re-mute request 0x21.4 is set, it answers it once per wipe as
    `main_tick_tasks` 0x3325 does on every pass: clear 0x21.4 and 0x22.4, call
    `audio_apply_mute` 0x58D3 (NJW1194 to the mute code, DAC register 9). On optical/coax
    without lock the key handler's volume write reaches the NJW1194 and the main loop puts
    the mute code back at the next tick; without this the mute code came back 0.18 s late.
    After it 0x22.4 stays clear until the wipe ends, so repeats would write the same values;
    they cost 5.2 ms each and wait for the main loop.

What that gives on each input (emulator, Vol+ from home):

| Situation | Countdown at `hn_wipe` | Entry | Unmute vs fast-lcd |
|---|---|---|---|
| Bluetooth, settled | 40..50, held | wipe, 200 ms | none in either image |
| Optical without signal, settled | 99..100, held | wipe, 205 ms (one re-mute) | none in either image |
| Headphone output, P2.6 low | 299..300, held | wipe, 200 ms | none in either image |
| USB, 7.4 s after power-on | 89 | wipe | 0.02 s earlier |
| HDMI, 0.5 s after the switch | 190 | wipe | 0.02 s earlier |
| USB, unmute due within 250 ms | 16 | fast clear | 0.02 s earlier |
| Vol+ during the power-on logo | 300, `post_power_on` pending | fast clear | 0.02 s earlier |
| USB or HDMI, settled | 0 | wipe | no unmute |

Earlier by up to 0.03 s because fast-lcd's own 40 ms draw loses ticks and the wipe does
not. A scratch sweep of 820 presses against fast-lcd (every 20 ms from 2 to 8.8 s after
Power and from 0 to 3 s after switching to USB and HDMI, every 50 ms for 3 s after
switching to optical, coax and BT) found every unmute between 0.03 s earlier and 0.01 s
later than fast-lcd. The audio states came in the same order everywhere except for
presses 2.0-3.3 s after Power, which wait for the logo; hn2 gives exactly the same
differences there (compared every 20 ms), so they are older than this change. One class of
audio state still comes late; see Risks.

## Memory

Code range: `features/house-numerals/build/flash_house_numerals.bin` adds 946 bytes of
patch code at 0x9800..0x9BB1 (fast-lcd's own patch code ends at 0x976B), plus a 15-byte
version string at 0x9BB2. Image length 39873 bytes, well under the 0xF400 code/EEPROM
split. `house_numerals.asm` is the generated listing.

XDATA 0x0100..0x0112 (new state; the EEPROM sectors and everything fast-lcd/direct-select
use stay untouched):

| Address | Name | Holds |
|---|---|---|
| 0x0100:0x0101 | `HN_THEME` | saved RAM 0x48:0x49 (theme colour), while accent/white ink is in use |
| 0x0102:0x0103 | `HN_ACC` | the accent colour for this call (theme colour, or SMSL orange on White) |
| 0x0104:0x0105 | `HN_N` | `hn_fill`'s pixel count, hi then lo |
| 0x0106:0x0107 | `HN_C` | `hn_fill`'s colour, hi then lo (right after `HN_N`) |
| 0x0108:0x0109 | `HN_SP` | `hn_text`'s string pointer |
| 0x010A:0x010B | `HN_TX` | `hn_text`'s current x |
| 0x010C | `HN_TY` | `hn_text`'s y |
| 0x010D | `HN_VOL` | the volume value being drawn (0..60, clamped) |
| 0x010E:0x010F | `HN_WX` | `hn_wipe`'s current edge x, hi then lo |
| 0x0110 | `HN_PEND` | volume page pending: set by `hn_enter_vol`, cleared by `hn_draw_volume` (and by `hn_home_tail`) |
| 0x0111 | `HN_TICK` | `hn_wipe`: a main-loop tick has been taken (the flag is set again at the end) |
| 0x0112 | `HN_REMUTE` | `hn_wipe`: the re-mute request 0x21.4 has been answered in this wipe |

## Emulator results

Running `python3 tools/run_tests.py` gives **ALL PASS** for every feature, 76.1 s wall
(house-numerals takes the 76.1 s, most of it the 63 s sweep).

- Image diff: only the ten hooks above (plus the version pointer) differ from fast-lcd
  inside the base image range; the gap up to 0x9800 is left erased; the image ends at
  39873 bytes, below 0xF400.
- `hn_draw_volume` (the 0x5936 hook): every step 0..60, in three themes, redraws only the
  number box and the line; the fill loop runs at 9.0 clocks per pixel (at most 10
  allowed). With `HN_PEND` = 0 it never calls `hn_wipe`.
- `hn_clear`'s wipe: the edge sweeps from x 318 to 0, 2 px at a time, black behind it,
  and takes 201 ms (the test allows 190-215 ms). With RAM 0x43:0x44 at 1 or 24 (via
  `hn_clear` and `hn_wipe`) it calls 0x51EE instead: no edge fills, black screen, 9.9 ms;
  at 25, 31 and 256 it wipes. Without ticks the countdown and the tick flag are untouched.
  With 0x20.3 set (countdown 0 or 300) it fast-clears.
- `hn_tick`: every combination of tick flag, countdown (0, 1, 2, 256, 300) and "tick taken"
  gives the expected flag, countdown and state (the first tick taken is left for the main
  loop, later ones count, never below 1); the re-mute request is answered once
  (`audio_apply_mute` called with 0x22.4 clear, 0x21.4 cleared) and not a second time.
  A wipe from countdown 100 with a flag-only Timer0: 20 ticks in all, 19 taken, 18 counted,
  flag set at the end, at most one tick per step; 20 ticks fit well under `HN_CD_MIN` (25).
  With 0x21.4 raised every tick, `audio_apply_mute` runs once, 11.2 ms in (first tick at
  10 ms), and the wipe takes 206 ms. With the countdown forced to 3 mid-wipe it stops at 1.
- `hn_enter_vol` (the four volume-key sites): draws nothing and sets `HN_PEND` = 1; the
  next 0x5936 call wipes (edges 318..0), draws the static page and the number, clears
  `HN_PEND`, and a second 0x5936 call does not wipe. With the countdown at 20 (unmute
  due within the wipe) the same path fast-clears and leaves the same final screen. The stock "volume" caption is skipped
  at all four addresses.
- Left-aligned text (0x2A25/0x3A82): page 1 text moves to x 16 with the same glyphs and
  cleared margins; page 3 (menus) stays centred, unchanged.
- Whole-firmware tour, lockstep with fast-lcd (real Timer0 ISR, real main loop):

  | Step | fast-lcd drawing | house-numerals drawing |
  |---|---|---|
  | power_on | 0 ms | 0 ms |
  | vol_up | 40 ms | 210 ms (200 ms wipe: countdown 31, counted during it) |
  | vol_up2 | 10 ms | 10 ms |
  | back_home | 0 ms | 0 ms |
  | source | 60 ms | 60 ms |
  | menu | 110 ms | 110 ms |
  | menu_down | 90 ms | 90 ms |
  | menu_timeout | 0 ms | 0 ms |
  | hdmi | 80 ms | 80 ms |
  | vol_down | 40 ms | 210 ms (200 ms wipe: countdown over) |
  | vol_timeout | 0 ms | 0 ms |
  | standby | 20 ms | 20 ms |

  Every step: same page, power, volumes, input and output as fast-lcd; the home screen
  is pixel-identical to fast-lcd outside the accent bar and the two left-aligned bands;
  the accent bar is 0xFC43 (White theme) at 18,114; menu screens are pixel-identical to
  fast-lcd. `vol_up` is 8 s after power-on, with the unmute countdown at 31 ticks, and
  `vol_down` 3 s after the HDMI switch, countdown 0: both wipe, 160 edge steps, 318 down
  to 0. In both the NJW1194 volume write (R7 = 0x10) comes 0.2 ms before `hn_wipe` starts
  and before the first edge fill. `back_home` returns home at 1.49 s in both images (the
  page timer is re-armed by `vol_up2`); `vol_timeout` at 1.52 s on
  fast-lcd and 1.69 s here: after a wiped entry the page timer is armed after the 200 ms
  wipe, so home comes back about 0.2 s later (the test allows 0 to 0.30 s).
- Audio state: 160 audio states, in the same order as fast-lcd, none more than 0.10 s
  later; the backlight switches the same way; every audio writer (`dac_i2c_write`,
  `expander_write`, `input_set_hw`, `njw1194_write`) receives the same argument sets.
  In hn2 a wipe during the countdown delayed the unmute (the BT mute pins, the NJW1194 and
  DAC writes after them) by 0.17 s; `hn_tick` counts the countdown during the wipe, and
  the `vol_up` wipe (countdown 31) leaves the unmute on time. The checks stay strict.
- Volume key per input (`input_scenarios`, in the `tour` group, 7 s): seven full-firmware
  runs from reset, each in both images, Vol+ once the input has settled: Bluetooth
  (countdown 44), optical without signal (99), headphone output with P2.6 low (299), USB
  7.4 s after power-on (89), HDMI 0.5 s after the switch (190), USB with the unmute due
  (16), and 2.5 s after Power, during the logo (300, `post_power_on` pending). The first
  five wipe (160 edge fills, 318 down to 0; 205 ms on optical, which answers one re-mute),
  the last two fast-clear; in all seven the volume write comes before `hn_wipe` (and before
  the first edge fill), the screen is `hn_volpage`'s render (the logo case: home, as
  fast-lcd, once `post_power_on` has run), and the audio states match fast-lcd in order
  (70 to 114 each) with none more than 0.10 s later. The held three unmute in neither
  image; the other four unmute 0.02 s earlier than fast-lcd.
- IR sweep: 256 commands x 5 states (standby, home, volume, volume_hp, menu), every
  screen compared against fast-lcd (home outside our bands, volume against
  `hn_volpage`'s own reference render, everything else pixel-identical); the outcome is
  read 0.5 s after the press (the wipe plus the page take about 0.22 s); sweep runs in
  63 s. The "volume" and "volume_hp" fixtures press the first Vol+ and wait 0.6 s, not
  0.5 s: the key timer at RAM 0x37:0x38 expires 0.5 s after a press and clears the IR key
  state (0x492b), and a command injected in that very iteration is read as "go home" on
  page 2 (`read_key`'s tail at 0x3DD6). Without a wipe the timer starts at the key press,
  so a second key at exactly 0.5 s hit it. This is a race in the harness's injection, not a
  behaviour of the patch.
- `tools/emu/panel_video.py` renders what the panel shows at 60 fps, with the real frame
  steps of the scan, to check animations: `python3 tools/emu/panel_video.py
  features/house-numerals/build/flash_house_numerals.bin OUT --seconds 5.5`. Its default
  presses come 9.5 s after power-on, past the countdown, so the first Vol+ wipes. With
  `--press 0.5:0x13 --press 5.0:0x0A --seconds 8.5` it switches to Bluetooth ("initializing",
  then "Searching.") and shows a wiped volume entry on it.

### Coverage gaps

- The tour reaches volume-entry sites 0x0D33 (`key_volume_up`) and 0x0F02
  (`key_volume_down`) only. Sites 0x0DB3 (`key_volume_up2`) and 0x0E5A
  (`key_volume_down4`) are covered by the per-site unit test (`test_enter_vol`) only —
  the dispatch table at 0x0CAB reaches them from key codes 0x5A/0x5B (bit 0x40:
  probably a held key / remote repeat, not confirmed).
- The sweep's layout checks (home bands, accent bar, volume-page reference) apply only
  while the amp is powered; in standby both screens go blank identically and the check
  falls back to raw pixel equality.

## Risks

- **Panel timing: same as fast-lcd.** `hn_fill` and `hn_digit2x` use fast-lcd's byte
  timing (the tuned WR pulse `features/blit-test` proved on the panel); no new bus
  pattern is introduced.
- **Main-loop timers: the wipe blocks the main loop for 200 ms.** The volume write happens
  first, so the sound does not wait. The main loop's software countdowns stop while the
  handler runs: after a wiped entry `vol_down` takes 210 ms to settle (fast-lcd: 40 ms) and
  the page returns home about 0.2 s later than on fast-lcd (the ISR-driven return-home
  count is armed after the wipe). Two main-loop duties touch the sound and `hn_tick` does
  them during the wipe: the unmute countdown (RAM 0x43:0x44) and the re-mute request
  (0x21.4); when the unmute is due within 250 ms, or `post_power_on` is still to run, there
  is no wipe. The others stay frozen for the 200 ms, as in hn2, and now also during the
  countdown after power-on and input switches, where one of them matters: the first format
  poll after the switch (`format_poll_tick` 0x341B, every 10 main ticks) reconfigures the
  DAC (`format_poll` 0x4638). A Vol key just before it delays it (20 to 36 audio states, DAC
  writes) by 0.16-0.19 s against fast-lcd. The scratch sweep found this for presses 0.02-0.14 s after
  switching to USB, HDMI, optical and coax (not BT), and 5.02-6.16 s after Power (keys
  pressed then wait for `post_power_on` and are dispatched right after it), and nowhere
  else. The amp is still muted then (the unmute is 1-2 s away) and the order of the audio
  states is unchanged, but the tests' 0.10 s audio check would flag it; no test presses in
  that window. Avoiding it would need the format poll run inside the wipe (a
  reconfiguration takes about 40 ms) or a wipe that does not block the main loop.
- **RAM 0x48:0x49 (the theme colour) is changed while drawing.** `hn_begin` saves it to
  XDATA `HN_THEME` and `hn_accent`/`hn_white` overwrite it so the stock glyph painters
  pick up the accent or white ink; `hn_end` restores it before returning. Every hn_*
  drawing path (`hn_draw_volume`, `hn_vol_static`, `hn_clear`'s wipe, `hn_home_tail`) is
  bracketed this way, and the tests check the colour is back afterwards in every case.
- **Recovery: unchanged.** The reset vector, the standby key handler (0x59B2) and
  `read_key`'s Source-in-standby jump to the bootloader (0x3DB8) are untouched.

## What to look for on the amp

- Turning the knob or pressing Vol+/Vol-: the accent edge sweeps in from the right as
  the volume page opens (200 ms). There is no exit wipe; home returns through the stock fast
  clear.
- Digits on the volume page: sharp and unbroken at 2x size (60 x 64), no torn columns or
  swapped bytes (a dropped byte on the panel bus shows as a colour shift, as noted in
  `features/blit-test`'s README).
- Accent colour: SMSL orange (0xff8a1f) on the White COLOR theme, the COLOR tint on
  every other theme, on both the home accent bar and the volume page's "VOL" label,
  divider is not tinted (fixed dark grey, 0x2104), and the position line.
- Home screen: input name and status line left-aligned at x 16, not centred.
- Menus: unchanged, still centred.
- Volume page returns home 2 s after the last step, same as stock; after a wiped entry it
  is about 0.2 s later than that, from the key press.
- Vol+ on Bluetooth (with and without a stream), on optical/coax without signal and in
  the seconds after power-on or an input switch: the wipe, as everywhere else. The page
  just appears only in the last quarter second before the amp unmutes, and for a key
  pressed during the power-on logo.
- The unmute after power-on or an input switch comes at the same moment whether or not a
  volume key was pressed during it.
- The volume should change before the edge starts.

## How to go back

Flash `features/fast-lcd/build/flash_fastlcd.bin` (stock UI, fast pixel path) or
`features/direct-select/build/flash_patched.bin` (stock UI, stock pixel path, direct
input selection over IR).

## Files

- `build_patch.py` builds `build/flash_house_numerals.bin` from
  `features/fast-lcd/build/flash_fastlcd.bin` and writes the listing
  `house_numerals.asm`.
- `emu_test.py` runs the unit tests, the full-firmware tour and the IR sweep above.
