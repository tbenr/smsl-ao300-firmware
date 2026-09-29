# House Numerals

A reduced build of study 3 ("House Numerals", after SMSL's SU and DO series screens) from
`features/ui-theme/ui_themes.html`. Built on top of fast-lcd. The RESET page shows
`v1.4 tbenr hn4`.

This is the fourth image ("hn4"). The wipe into the volume page no longer blocks anything:
it runs one step per 10 ms main-loop tick, eased, and there is now a wipe back home too.
All our text goes through a new streaming text painter.

Earlier images:
- hn3 (`v1.4 tbenr hn3`, sha256 `2c4809ab…`) and hn2 (`2819e0b0…`) drew a 200 ms wipe inside the
  volume-key handler, which stopped the main loop.
- The first image (`v1.4 tbenr hn`, `deada16a…`, 47 ms wipe) is the only one flashed so far.

## Status

Emulator-verified (all tests pass). Not yet tried on hardware (hn4, `v1.4 tbenr hn4`).

## What the build shows

| Element | Build |
|---|---|
| Home: input name | stock big font and y (75), left-aligned at x 16 on page 1 only |
| Home: status line | stock small font and y (135), left-aligned at x 16 on page 1 only |
| Home: accent bar | 28 x 3 at 18,114 (under the name) |
| Home: icon, volume, tags | stock, unchanged |
| Volume page: name | small font, white, at 16,30 |
| Volume page: divider | 1 x 104 at 140,14, colour 0x2104 |
| Volume page: label | "VOL" in accent, small font, at 158,14 |
| Volume page: number | stock big digits at 2x (60 x 64 each), white, at 184,42 and 244,42; leading zero blank |
| Volume page: position line | 240 x 3 at 40,136: accent for 4 px per step, 0x18E3 for the rest |
| Wipe in | 2-px accent edge from x 318 to 0 over 20 ticks (about 200 ms), ease-in-out; black behind it; each element appears once the edge has passed it |
| Wipe out | the same from x 0 to 318; the home elements appear once the edge has passed them |
| Accent | theme colour (RAM 0x48:0x49); SMSL orange 0xFC43 when the theme is White (0xFFFF) |

Still cut from the mockup: number roll, spring on the line, dB readout and captions, MUTE state
and status text on the volume page.

## How the wipes work

### Driver: one step per tick

The main loop (0x540A) calls `main_tasks_on` (0x5B22) when the amp is on. `main_tasks_on`
calls `main_tick_tasks` (0x3325) at 0x5B2A:
- `main_tick_tasks` first handles the re-mute request 0x21.4;
- if the 10 ms tick flag 0x20.7 is set, it runs `main_tick_10ms` (0x3335): countdowns,
  page renders, the periodic home refresh, format poll, unmute.

The `lcall 0x3325` at 0x5B2A becomes `lcall hn_tasks`. `hn_tasks` looks at the tick flag first.
- No tick: it tail-jumps to 0x3325, which does exactly what it did before.
- Tick: it calls 0x3325, then, if RAM 0x4F is 1 (amp on), runs `hn_step`.

The step comes after all of that tick's stock work. A page render in the same tick (for
example the Timer0 return home) has already started the wipe, and the unmute and format
poll are never delayed by a step. Hooking this call was chosen over:
- the flag test at 0x332F, which would put the step before the tick's duties;
- the main loop's `lcall 0x5B22` at 0x5422, where `post_power_on` and the power-off path
  share the call.

A step never waits. The main loop keeps its timing, and a lost tick only delays the wipe
by one tick.

### A step (`hn_step`)

State lives in XDATA: mode (0 idle, 1 in, 2 out), step 0..20, edge x. `ease` holds 21 edge
positions for the way in: `round(318 (1 + cos(pi k / 20)) / 2)`, that is 318 316 310 301 288
271 252 231 208 184 159 134 110 87 66 47 30 17 8 2 0. The way out uses 318 - x. The table is
symmetric, so turning a wipe round maps step k to 20 - k at the same x.

