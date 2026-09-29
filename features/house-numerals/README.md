# House Numerals

A reduced build of study 3 ("House Numerals", after SMSL's SU and DO series screens) from
`features/ui-theme/ui_themes.html`. Built on top of fast-lcd. The RESET page shows
`v1.4 tbenr hn6`.

This is image hn6 (sha256 `7b74e950…`): hn5 with the larger sizes picked on the amp's feedback,
the home layout now read from `layout.json`, which `sizing.html` writes (see "Layout" below).

hn5 (`v1.4 tbenr hn5`, sha256 `510fd138…`) made the home screen the mock's, drawn in the mock's
own typefaces: speaker icon and volume top left, the tags as accent boxes top right, the input
name in the condensed display face, the status line in grey mono under it, the accent bar
below. See "The home screen" below. The volume page and the wipes are hn4.1's.

hn4.1 (`v1.4 tbenr hn4.1`, sha256 `5eddb6df…`) made the wipe into the volume page non-blocking:
one step per 10 ms main-loop tick, eased, and a wipe back home too. It fixed three things found
in hn4 (`v1.4 tbenr hn4`, sha256 `86aacb8b…`):
- **The edge could vanish for a whole panel frame.** hn4 erased the old edge (with the band)
  before it drew the new one. The new edge now comes first, and the old edge's columns are
  erased last.
- **The stock refresh's flag path could damage the exit.** After a Source press, the flag path
  (0x3FF8) could run mid-exit and black out revealed parts at 0x412F. It now skips that fill
  during a wipe.
- **A name drawn during an exit left the screen incomplete.** Such a draw (Source,
  direct-select, the BT key's home_refresh) cleared the screen in the middle of stock sequences
  that had already drawn other parts. It now ends the exit with the whole home screen.

Earlier images:
- hn3 (`v1.4 tbenr hn3`, sha256 `2c4809ab…`) and hn2 (`2819e0b0…`) drew a 200 ms wipe inside the
  volume-key handler, which stopped the main loop.
- Flashed so far: the first image (`v1.4 tbenr hn`, `deada16a…`, 47 ms wipe) and hn4.1.

## Status

hn6: emulator-verified (all tests pass), not yet tried on the amp.

hn5: emulator-verified. Tried on the amp on 2026-09-29: looks great, and the
anti-aliased text works well on the panel, but the tags, the status line (sample rate) and the
volume are too small at the panel's size. A redesign of the sizes is next.

Tried on the amp on 2026-09-29: hn4.1 (`v1.4 tbenr hn4.1`, `5eddb6df…`) looks OK. Longer use
is still to come.

## What the build shows

| Element | Build |
|---|---|
| Home: icon | the mock's speaker at 23 px, 12,7, white; red with an X when muted (bit 0x22.1); headphones on the headphone output |
| Home: volume | Barlow Condensed 36 px, white, at x 47, baseline 29, no leading zero |
| Home: tags | IBM Plex Mono 13 px in the accent, in 1-px accent boxes 10 px wider than the text, rows 9..29: the EQ box 276..309, the format box ending at 269 |
| Home: input name | Big Shoulders Display 52 px, white, at x 16, baseline 104, 1 px letter spacing |
| Home: status line | IBM Plex Mono 20 px, grey #8a9096, at x 18, baseline 140, 1 px letter spacing |
| Home: accent bar | 28 x 3 at 18,150 |
| (hn5) | speaker 16 px, volume 22, tags 10 in 17-px boxes, status 12 at baseline 132, bar at y 144 |
| Volume page: name | small font, white, at 16,30 |
| Volume page: divider | 1 x 104 at 140,14, colour 0x2104 |
| Volume page: label | "VOL" in accent, small font, at 158,14 |
| Volume page: number | stock big digits at 2x (60 x 64 each), white, at 184,42 and 244,42; leading zero blank |
| Volume page: position line | 240 x 3 at 40,136: accent for 4 px per step, 0x18E3 for the rest |
| Wipe in | 2-px accent edge from x 318 to 0 over 20 ticks (about 200 ms), ease-in-out; black behind it; each element appears once the edge has passed it |
| Wipe out | the same from x 0 to 318; the home elements appear once the edge has passed them |
| Accent | theme colour (RAM 0x48:0x49); SMSL orange 0xFC43 when the theme is White (0xFFFF) |

Still cut from the mockup: the volume page in the mock's typefaces, number roll, spring on the
line, dB readout and captions, MUTE state and status text on the volume page, and the reddish
status line without a signal on the home screen.

## The home screen

Every home element is drawn by our code, in fonts made from the mock's typefaces
(`tools/fonts/`, packed by `tools/patch/pfont.py`, drawn by the kit's `uk_text`). Rather than
replacing `home_refresh` and every stock sequence that draws parts of the home, each element's
own stock painter is replaced. The periodic refresh, Source, direct-select, the BT key, the
EQ key and the rest all call these painters in their own order, so they all draw ours:

| Element | Stock painter | Ours |
|---|---|---|
| icon | `home_draw_output_icon` 0x5744 | `hm_icon`: speaker, muted speaker (red) or headphones, as the stock picks icon 3, 1 or 2 |
| volume | `home_draw_volume` 0x5916 | `hm_volume`: the speaker or headphone volume, as stock |
| EQ tag | `eq_tag_paint` 0x4F18 (only caller: `home_draw_eq_tag`) | `hm_eq` |
| format tag | `home_draw_format_tag`'s `lcall small_text_at` (0x425D) and its two `tag_box_clear` calls (0x41E8, 0x41FC) | `hm_fmt`, `hm_fmt_clear` |
| input name | `big_text_render` on page 1 at y 75 (hook 0x2A25, after its scan) | `hm_name`, from XDATA 0x35 |
| status line | `small_text_render` on page 1 at y 135 (hook 0x3A82) | `hm_status`, from XDATA 0x50 |
| accent bar | `home_refresh`'s tail (0x5C99) | `hn_home_tail` |

- **Text hand-over.** At 0x2A25 / 0x3A82 the stock renderers have scanned the string and
  computed the start x; nothing is on the stack. On page 1 at the name's or the status line's y
  our routine draws the buffer and returns for the renderer. The name's scan also sets or
  clears 0x22.4 (a narrow-character flag it shares with the mute logic); the hand-over keeps
  that (tested). Other page-1 texts start at x 16 as in hn4.1; other pages are stock. Big text
  at y 75 that is not a name (the EQ key's preset name, `eq_show` 0x3881) is drawn in the
  display face too: `NAME_CHARS` has A-Z, space, `.` and `-`.
- **No flicker.** Each element draws its cells with their background, then clears only what a
  longer text left to the right (`hm_rest`: to x 319 for the name and the status line, to the
  next element for the icon and the volume). The stock refresh redraws everything every 0.5 s;
  the pixels don't change. During a wipe `hm_rest` does nothing: the wipe's band is black and
  the element is only drawn once the edge has passed it.
- **Tags.** The stock strings are copied without trailing spaces ("PCM ", "DoP ", "MQA."). The
  EQ tags are all three letters, so the EQ box has one width (x 276..309); the format box ends
  at x 269 and is 34 or 42 px wide; the format tag's area is x 228..269 and is cleared up to the
  box. The tag arithmetic keeps x - 192 in 8 bits (the EQ box ends past x 255).
- **Colours.** Name and volume white, status grey, tags and bar in the accent (the COLOR tint;
  SMSL orange on White), the muted icon red. The stock tinted all of it.
- **Speed.** A whole home (home_refresh and the status line) takes 12.4 ms; the stock refresh
  took about 45 ms. The main loop now loses fewer ticks at the refreshes after power-on, so
  the first unmute comes 0.12 to 0.18 s earlier than on fast-lcd (see "Per input").
- **Fonts** (8997 bytes): the name face 3164 (A-Z, space, `.`, `-`), the status mono 3681 (the 59
  characters of every firmware string), the volume digits 992, the tag mono 769, the three
  icons 391, all 4-level anti-aliased run-length.

### Layout: `layout.json` and `sizing.html`

`build_patch.py` takes every home position and font from `layout.json`: each element's raster
(`tools/fonts/raster/<id>.json`), x, baseline, the tags' box rows and padding, the status colour
and letter spacing, the bar. Everything else (the clear-up-to columns, the tag areas, the exit
wipe's element columns) is derived from it, and the build asserts that the elements don't
overlap and that the tags stay right of x 192.

`sizing.html` edits it. Served by the font bench, it shows the home exactly as the firmware
draws it: it rasterises the fonts in the page with the same code as `raster.html`
(`tools/fonts/glyphs.js`) and packs and draws them with a port of `pfont.py`. The preview of
hn6's default state equals the emulator's screen pixel for pixel. It shows each font's cap
height on the panel in mm and its exact size in flash, and flags overlaps and texts wider than
the screen. **Save layout and fonts** writes the rasters of the chosen sizes (adding them to
`tools/fonts/specs.json`) and `layout.json`, with the slider values under `controls` and the
positions under `home`. Then rebuild by hand:

    python3 tools/fonts/rasterize.py         # the font bench; open the sizing page it prints
    python3 features/house-numerals/build_patch.py
    python3 tools/run_tests.py house-numerals

A new image needs its sha256 in `KNOWN_IMAGES` before `flash_ao300.py` flashes it.

## How the wipes work

### Driver: one step per tick

The main loop (0x540A) calls `main_tasks_on` (0x5B22) when the amp is on. `main_tasks_on`
calls `main_tick_tasks` (0x3325) at 0x5B2A:
- `main_tick_tasks` first handles the re-mute request 0x21.4;
- if the 10 ms tick flag 0x20.7 is set, it runs `main_tick_10ms` (0x3335): countdowns,
  page renders, the periodic home refresh, format poll, unmute.

The `lcall 0x3325` at 0x5B2A becomes `lcall uk_tasks`. `uk_tasks` looks at the tick flag first.
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
2. Draws the 2-px accent edge at [x, x+1] (outside the band), except on step 20, where the
   band runs to the screen edge.
3. Fills the band the edge swept since the last step with black (the new page's background).
   The old edge's two columns go last: on the way in they are the band's top end, and
   `uk_fill` goes up in x; on the way out they are its bottom end, so the rest of the band is
   filled first.
4. Marks as "not on screen" every element of either page that the band or the edge
   columns touched.
5. On the way in, redraws the part of the position line inside the band.
6. Draws every element of the new page that is not on screen and that the edge has fully
   passed:
   - on the way in, when its left edge is right of the edge (x0 >= x + 2);
   - on the way out, when its right edge is left of it (x1 < x);
   - on step 20, everything.

The wipe ends after step 20.

GRAM therefore always holds a whole edge between the first and the last step: the new one is
there before the old one goes. The panel reads one row (firmware x) per line time, 48 µs,
and a band column takes 64 µs to fill. So whichever way the scan runs, a frame that misses
the new edge still reads the old one before its columns are erased.

The `tour` group runs `panel_video.py`'s scan model over an entry and an exit, both scan
directions, at four frame phases. Every frame between the first and last step has a whole
2-px edge (hn4 failed this in 11 of the 16 cases).

| Way in: element | Columns | Appears at step (edge x) |
|---|---|---|
| number box | 184..303 | 10 (159) |
| "VOL", divider | 158..199, 140 | 11 (134) |
| position line | 40..279 | drawn in parts inside each band; in full at 16 (30) |
| name | 16.. | 18 (8) |

| Way out: element | Drawn by | Appears (OPTICAL, "No signal") |
|---|---|---|
| icon 12..45, accent bar 18..45 | `home_draw_output_icon` 0x5744 (`hm_icon`), `uk_fill` | 5 (47) |
| volume 47..82 | `home_draw_volume` 0x5916 (`hm_volume`) | 7 (87) |
| status line 18..end of the text | `hm_status`, buffer XDATA 0x50 | 11 (184): once the stock refresh has loaded the buffer, and the edge has passed its end |
| input name 16..end of the text | `hm_name`, buffer XDATA 0x35 | 11 (184); USB 8 (110), BT 6 (66) |
| format tag 228..269 | `home_draw_format_tag` 0x41CA (`hm_fmt`) | 15 (271) |
| EQ tag 276..309 | `home_draw_eq_tag` 0x49A1 (`hm_eq`) | 18 (310) |

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
  `home_draw_input_name`'s first instruction (0x4A85, `hn_name_guard`) ends the exit with the
  whole home screen (`hn_home_now`), then lets the stock name draw go on:
  - stop the wipe;
  - `lcd_clear_black`;
  - `home_refresh`, whose own name draw passes the guard;
  - the status line from XDATA 0x50, as `home_refresh_periodic` draws it.

  The stock sequences that get there have often drawn other home parts already, and a bare
  clear would lose them:
  - `key_bt_function` (IR 0x0E) calls `home_refresh` itself at 0x108E, so the EQ and format
    tags are drawn before the name;
  - Source with 0x21.3 or 0x21.1 set (0x0FA7, 0x0FE3) draws the EQ tag, icon and volume first.

  The text buffers are kept, so the BT key's own "BT Reconnect" status line still follows.
  The screen is a whole home 0.15 s after the key (tested for Source, direct-select, the BT
  key and the 0x21.3 Source path).
- **The refresh's flag path during a wipe:** Source (and `key_59`, `key_output_toggle`) set
  0x20.6, 0x21.3 or 0x21.1. They stay set until `home_refresh_periodic` runs on page 1,
  about 3 s after Source, so also across a volume page opened in that time. The exit's render
  then makes the refresh run 10 ticks into the exit, and its flag path (0x3FF8) would clear
  the flags, set page 1 and black out x 0..239, y 43..169 through the slow `0x412F` (125 ms),
  erasing revealed parts.
  - During a wipe, the hook at 0x3FF8 (`hn_flag_path`) does the flag and page part and skips
    the fill. The status line is loaded and the held refresh proceeds as usual, and the exit
    draws the home.
  - Tested: Source, then Vol+ 0.2, 1.0 and 2.0 s later. All 20 exit steps run, and two ticks
    after the exit the screen is a whole home.
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

## The text painter (`uk_paint`)

`uk_paint` is the kit's painter for the stock fonts (`tools/patch/uikit.py`, tested in
`tools/patch/uikit_test.py`). In hn5 it draws the volume page's name, "VOL" and number; the
home screen uses the kit's `uk_text` for the mock's typefaces (see "The home screen" and the
main README's "UI themes").

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
- **Layout.** `uk_home_x` computes where the stock renderer starts a text on page 1:
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

Worst step measured: **7.28 ms**, on the exit with the OPTICAL name and "No signal", which
the edge passes on the same step (step 11). The budget is 8 ms, inside the 10 ms tick.
Unit test, worst step per wipe:

| Wipe | Worst |
|---|---|
| Entry | 4.87 ms (number box) |
| Exit, OPTICAL, "No signal" | 7.28 ms (name and status line together) |
| Exit, USB, "2.8224MHz" | 3.69 ms |
| Exit, BT, "Searching..." | 4.23 ms |

In the whole firmware the worst step seen is 4.96 ms (entries) and 7.37 ms (optical exit).
That includes the `timer3_isr` calls that land inside a step, about 5 µs every 0.5 ms (before
`Amp` ran Timer3: 4.91 and 7.28 ms).
For comparison, a whole hn6 home takes 12.4 ms and the stock periodic home refresh blocks the
main loop for about 45 ms every 0.5 s.

## Per input (emulator, Vol+ from home, whole firmware against fast-lcd)

The wipe runs everywhere. The audio states come in the same order as fast-lcd, none more
than 0.10 s later. In hn5 the first unmute after power-on comes 0.12 to 0.18 s earlier than on
fast-lcd in every scenario: hn5's home refreshes are faster, so the main loop loses fewer
ticks while the unmute counts down.

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

Twenty-one hook sites: seventeen 3-byte hooks, plus the four places the volume keys open the
volume page. Every stock byte is asserted by `build_patch.py`.

| Address | Stock bytes | Now | What |
|---|---|---|---|
| 0x2106 | `12 5D 42` lcall `ui_clear_screen` | lcall `hn_clear` | `ui_render_page`'s clear: page 2 starts the entry, page 1 with the volume page on screen starts the exit; otherwise cancel + stock clear |
| 0x2143 | `02 21 67` ljmp `volpage_render` | ljmp `hn_volpage` | page-2 jump-table entry |
| 0x5936 | `AB 07 E5` | ljmp `hn_draw_volume` | number and line; only recorded during a wipe |
| 0x2A25 | `E4 78 02` | ljmp `hn_align_big` | page 1: at y 75 `hm_name` draws and returns; other texts start at x 16 |
| 0x3A82 | `E4 78 02` | ljmp `hn_align_small` | page 1: at y 135 `hm_status` draws and returns; other texts start at x 16 |
| 0x5C99 | `02 59 16` | ljmp `hn_home_tail` | `home_refresh`'s tail: the volume, then the accent bar |
| 0x5744 | `30 11 0B` (`home_draw_output_icon`) | ljmp `hm_icon` | the icon |
| 0x5916 | `AB 07 E5` (`home_draw_volume`) | ljmp `hm_volume` | the home volume |
| 0x4F18 | `7D 0A 7C` (`eq_tag_paint`) | ljmp `hm_eq` | the EQ tag |
| 0x425D | `12 4F 20` lcall `small_text_at` | lcall `hm_fmt` | the format tag |
| 0x41E8 | `02 00 26` ljmp `tag_box_clear` | ljmp `hm_fmt_clear` | no format (BT, ARC, AUX, PHONO): the tag's area black |
| 0x41FC | `12 00 26` lcall `tag_box_clear` | lcall `hm_fmt_clear` | the format changed: the same |
| 0x5B2A | `12 33 25` lcall `main_tick_tasks` | lcall `uk_tasks` | the driver: one wipe step after each tick |
| 0x4081 | `12 5C 8B` lcall `home_refresh` | ljmp `hn_hold` | periodic refresh held back during a wipe |
| 0x5D42 | `12 5C BC` (`ui_clear_screen`'s first call) | ljmp `hn_cancel` | every stock clear cancels a wipe |
| 0x4A85 | `E5 47 14` (`home_draw_input_name`) | ljmp `hn_name_guard` | a name drawn during an exit: the whole home first, then the name |
| 0x3FF8 | `C2 0B C2` (`clr 0x21.3; clr 0x20.6`) | ljmp `hn_flag_path` | the refresh's flag path during a wipe: flags and page as stock, the 0x412F fill skipped |
| 0x0D33, 0x0DB3, 0x0E5A, 0x0F02 | `12 5D 42 7B FF …` | `12 A0 B8 80 11` (lcall `hn_enter_vol` ; sjmp site+0x16) | volume-key entry sites A-D |

## Memory

- **Code:** 15558 bytes at 0x9800..0xD4C5 (8997 of them fonts), plus the version string at
  0xD4C6. Image length 54485 bytes; 7979 bytes are left under the 0xF400 split.
  `house_numerals.asm` is the generated listing.
- **XDATA** 0x0100..0x01A6. The EEPROM sectors and everything fast-lcd/direct-select use
  stay untouched.

| Address | Name | Holds |
|---|---|---|
| 0x0100, 0x0102 | `HN_N`, `HN_C` | `uk_fill`'s pixel count and colour |
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
| 0x0130..0x0140 | `FP_*` | `uk_paint`'s parameters |
| 0x0141..0x0155 | `FP_*` | `uk_paint`'s work area |
| 0x0160..0x0191 | `TP_*` | `uk_text`'s parameters and work area |
| 0x0192 | `HM_VS` | the home volume as text |
| 0x0196 | `HM_TAG` | a tag's text, trailing spaces cut |
| 0x019C..0x019E | `HM_TX`, `HM_TW`, `HM_TWD` | `hm_tag`: box x (- 192), box width, text width |
| 0x019F..0x01A4 | `HM_RL`, `HM_RY`, `HM_RH`, `HM_RX` | `hm_rest`: last column, rows, next column |
| 0x01A5, 0x01A6 | `HM_TR`, `HM_TL` | `hm_tag`: where the box ends, where the tag's area starts (- 192) |

- **Stack:** the tour (with two entries and two exits) was run with a canary above SP. The
  deepest idata used is 0xB3, the same as fast-lcd. That is stock's own peak: the delay
  leaves (0x0006, 0x0016) at SP 0xA0 with `timer3_isr` on top. Before `Amp` ran Timer3 the
  tour measured 0xAF (Timer0 ISR on top).

## Emulator results

`python3 tools/run_tests.py` gives **ALL PASS** for every feature, 116 s wall (house-numerals
116 s, most of it the sweep). `emu_test.py` has four groups: `unit`, `tour`, `int1`, `sweep`;
`unit tour` alone runs in about 50 s.

- **Image diff:** only the fifteen hook sites (plus the version pointer) differ from
  fast-lcd inside the base image. The labels in `SmslAo300Labels.java` match this build.
- **Home screen, against `home_model`.** The model is written in Python, independent of the
  8051 code. It reads the state (input, output, mute bit, volumes, EQ, format, the two text
  buffers) and draws with `PFont.render`, which the kit test proves pixel-identical to
  `uk_text`. The tag strings come from the stock tag routines run on the base image. Checks:
  - 55 states x 2 tints: every input, both outputs, muted, every EQ, every format and MQA
    variant, volumes 0..60, status lines. The whole screen equals the model.
  - A home drawn over a different one (longer name, status, volume, a format tag that goes)
    equals the model of the second.
  - All 82 firmware strings as the status line and (capitals) as the name: the element, the
    rest of its rows black, nothing else drawn.
  - The name hand-over leaves 0x22.4 as the stock scan does. During a wipe nothing is cleared
    after a shorter text.
- **Painter:** see the kit test. `uk_fill` runs at 9.0 clocks per pixel.
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
  `hn_hold` in each mode; `hn_name_guard`; `uk_tasks` (a step only after a tick, only with
  0x4F = 1); a bogus mode stops.
- **Tour** (whole firmware, lockstep with fast-lcd, real Timer0 ISR):
  - each step lands on the same page, power, volumes, input and output;
  - home screens equal to `home_model`; volume pages exactly as `hn_volpage`; menus and
    standby identical to fast-lcd;
  - both entries and both exits take 20 steps with the table's x, and the screen at entry
    step 10 is checked;
  - the volume write comes before the first step;
  - the home refresh is held during the exit and resumes 0.41 s after it, drawing the same
    pixels;
  - home comes back at the same moment as fast-lcd (within 0.05 s);
  - audio states in the same order, none more than 0.10 s later; same argument sets for every
    audio writer.
- **Per input:** the eight scenarios above, each checking entry, exit, screens, the unmute
  and the audio.
- **Keys during a wipe:** 14 scenarios, each with the final screens and audio checked
  against fast-lcd:
  - Vol+ during the entry;
  - Vol+ and Vol- during the exit (turned round);
  - Menu, Source, Power and direct-select (HDMI), each during the entry and during the exit;
  - Source late in the exit (step 18);
  - the BT key (IR 0x0E) during the exit on Bluetooth;
  - Source with 0x21.3 set during the exit.

  For keys on page 1 during the exit, the screen 0.15 s after the key must equal a whole
  refresh for that state, and the screen at the end must equal `home_model`.
- **Source, then Vol+ 0.2, 1.0 or 2.0 s later** (the refresh's flags still set, so its flag
  path runs mid-exit): 20 + 20 steps. Two ticks after the exit the screen is a whole home,
  and later it matches fast-lcd.
- **Panel scan:** see "A step" above.
- **INT1** (`int1`, 100 whole-firmware runs per image, 7 s):
  - Setup: USB, settled, Vol+ from home with INT1's RAM effects injected at the press
    (0x21.4, 0x43:0x44 = 30, 0x4E = 0xFF), the press moved in 1 ms steps across one
    10-tick format-poll period.
  - Results: the DAC reconfiguration (0x46A0) always comes before the unmute, and the unmute
    is 0.02-0.03 s earlier than fast-lcd.
  - Near a format poll the main loop takes the key's volume write or the poll's DAC
    reconfiguration first, depending on where in the loop and in the 10-tick poll period the
    press is seen. Both orders are stock behaviour. hn5's poll period is shifted against
    fast-lcd's, because fast-lcd's slower home refreshes after power-on lose more ticks, so
    at 13 offsets (65..72, 86..92 ms) the two images take the two in a different order. At
    those offsets the test requires the same number of audio states, the same final state
    and the DAC reconfiguration no later than fast-lcd's + 0.10 s (hn5's is up to 100 ms
    earlier). At every other offset the audio states match in order and time.
- **IR sweep:** 256 commands x 5 states, against fast-lcd, 63 s. Page-1 screens must equal
  `home_model` 0.5 s after the command. Four commands leave a home the stock sequence has
  not finished at that point: in standby 0x01 (power on, the logo, identical to fast-lcd) and
  on home 0x13, 0x14, 0x15 (direct-select BT, ARC, AUX: the input switch postpones the refresh
  by 2 s, and the old format tag stays on screen in both images until then). Those are
  checked again once the periodic refresh has run: home equals the model.
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
  name path or a clear, and no NEC command reaches them in the emulator. If they come during
  an exit, they draw over the half-revealed screen until the exit reaches them. The exit's
  reveal then redraws the same parts, and the flag they set only reaches `hn_flag_path`. No
  test presses them. Through the painter hooks they draw hn5's elements; `eq_show`'s preset
  name and description (big at y 75, small at y 135) are drawn in our fonts.
- **Source or direct-select during an exit differ from fast-lcd in their transient content,
  for up to about 2.9 s.**
  - hn4.1 shows the whole home with the new name at once.
  - fast-lcd, back home a moment earlier, may not have drawn its home yet, and the Source
    key pushes its next refresh back 2 s. Until then it shows only the name and the status
    line.
  - Pressed after fast-lcd's first refresh, fast-lcd shows the whole home too. Both images
    end on the same screen (tested 2.5 s later).
- **Input 7** (no name in `home_draw_input_name`'s table; apparently unused) draws a blank
  name after any volume page. The exit's start clears XDATA 0x35 as stock `ui_clear_screen`
  does at the return home, and stock then also renders the empty buffer.

## Risks

- **Panel timing: same as fast-lcd.** `uk_fill` and `uk_paint` use fast-lcd's byte timing (the
  WR pulse `features/blit-test` proved on the panel).
- **The main loop now runs during the wipes.** A step is at most 5.4 ms, after the tick's own
  work. The volume keys, format poll, unmute and re-mute run as on fast-lcd (tested
  against it, including the INT1 case the hn3 review raised).
- **Stock routines called from a step** (`home_draw_output_icon`, `home_draw_volume`,
  `home_draw_format_tag`, `home_draw_eq_tag`, `big_text_load`) run in the main loop, as
  they do from `home_refresh_periodic`. The stack peak is unchanged (0xAF with Timer0
  only, 0xB3 with Timer3; see Stack above).
- **Recovery: unchanged.** The reset vector, the standby key handler (0x59B2) and
  `read_key`'s Source-in-standby jump to the bootloader (0x3DB8) are untouched.

## What to look for on the amp

hn6: the volume, the tags and the status line larger than hn5's (36, 13 and 20 px against 22,
10 and 12), the speaker larger with them, the bar 6 px lower. Readable at arm's length?

hn5, the home screen:
- The home looks like the mock's House Numerals home: speaker and volume top left, the tags
  in thin accent boxes top right, the input name large in the condensed face, the status in
  grey mono under it, the short accent bar below.
- Mute (remote): the speaker turns red with an X. Headphone output: the headphones icon and
  the headphone volume.
- Change the input, the EQ and the format (play PCM, then DSD or MQA): the tags and texts
  follow without leftovers of longer texts, and nothing flickers at the 0.5 s refreshes.
- The EQ key on the home screen: the preset's name shows large, its description as the
  status line, then the home comes back.
- The first unmute after power-on may come a little earlier than before (0.1 to 0.2 s).

From hn4.1, the wipes:

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

- `layout.json` is the home layout; `sizing.html` edits it (see "Layout").
- `build_patch.py` builds `build/flash_house_numerals.bin` from
  `features/fast-lcd/build/flash_fastlcd.bin` and writes the listing
  `house_numerals.asm`. It uses the text instructions added to `tools/patch/asm51.py`
  (`Asm.op`, `#hi(label)` / `#lo(label)`).
- `emu_test.py` runs the unit tests, the whole-firmware scenarios, the INT1 sweep and the IR
  sweep above.
