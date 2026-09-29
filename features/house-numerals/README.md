# House Numerals

A reduced first build of study 3 ("House Numerals", after SMSL's SU and DO series
screens) from `features/ui-theme/ui_themes.html`. Built on top of fast-lcd. The RESET
page shows `v1.4 tbenr hn`.

## Status

Emulator-verified (all tests pass), not yet tried on hardware.

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
| Volume page: entry | 2-px accent edge sweeps from x 318 to x 0, black behind it; then content is drawn |
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
| 0x2106 | `12 5D 42` lcall `ui_clear_screen` | `12 9A 6D` lcall `hn_clear` | `ui_render_page`'s page clear. On page 2 it does the accent-edge wipe (via `hn_wipe`); on every other page it falls through to the stock clear |
| 0x2143 | `02 21 67` ljmp `volpage_render` | `02 9A 5C` ljmp `hn_volpage` | page-2 jump-table entry (`ui_page_table`) — a second way into the volume page, alongside the four sites below |
| 0x5936 | `AB 07 E5` (start of `volpage_draw_volume`) | `02 99 99` ljmp `hn_draw_volume` | replaces the volume digits/line draw entirely, so knob and remote steps redraw only the number and the line |
| 0x2A25 | `E4 78 02` (`big_text_render`'s start-x store) | `02 9B 07` ljmp `hn_align_big` | on page 1, moves the stored start x to 16; page 3 (menus) unchanged |
| 0x3A82 | `E4 78 02` (`small_text_render`'s start-x store) | `02 9B 21` ljmp `hn_align_small` | same, for the status line |
| 0x5C99 | `02 59 16` ljmp `home_draw_volume` | `02 9A EE` ljmp `hn_home_tail` | `home_refresh`'s tail: draws the volume as stock, then adds the accent bar |
| 0x0D33 (in `key_volume_up`) | `12 5D 42 7B FF …` | `12 9A 67 80 11` (lcall `hn_enter_vol` ; sjmp 0x0D49) | volume-key entry site A |
| 0x0DB3 (in `key_volume_up2`) | `12 5D 42 7B FF …` | `12 9A 67 80 11` (lcall `hn_enter_vol` ; sjmp 0x0DC9) | volume-key entry site B |
| 0x0E5A (in `key_volume_down4`) | `12 5D 42 7B FF …` | `12 9A 67 80 11` (lcall `hn_enter_vol` ; sjmp 0x0E70) | volume-key entry site C |
| 0x0F02 (in `key_volume_down`) | `12 5D 42 7B FF …` | `12 9A 67 80 11` (lcall `hn_enter_vol` ; sjmp 0x0F18) | volume-key entry site D |

The four volume-key sites are inline in the key handlers, right after `mov 0x45,#0x02`
(labelled `volpage_enter_a`..`d` in `SmslAo300Labels.java`): stock, each ran
`lcall ui_clear_screen`, loaded "volume" (0x9347) via `small_text_load` (0x4D3A) and
drew it with `small_text_render` (0x3A53) at y 135. The patch replaces the first 5
bytes with `lcall hn_enter_vol ; sjmp site+0x16`, which skips straight past that stock
caption into the same wipe-then-static-page path the 0x2106/0x2143 hooks use. This is
the path the amp actually uses to enter the volume page; the 0x2106/0x2143 hooks stay
in as a second way in (the page-2 renderer entry, `volpage_render` at 0x2167).

Code range: `features/house-numerals/build/flash_house_numerals.bin` adds 827 bytes of
patch code at 0x9800..0x9B3A (fast-lcd's own patch code ends at 0x976B), plus a 14-byte
version string at 0x9B3B. Image length 39753 bytes, well under the 0xF400 code/EEPROM
split. `house_numerals.asm` is the generated listing.

XDATA 0x0100..0x010F (new state; the EEPROM sectors and everything fast-lcd/direct-select
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

## Emulator results

Running `python3 tools/run_tests.py house-numerals` gives **ALL PASS**, 76.3 s wall.

- Image diff: only the ten hooks above (plus the version pointer) differ from fast-lcd
  inside the base image range; the gap up to 0x9800 is left erased; the image ends at
  39753 bytes, below 0xF400.
- `hn_draw_volume` (the 0x5936 hook): every step 0..60, in three themes, redraws only the
  number box and the line; the fill loop runs at 9.0 clocks per pixel (at most 10
  allowed).
- `hn_clear`'s wipe: the edge sweeps from x 318 to 0, 2 px at a time, black behind it,
  and takes 47 ms (the test allows 30-200 ms).
- `hn_enter_vol` (the four volume-key sites): each runs the same wipe, then the static
  page, with the stock "volume" caption skipped, at all four addresses.
- Left-aligned text (0x2A25/0x3A82): page 1 text moves to x 16 with the same glyphs and
  cleared margins; page 3 (menus) stays centred, unchanged.
- Whole-firmware tour, lockstep with fast-lcd (real Timer0 ISR, real main loop):

  | Step | fast-lcd drawing | house-numerals drawing |
  |---|---|---|
  | power_on | 0 ms | 0 ms |
  | vol_up | 40 ms | 60 ms |
  | vol_up2 | 10 ms | 10 ms |
  | back_home | 0 ms | 0 ms |
  | source | 60 ms | 60 ms |
  | menu | 110 ms | 110 ms |
  | menu_down | 90 ms | 90 ms |
  | menu_timeout | 0 ms | 0 ms |
  | hdmi | 80 ms | 80 ms |
  | vol_down | 40 ms | 60 ms |
  | vol_timeout | 0 ms | 0 ms |
  | standby | 20 ms | 20 ms |

  Every step: same page, power, volumes, input and output as fast-lcd; the home screen
  is pixel-identical to fast-lcd outside the accent bar and the two left-aligned bands;
  the accent bar is 0xFC43 (White theme) at 18,114; menu screens are pixel-identical to
  fast-lcd; `back_home` and `vol_timeout` return home within 0.1 s of fast-lcd (1.49 s
  and 1.52-1.54 s).
- Audio state: 160 audio states, in the same order as fast-lcd, none more than 0.10 s
  later; the backlight switches the same way; every audio writer (`dac_i2c_write`,
  `expander_write`, `input_set_hw`, `njw1194_write`) receives the same argument sets.
- IR sweep: 256 commands x 5 states (standby, home, volume, volume_hp, menu), every
  screen compared against fast-lcd (home outside our bands, volume against
  `hn_volpage`'s own reference render, everything else pixel-identical); sweep runs in
  71 s.

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
- **Main-loop timers: the volume page draws slower than in fast-lcd.** `vol_up` and
  `vol_down` take 60 ms to settle against fast-lcd's 40 ms (the table above). The cost is
  `hn_wipe`: it takes 46.6 ms against fast-lcd's 9.9 ms stock clear, while `hn_vol_static`
  takes 7.4 ms and the volume draw at 0x5936 takes 3.7 ms in both images. The first volume
  write after a key press lands about 37 ms later than on fast-lcd. The tour's audio-state
  check still shows the same 160 states in the same order, none more than 0.10 s later
  than fast-lcd, and `back_home` / `vol_timeout` return home within 0.1 s of fast-lcd, so
  the slower draw does not visibly displace the timers that pace power-on, mutes or the
  return-home countdown.
- **RAM 0x48:0x49 (the theme colour) is changed while drawing.** `hn_begin` saves it to
  XDATA `HN_THEME` and `hn_accent`/`hn_white` overwrite it so the stock glyph painters
  pick up the accent or white ink; `hn_end` restores it before returning. Every hn_*
  drawing path (`hn_draw_volume`, `hn_vol_static`, `hn_clear`'s wipe, `hn_home_tail`) is
  bracketed this way, and the tests check the colour is back afterwards in every case.
- **Recovery: unchanged.** The reset vector, the standby key handler (0x59B2) and
  `read_key`'s Source-in-standby jump to the bootloader (0x3DB8) are untouched.

## What to look for on the amp

- Turning the knob or pressing Vol+/Vol-: the accent edge sweeps in from the right as
  the volume page opens. There is no exit wipe; home returns through the stock fast
  clear.
- Digits on the volume page: sharp and unbroken at 2x size (60 x 64), no torn columns or
  swapped bytes (a dropped byte on the panel bus shows as a colour shift, as noted in
  `features/blit-test`'s README).
- Accent colour: SMSL orange (0xff8a1f) on the White COLOR theme, the COLOR tint on
  every other theme, on both the home accent bar and the volume page's "VOL" label,
  divider is not tinted (fixed dark grey, 0x2104), and the position line.
- Home screen: input name and status line left-aligned at x 16, not centred.
- Menus: unchanged, still centred.
- Volume page returns home 2 s after the last step, same as stock.

## How to go back

Flash `features/fast-lcd/build/flash_fastlcd.bin` (stock UI, fast pixel path) or
`features/direct-select/build/flash_patched.bin` (stock UI, stock pixel path, direct
input selection over IR).

## Files

- `build_patch.py` builds `build/flash_house_numerals.bin` from
  `features/fast-lcd/build/flash_fastlcd.bin` and writes the listing
  `house_numerals.asm`.
- `emu_test.py` runs the unit tests, the full-firmware tour and the IR sweep above.