Each step:
1. Takes the next x.
2. Fills the band the edge swept since the last step with black (the new page's background).
3. Marks as "not on screen" every element of either page that the band or the edge
   columns touched.
4. On the way in, redraws the part of the position line inside the band.
5. Draws the 2-px accent edge at [x, x+1], except on step 20, where the band runs to the
   screen edge.
6. Draws every element of the new page that is not on screen and that the edge has fully
   passed:
   - on the way in, when its left edge is right of the edge (x0 >= x + 2);
   - on the way out, when its right edge is left of it (x1 < x);
   - on step 20, everything.

The wipe ends after step 20.

| Way in: element | Columns | Appears at step (edge x) |
|---|---|---|
| number box | 184..303 | 10 (159) |
| "VOL", divider | 158..199, 140 | 11 (134) |
| position line | 40..279 | drawn in parts inside each band; in full at 16 (30) |
| name | 16.. | 18 (8) |

| Way out: element | Drawn by | Appears (OPTICAL, "No signal") |
|---|---|---|
| output icon 15..44, accent bar 18..45 | `home_draw_output_icon` 0x5744, `hn_fill` | 5 (47) |
| volume 48..75 | `home_draw_volume` 0x5916 | 7 (87) |
| status line 16..16+14n-1 | `hn_paint`, small font, buffer XDATA 0x50 | 11 (184): once the stock refresh has loaded the buffer, and the edge has passed its end |
| input name 16..end of the text | `hn_paint`, big font, buffer XDATA 0x35 | 13 (231); USB 8 (110), BT 7 (87) |
| format tag 208..263 | `home_draw_format_tag` 0x41CA | 15 (271) |
| EQ tag 266..307 | `home_draw_eq_tag` 0x49A1 | 18 (310) |

The status line waits for its buffer:
- The stock refresh loads XDATA 0x50 10 ticks after the return home (0x27:0x28 = 10 after
  the render). `hn_hold` notes when it has run (`HN_SBUF`).
- The status line is drawn on the first step after that on which the edge has passed its
  end. On step 20 it is drawn in any case.
- The name is loaded into XDATA 0x35 at the start of the exit, as `home_draw_input_name` does
  (`big_text_load` 0x4C8F with the string from its table; input 7: the buffer as it is).

### Entry (home -> volume page)

`hn_enter_vol` starts the entry. It is called:
- by the four volume-key sites (0x0D33, 0x0DB3, 0x0E5A, 0x0F02: `lcall hn_enter_vol ; sjmp`
  past the stock "volume" caption);
- through the page-2 renderer path, 0x2106 (`hn_clear` with page 2).

It draws nothing. It clears the two text buffers, as the stock `ui_clear_screen` did at those
places, and sets mode 1, step 0, x 318. If the page is already on screen or an entry is
running, it does nothing. If an exit is running, it turns it round.

The key handler's common tail (0x0F48) still writes the volume to the NJW1194 first, then
calls 0x5936 (`hn_draw_volume`).
- During a wipe, `hn_draw_volume` only records the value (`HN_VOL`, `HN_NUM`). It draws the
  number and the line only if the wipe has already revealed them.
- The wipe draws them with the latest value when it reaches them.
- Without a wipe, a volume change redraws the number and the line, as before.
- The page-2 renderer (0x2143, `hn_volpage`) does the same during a wipe, and draws the whole
  page when idle.

In the emulator the volume write comes 0.2 to 15 ms before the first step. Nothing is drawn
in between.

### Exit (volume page -> home)

The stock path is:
1. The Timer0 ISR counts RAM 0x3F:0x40 down (armed at 200 by the key tail) and at 0 sets page
   1 and 0x22.3 (`t0_return_home` 0x3ED9).
2. The next tick's render calls `ui_render_page(1)`, which clears the screen at 0x2106. Page 1
   has no renderer. 0x27:0x28 is set to 10.
3. 10 ticks later `main_tick_10ms` calls `home_refresh_periodic` (0x3FE3). It loads the status
   line into XDATA 0x50, then at 0x4081 calls `home_refresh` 0x5C8B and `small_text_render`
   0x3A53 at y 135.
4. It runs again every 50 ticks.

hn4 changes two of those steps:
- `hn_clear` at 0x2106, with page 1 and the volume page on screen (or an entry running),
  starts the exit (mode 2 from x 0) instead of clearing. It clears the text buffers (as
  `ui_clear_screen` did), loads the name and measures where it ends.
- At 0x4081 the `lcall home_refresh` becomes `ljmp hn_hold`. While a wipe runs, `hn_hold`
  returns at once (0x4088 is a tail jump, so this is 0x3FE3's own return): no `home_refresh`,
  no status line. It notes that the status buffer is loaded. Otherwise it does
  `lcall home_refresh ; ljmp 0x4084`, as stock.

The stock refresh therefore draws nothing during the exit. Its next run, 0.41 s after the
exit ends, draws exactly the same pixels over the revealed screen (tested). The end state
is the hn3 home screen.

### Interruptions and how a wipe is cancelled

- **Any stock clear cancels.** The first instruction of `ui_clear_screen` (0x5D42, 16
  callers: menu, Source, standby, the other pages, `post_power_on`, "go home" on page 2)
  becomes `ljmp hn_cancel`. `hn_cancel` sets mode, the volume-page flags and the home flags
  to 0, then runs the stock clear (`lcall 0x5CBC ; ljmp 0x5D45`). `hn_clear` for any other
  page, and for page 1 while an exit already runs, goes the same way.
- **Volume key during the entry:** the value is recorded and drawn when revealed (or at once
  if its box already is).
- **Volume key during the exit:** the key handler sets page 2. `hn_enter_vol` turns the wipe
  round at its x (step 20 - k), and the edge heads left again. Volume-page elements the
  exit had not touched are still on screen and stay. The rest are redrawn as the edge passes
  them. The number on screen is redrawn at once with the new value.
- **Source, direct-select, or any other name draw on page 1 during the exit:** the hook on
  `home_draw_input_name`'s first instruction (0x4A85, `hn_name_guard`) cancels the exit and
  runs the stock clear first, then the stock name draw.
- **Menu (NEC 0x04):** during the exit it opens the menu through the stock clear, which
  cancels. During the entry the page is 2, so `read_key` turns it into "go home"
  (0x3DD6), whose clear cancels.
- **Power off:** the standby path (0x5B0B) calls `ui_clear_screen`, which cancels. The
  driver also steps only while 0x4F is 1. Standby looks exactly as stock (tested).
- **Power on:** `post_power_on` ends with `ljmp ui_clear_screen`, so the wipe state is reset
  before the first step. XDATA after a cold start is not trusted: a mode other than 0/1/2
  stops the wipe.
- **A volume key during the power-on logo:** it is dispatched just before `post_power_on`.
  Its entry wipe starts, then `post_power_on`'s clear cancels it, and home comes up as
  stock.

## The text painter (`hn_paint`)

`hn_paint` is a general text painter, built for later passes (per-element tint, number roll,
clipped reveals, new fonts). It is used for all our text:
- the volume page's name, "VOL" and number;
- the exit's name and status line.

Outside the wipes, the home screen is still drawn by the stock `big_text_render` /
`small_text_render`.

- **Parameters.** An XDATA block at 0x0130:

  | Parameter | Meaning |
  |---|---|
  | font | pointer to a font descriptor in code |
  | string | pointer and space (0 XDATA, e.g. the stock buffers 0x35 / 0x50; 1 code) |
  | x, y | position |
  | ink, background | RGB565 colours |
  | clip x0..x1 | x clip window: only those columns are drawn |
  | scale | 1 or 2 |

- **Result.** `FP_END` is the last column of the last cell. An empty clip window measures
  without drawing.
- **Font descriptor.** Glyph width, bytes per column, bytes per glyph, glyph data, a
  96-entry character map (0x20..0x7F -> glyph index, bit 7 = narrow) and the narrow advance.
  - Small font: 0x5DAB, 14 x 24, 42 bytes per glyph. It maps the characters
    `small_glyph_paint` 0x2DF8 maps: space . : - + = 0-9 A-Z a-z < > { } ( ) ! '.
  - Big font: 0x6A23, 30 x 32, 120 bytes per glyph. It maps space . : - + = 0-9 A-Z, and
    space . - + = I advance 17 px (big_text_render 0x2A9E).
  - Characters the stock painters do not map (they reuse the previous glyph) draw blank.
- **Drawing.** Every cell is drawn in full (background included), and cells may overlap as
  in stock. At scale 2 each glyph column and row is doubled; this replaces hn3's
  `hn_digit2x`. Pixels are streamed on the fast-lcd bus pattern, unrolled per bit:
  3.68 ms for OPTICAL (6720 px, 13.1 clocks per pixel), 3.04 ms for two 2x digits (7680 px,
  9.5), 1.84 ms for "2.8224MHz".
- **Layout.** `hn_home_x` computes where the stock renderer starts a text on page 1:
  - centred, `(320 - n*w) / 2`, or `(333 - n*w) / 2` when a big text has a narrow character;
  - then x 16 as `hn_align_*` do, unless the text is wider than 288 px.
- **Tested against stock.** Every mapped character in both fonts, and 38 big-font and 85
  small-font strings, in two themes:
  - all input names (USB, OPTICAL, COAXIAL, BT, ARC, AUX, PHONO);
  - every printable string in the firmware's string area;
  - every sample-rate text `status_rate_text` 0x3CDC produces;
  - a 294-px string that stays centred.

  The painter's output is pixel-identical to `big_text_render` / `small_text_render` on
  page 1. Clip windows at both scales, with odd edges and empty windows, give exactly the
  columns of a full paint.
- **Number blank.** The number's blank tens digit is 0x7F, which maps to the blank glyph at
  full width; a space would be narrow.

## Timing

Worst step measured: **5.36 ms**, on the exit with the OPTICAL/COAXIAL name (3.7 ms name plus
a 23-px band). Per-step times, unit test, 20 steps each:

| Wipe | Steps (ms) | Worst |
|---|---|---|
| Entry | 0.3 0.6 0.8 1.0 1.3 1.4 1.6 1.7 1.8 **4.9** 2.5 1.8 1.7 1.6 1.4 1.6 1.0 2.2 0.6 0.3 | 4.88 ms (number box) |
| Exit, OPTICAL | 0.3 0.6 0.8 1.0 2.3 1.4 3.0 1.7 1.7 1.8 3.8 1.7 **5.4** 1.5 4.3 1.3 1.0 3.0 0.6 0.3 | 5.36 ms (name) |
| Exit, USB | … 3.2 (name) … 3.8 (status) … **4.3** (format tag, stock 2.9 ms) … | 4.32 ms |
| Exit, BT | … 4.1 (volume + name) … **4.4** (status) … | 4.45 ms |

In the whole firmware the worst step seen is 4.91 ms (tour, entries) and 5.36 ms (optical
exit). For comparison, the stock periodic home refresh blocks the main loop for about 45 ms
every 0.5 s.

## Per input (emulator, Vol+ from home, whole firmware against fast-lcd)

The wipe runs everywhere. The audio states come in the same order as fast-lcd, none more
than 0.10 s later.

| Situation | Entry and exit | Unmute vs fast-lcd |
|---|---|---|
| Bluetooth, no stream (countdown held at 40..50) | both wipe | no unmute in either image |
| Optical without signal (held at 100) | both wipe | none in either |
| Headphone output, P2.6 low (held at 300) | both wipe | none in either |
| USB, 7.4 s after power-on | both wipe | 0.03 s earlier |
| HDMI, 0.5 s after the switch | both wipe | 0.03 s earlier |
| USB, 0.05 s after switching from HDMI | both wipe | 0.03 s earlier |
| USB, unmute due within the wipe | both wipe | 0.02 s earlier |
| Vol+ during the power-on logo | wipe starts, `post_power_on` cancels it | 0.03 s earlier |

Earlier, because fast-lcd's own 40 ms volume draw loses ticks and the wipe does not.

## Hooks

Fourteen hook sites: ten 3-byte hooks, plus the four places the volume keys open the
volume page. Every stock byte is asserted by `build_patch.py`.

| Address | Stock bytes | Now | What |
|---|---|---|---|
| 0x2106 | `12 5D 42` lcall `ui_clear_screen` | lcall `hn_clear` | `ui_render_page`'s clear: page 2 starts the entry, page 1 with the volume page on screen starts the exit; otherwise cancel + stock clear |
| 0x2143 | `02 21 67` ljmp `volpage_render` | ljmp `hn_volpage` | page-2 jump-table entry |
| 0x5936 | `AB 07 E5` | ljmp `hn_draw_volume` | number and line; only recorded during a wipe |
| 0x2A25 | `E4 78 02` | ljmp `hn_align_big` | page 1: stored start x 16 |
| 0x3A82 | `E4 78 02` | ljmp `hn_align_small` | the same, status line |
| 0x5C99 | `02 59 16` | ljmp `hn_home_tail` | `home_refresh`'s tail: volume as stock, then the accent bar |
| 0x5B2A | `12 33 25` lcall `main_tick_tasks` | lcall `hn_tasks` | the driver: one wipe step after each tick |
| 0x4081 | `12 5C 8B` lcall `home_refresh` | ljmp `hn_hold` | periodic refresh held back during a wipe |
| 0x5D42 | `12 5C BC` (`ui_clear_screen`'s first call) | ljmp `hn_cancel` | every stock clear cancels a wipe |
| 0x4A85 | `E5 47 14` (`home_draw_input_name`) | ljmp `hn_name_guard` | a name drawn during an exit cancels it first |
| 0x0D33, 0x0DB3, 0x0E5A, 0x0F02 | `12 5D 42 7B FF …` | `12 A0 B8 80 11` (lcall `hn_enter_vol` ; sjmp site+0x16) | volume-key entry sites A-D |

## Memory

- **Code:** 3986 bytes of patch code at 0x9800..0xA791, plus the version string at 0xA792.
  Image length 42913 bytes, under the 0xF400 split. `house_numerals.asm` is the generated
  listing.
- **XDATA** 0x0100..0x0155. The EEPROM sectors and everything fast-lcd/direct-select use
  stay untouched.

| Address | Name | Holds |
|---|---|---|
| 0x0100, 0x0102 | `HN_N`, `HN_C` | `hn_fill`'s pixel count and colour |
| 0x0104 | `HN_VOL` | the volume shown (0..60) |
| 0x0105..0x0107 | `HN_NUM` | its two characters and a NUL (tens blank: 0x7F) |
| 0x0108 | `HN_MODE` | 0 idle, 1 wipe in, 2 wipe out |
| 0x0109 | `HN_VF` | volume-page elements on screen (name, divider, VOL, number, line) |
| 0x010A | `HN_HF` | home elements drawn by the exit (icon, volume, bar, name, format, EQ, status) |
| 0x010B | `HN_STEP` | step 0..20 |
| 0x010C | `HN_SBUF` | the stock refresh has loaded the status buffer during this exit |
| 0x010D, 0x010F | `HN_X`, `HN_XP` | edge x, previous x |
| 0x0111 | `HN_LIM` | this step's reveal limit |
| 0x0113, 0x0115 | `HN_D0`, `HN_D1` | damaged columns (band and edge) |
| 0x0117, 0x0119 | `HN_B0`, `HN_B1` | the band |
| 0x011B, 0x0123 | `HN_NAMER`, `HN_STATR` | right end of the home name / status line |
| 0x011D, 0x011F, 0x0121 | `HN_S0`, `HN_S1`, `HN_SPL` | `hn_line_seg`: columns, 40 + 4 * volume |
| 0x0130..0x0140 | `FP_*` | `hn_paint`'s parameters |
| 0x0141..0x0155 | `FP_*` | `hn_paint`'s work area |

- **Stack:** the tour (with two entries and two exits) was run with a canary above SP. The
  deepest idata used is 0xAF, the same as fast-lcd.

## Emulator results

`python3 tools/run_tests.py` gives **ALL PASS** for every feature, 105 s wall (house-numerals
105 s, most of it the 65 s sweep). `emu_test.py` has four groups: `unit`, `tour`, `int1`, `sweep`;
`unit tour` alone runs in about 35 s.

- **Image diff:** only the fourteen hook sites (plus the version pointer) differ from
  fast-lcd inside the base image. The labels in `SmslAo300Labels.java` match this build.
- **Painter:** see above. `hn_fill` runs at 9.0 clocks per pixel.
- **`hn_draw_volume`:** every value 0..60 in three themes. It records and skips drawing
  during a wipe unless the box or line is revealed.
- **`hn_step`, unit:** starting from a pattern screen, each of the 20 entry steps checks:
  - x from the table;
  - the old page left of the edge, then the accent edge;
  - the volume page right of it with only the passed elements (and the line in parts);
  - the element flags.

  The same for the exit on three inputs, including the status-buffer rule. Both end
  pixel-identical to `hn_volpage` / the stock home refresh. Reversals after steps 1, 5, 10
  and 19 each way end on the right page; the exit reversal redraws with the new volume.
- **Logic:** `hn_enter_vol` and `hn_clear` in every mode; `hn_cancel` from both modes;
  `hn_hold` in each mode; `hn_name_guard`; `hn_tasks` (a step only after a tick, only with
  0x4F = 1); a bogus mode stops.
- **Tour** (whole firmware, lockstep with fast-lcd, real Timer0 ISR):
  - each step lands on the same page, power, volumes, input and output;
  - home screens as fast-lcd outside our bands, with the bar; volume pages exactly as
    `hn_volpage`; menus and standby identical;
  - both entries and both exits take 20 steps with the table's x, and the screen at entry
    step 10 is checked;
  - the volume write comes before the first step;
  - the stock home refresh is held during the exit and resumes 0.41 s after it, drawing the
    same pixels;
  - home comes back at the same moment as fast-lcd (within 0.05 s);
  - 160 audio states in the same order, none more than 0.10 s later; same argument sets for
    every audio writer.
- **Per input:** the eight scenarios above, each checking entry, exit, screens, the unmute
  and the audio.
- **Keys during a wipe:** 11 scenarios, each with the final screens and audio checked
  against fast-lcd:
  - Vol+ during the entry;
  - Vol+ and Vol- during the exit (turned round);
  - Menu, Source, Power and direct-select (HDMI), each during the entry and during the exit.
- **INT1** (`int1`, 100 whole-firmware runs per image, 7 s):
  - Setup: USB, settled, Vol+ from home with INT1's RAM effects injected at the press
    (0x21.4, 0x43:0x44 = 30, 0x4E = 0xFF), the press moved in 1 ms steps across one
    10-tick format-poll period.
  - Results: the DAC reconfiguration (0x46A0) always comes before the unmute, and the unmute
    is 0.02-0.03 s earlier than fast-lcd.
  - The audio states match in order and time at 99 offsets. At offset 66 the press and a
    format poll fall in the same tick, and the two images take them in a different order:
    fast-lcd the key first, hn4 the poll first. Both orders are stock behaviour: from 65 to
    72 ms both images take the poll first. The main loops are just not in the same phase, so
    that edge is one millisecond apart. The test lists such offsets and allows at most two.
- **IR sweep:** 256 commands x 5 states, against fast-lcd, all screens as expected, 65 s.
- **Audio comparison at the end of a run:** both images stop at the same clock. A state
  fast-lcd reaches in the last 0.10 s may therefore still be to come in hn4, which is up to
  0.10 s later by design of the check. The comparison requires the states up to 0.10 s
  before the end to match one for one, and the rest to continue the same sequence.
- **Videos:** `tools/emu/panel_video.py features/house-numerals/build/flash_house_numerals.bin OUT`
  shows the entry, two redraws and the exit.
  - `--press 0.5:0x13 --press 5.0:0x0A --seconds 8.5`: Bluetooth.
  - `--press 0.5:0x0A --press 2.6:0x0A --seconds 5.5`: an exit turned round by Vol+.

### Coverage gaps

- The tour reaches volume-entry sites 0x0D33 (`key_volume_up`) and 0x0F02 (`key_volume_down`)
  only. 0x0DB3 and 0x0E5A (key codes 0x5A/0x5B, probably a held key) are covered by the
  per-site unit test.
- `key_59` (0x0F62) and `key_output_toggle` (0x1006) draw home parts on page 1 without the
  name path or a clear. If they come during an exit, they draw over the half-revealed screen
  until the exit reaches them; the exit's own reveal then redraws the same parts. No test
  presses them during an exit.
- `home_refresh_periodic`'s flag path (0x21.3, 0x21.1 or 0x20.6 set, after a Source-type
  key) draws at 0x412F before 0x4081, so `hn_hold` does not hold that part back. Those keys
  cancel the exit through the name guard first.

## Risks

- **Panel timing: same as fast-lcd.** `hn_fill` and `hn_paint` use fast-lcd's byte timing (the
  WR pulse `features/blit-test` proved on the panel).
- **The main loop now runs during the wipes.** A step is at most 5.4 ms, after the tick's own
  work. The volume keys, format poll, unmute and re-mute run as on fast-lcd (tested
  against it, including the INT1 case the hn3 review raised).
- **Stock routines called from a step** (`home_draw_output_icon`, `home_draw_volume`,
  `home_draw_format_tag`, `home_draw_eq_tag`, `big_text_load`) run in the main loop, as
  they do from `home_refresh_periodic`. The stack peak is unchanged (0xAF).
- **Recovery: unchanged.** The reset vector, the standby key handler (0x59B2) and
  `read_key`'s Source-in-standby jump to the bootloader (0x3DB8) are untouched.

## What to look for on the amp

- Vol+/Vol- on home: the volume changes at once. The accent edge sweeps in from the right,
  slow at the ends and fast in the middle, about 200 ms. The number appears when the edge
  has passed it, then VOL and the divider, then the line and the name.
- 2 s after the last key: the edge sweeps back to the right. The icon, volume and bar
  appear first, then the status line and name, the format tag, and the EQ tag last. The
  finished screen must not change when the periodic refresh comes about 0.4 s later.
- Vol+ while the edge is going back: it turns round and the volume page comes back with the
  new value.
- Menu, Source, Power or a direct input key during either wipe: the wipe stops and the
  stock screen follows, without leftovers of the volume page.
- On Bluetooth, optical without signal, headphones, right after power-on or an input
  switch: the same wipes; the unmute comes at the same moment as without a key.
- Digits sharp at 2x, no torn columns or colour shifts (a dropped bus byte shows as a
  colour shift, see `features/blit-test`).
- Accent: SMSL orange on the White theme, the theme colour otherwise.

## How to go back

Flash `features/fast-lcd/build/flash_fastlcd.bin` (stock UI, fast pixel path) or
`features/direct-select/build/flash_patched.bin` (stock UI, stock pixel path, direct
input selection over IR).

## Files

- `build_patch.py` builds `build/flash_house_numerals.bin` from
  `features/fast-lcd/build/flash_fastlcd.bin` and writes the listing
  `house_numerals.asm`. It uses the text instructions added to `tools/patch/asm51.py`
  (`Asm.op`, `#hi(label)` / `#lo(label)`).
- `emu_test.py` runs the unit tests, the whole-firmware scenarios, the INT1 sweep and the IR
  sweep above.
