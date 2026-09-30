# House Numerals

A reduced build of study 3 ("House Numerals", after SMSL's SU and DO series screens) from
`features/ui-theme/ui_themes.html`. Built on top of fast-lcd, with fix-auto-off and strings included. The RESET page shows
`v1.4 tbenr hn10.1`.

This is image hn10.1 (sha256 `89a6ed99…`). It is hn10 with one fix and one more fix linked in:
- **The status line's tint after an input change.** Seen on the amp with hn8: after Source from
  an input without a signal, the next input's status showed reddish too, until a refresh turned
  it grey. `input_apply` (0x5640) draws the new input's placeholder ("Digital input",
  "initializing", "Analog input") through 0x4BC9 at once, but the periodic refresh, whose status
  loader makes the signal check, comes 2 to 3 s after an input change. Until then the
  placeholder was drawn in the tint of the previous input's check. The tint now belongs to the
  loader's own text: only the refresh's draw after the loader keeps it, and every other status
  draw on the home (the placeholder, the BT key's "BT Reconnect", the EQ key's description) is
  grey. See "Colours" under "The home screen".
- **`features/strings` included.** The stock "No Connected" of HDMI ARC without a link is
  "Disconnected", patched in place in the stock string table (13 bytes at 0x91ED, no code).

hn10 (`v1.4 tbenr hn10`, sha256 `45c22bf1…`) is hn9 with the mock's easing on both wipes:
- **Cubic ease, 32 ticks each way.** The edge follows the mock's
  `ease = t < .5 ? 4t³ : 1 − (−2t + 2)³ / 2`: x = round(318 (1 − ease(k / 32))) on the way in,
  318 − x on the way out, one table for both (hn9: a cosine ease over 20 ticks). 32 ticks is the
  mock's 0.32 s entry; its exit takes 0.42 s, but one length both ways keeps the reversal (step
  k → 32 − k at the same x). The length is one constant, `STEPS` in `build_patch.py`; tables,
  code, tests derive from it. The generator is the kit's `ease_cubic_in_out`.
- **Steps that do not move.** The cubic barely moves at its ends: at 32 steps, 4 steps move the
  edge 0 px and 4 move it 1 px. A step whose x equals the previous x now draws and reveals
  nothing (it only counts); so the edge first appears with the first step that moves it (entry
  step 3, x 317; exit step 3, x 1), and no band is ever 0 columns wide. 1-px steps keep a whole
  2-px edge (the new edge first, then the one old column).
- Not in this build (as hn9): the mock's 0.42 s exit, the MUTE state of the volume page, a
  dB ↔ steps switch, sizing for the volume page, per-column reveal.

hn9 (`v1.4 tbenr hn9`, sha256 `b45331a8…`) is hn8 with the volume page's two animations from
the mock:
- **Number roll.** On the open page a volume step rolls the number: the old one slides out and
  fades, the new one slides in from the other side, 14 frames over 0.14 s (the mock's `this.k`,
  cubic ease, 20 px). The panel is write-only and `uk_text` streams its cells, so two
  translucent numbers cannot be mixed: each frame draws **one** number on black, the old one
  while the mock's ease is below 0.5 (frames 1 and 2), then the new one, at the mock's offset
  for it and in the mock's alpha as a grey, clipped to a box between "VOL" and the line. The
  box is `uk_text`'s new row clip (`uk_textc`, in the kit). See "The number roll".
- **Spring on the line.** The position line's fill follows the volume with the mock's spring
  (k 200, damping 28): it grows from 0 when the page opens, follows each step, and retracts
  while the edge wipes back home. One fixed-point tick per 10 ms, within 1.05 px of the mock's
  float integrator, never past the target, still on the exact split at the end. See "The spring
  on the line".
- **Tick driver.** `uk_tasks` now serves `main_tick_tasks`' re-mute request itself before it
  looks at the tick flag, so a tick that arrives meanwhile is no longer consumed without the
  step (in the emulator 3 of the 17 ticks after a volume key went by without one; see "Driver").
- Not in this build (as hn8): the MUTE state of the volume page, a dB ↔ steps switch, sizing
  for the volume page, the mock's wipe timings and per-column reveal.

hn8 (`v1.4 tbenr hn8`, sha256 `122a963c…`) is hn7 with the mock's volume page and two home
details:
- **The volume page in the mock's typefaces**, with the elements hn7 lacked: the input name at
  36 px and the status line under it (loaded as the periodic refresh loads it, since page 2
  never refreshes it), "VOL" letter-spaced in the accent, the volume right-aligned in 84-px
  numerals, the position line 288 px wide, the level in dB below step 60 ("−39.5 dB", from the
  stock NJW1194 code table) and "max 60". See "The volume page".
- **Home:** the tag boxes have corners of radius 2 as the mock strokes them, and the status
  line turns reddish when the input has no signal (the mock's `M(dim, '#ff5040', .5)`).
- Not in hn8: the mock's MUTE state on the volume page (the firmware never shows the
  page muted: the mute key goes home and the volume keys unmute first), a dB ↔ steps switch,
  the number roll, the spring on the line, sizing for the volume page.

hn7 (`v1.4 tbenr hn7`, sha256 `41ce9807…`) is hn6.1 with the sizes redone in `sizing.html`: icon 22 px, volume 33, tags 16 in 22-px boxes, name 54, status line 28,
bar at y 156. The name and the wider status line no longer share a step of the wipe back home.
Together they took 8.4 ms, over the 8 ms budget per 10 ms tick, so the status line now comes
one step after the name (the last step still draws whatever is left).

hn6.1 (`v1.4 tbenr hn6.1`, sha256 `8f0ab9b2…`) is hn6 with `features/fix-auto-off` linked in
(`INCLUDES`), so with Dimmer on Auto OFF the display also goes dark after a cold power-up
(5.1 s after the power-on routine in the emulator). Nothing else changed.

hn6 (`v1.4 tbenr hn6`, sha256 `7b74e950…`) is hn5 with the larger sizes picked on the amp's feedback,
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

hn10.1: emulator-verified (all tests pass, including "fix-auto-off in house-numerals" and
"strings in house-numerals"). Tried on the amp on 2026-09-30: works.

hn10: emulator-verified (all tests pass, including "fix-auto-off in house-numerals"). Tried on
the amp on 2026-09-30: looks good.

hn9: emulator-verified (all tests pass, including "fix-auto-off in house-numerals"). Tried on
the amp on 2026-09-30, before hn10: good.

hn8: emulator-verified (all tests pass, including "fix-auto-off in house-numerals"). Tried on
the amp on 2026-09-30: works. One thing seen: after a Source change
from an input whose status was reddish ("No Connected"), the next input's status shows reddish
too for a while, until a refresh turns it grey. Reproduced in the emulator and fixed in hn10.1.

hn7: emulator-verified (all tests pass, including "fix-auto-off in house-numerals"). Tried on
the amp on 2026-09-29: looks good, and with Dimmer on Auto OFF the display goes dark after a cold
power-up.

hn6.1: emulator-verified (all tests pass, including "fix-auto-off in house-numerals"), not
yet tried on the amp.

hn6: emulator-verified (all tests pass), not yet tried on the amp.

hn5: emulator-verified. Tried on the amp on 2026-09-29: looks great, and the
anti-aliased text works well on the panel, but the tags, the status line (sample rate) and the
volume are too small at the panel's size. A redesign of the sizes is next.

Tried on the amp on 2026-09-29: hn4.1 (`v1.4 tbenr hn4.1`, `5eddb6df…`) looks OK. Longer use
is still to come.

## What the build shows

| Element | Build |
|---|---|
| Home: icon | the mock's speaker at 22 px, 12,10, white; red with an X when muted (bit 0x22.1); headphones on the headphone output |
| Home: volume | Barlow Condensed 33 px, white, at x 46, baseline 31, no leading zero |
| Home: tags | IBM Plex Mono 16 px in the accent, in 1-px accent boxes 10 px wider than the text with corners of radius 2, rows 10..31: the EQ box 270..309, the format box ending at 263 |
| Home: input name | Big Shoulders Display 54 px, white, at x 16, baseline 101, 1 px letter spacing |
| Home: status line | IBM Plex Mono 28 px, grey #8a9096, at x 18, baseline 147, 1 px letter spacing; #c4706b (the grey mixed half with #ff5040) when the status loader's signal check found none on a digital input |
| Home: accent bar | 28 x 3 at 18,156 |
| (hn6) | speaker 23 px, volume 36, tags 13 in 21-px boxes, name 52 at baseline 104, status 20 at baseline 140, bar at y 150 |
| (hn5) | speaker 16 px, volume 22, tags 10 in 17-px boxes, status 12 at baseline 132, bar at y 144 |
| Volume page: name | Big Shoulders Display 36 px, white, at x 16, baseline 64, 1 px letter spacing (inputs 1..6) |
| Volume page: status line | IBM Plex Mono 16 px (the tag face), grey (reddish without a signal), at x 18, baseline 90; loaded by the stock status loader when the page is drawn |
| Volume page: divider | 1 x 92 at 150,24, colour 0x2104 (#222) |
| Volume page: label | "VOL" in the accent, Plex Mono 16 px letter-spaced 3, at x 164, baseline 38 |
| Volume page: number | Barlow Condensed 84 px, white, right-aligned to end at x 304, baseline 112; the rest of the box 156..304 x 42..119 black |
| Volume page: number roll | a step on the open page: 14 frames, one per tick, one number each in the box: the old one (frames 1, 2), then the new one, shifted and grey (see "The number roll") |
| Volume page: position line | 288 x 3 at 16,136: accent up to the spring's split, 0x18E3 (#1d1d1d) after it; at rest the split is 16 + round(4.8 · step) |
| Volume page: spring | the split follows the volume (k 200, c 28, 10 ms ticks, fixed point); from 0 when the page opens, towards 0 during the exit |
| Volume page: dB caption | Plex Mono 16 px, grey, at x 16, baseline 160: the level below step 60 from the NJW1194 code table, "−39.5 dB" (8 cells; "−∞ dB" at step 0) |
| Volume page: max | "max 60", Plex Mono 16 px, #4d5257, ending at x 304, baseline 160 |
| (hn7) | volume page: name in the stock small font at 16,30, divider 1 x 104 at 140,14, "VOL" small font at 158,14, stock big digits at 2x at 184,42, line 240 x 3 at 40,136 |
| Wipe in | 2-px accent edge from x 318 to 0 over 32 ticks (0.32 s), the mock's cubic ease-in-out; black behind it; each element appears once the edge has passed it |
| Wipe out | the same from x 0 to 318; the home elements appear once the edge has passed them |
| Accent | theme colour (RAM 0x48:0x49); SMSL orange 0xFC43 when the theme is White (0xFFFF) |

Still cut from the mockup: the dB ↔ steps switch (and the dB mode's other captions), the mock's
wipe timings (0.32 s in, 0.42 s out) and per-column reveal. The MUTE state of the volume page is
unreachable in this firmware (see above). The roll shows one number per frame where the mock
crossfades two (see "The number roll").

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
  EQ tags are all three letters, so the EQ box has one width (x 270..309); the format box ends
  at x 263 and is 40 or 50 px wide; the format tag's area is cleared up to the box. The tag
  arithmetic keeps x - 192 in 8 bits (the EQ box ends past x 255). The box's corners have
  radius 2 as the mock strokes them: its two edge columns are glyphs of a tiny font (`pf_box`,
  `pfont.box_edges`, drawn with `uk_text` in the accent) whose corners quantise a 1-px stroke of
  radius 2 to 1/4, 3/4, 3/4 and 1/4 ink; the top and bottom rows run between them.
- **Colours.** Name and volume white, status grey, tags and bar in the accent (the COLOR tint;
  SMSL orange on White), the muted icon red. The stock tinted all of it. Without a signal the
  status line is the grey mixed half with #ff5040 (`DIM_LOST`), as the mock's home: the status
  loader's `lcall signal_check` at 0x4016 is `hn_signal`, which keeps the check's result in
  XDATA `HN_SIG` next to the text it decides (RAM 0x22.5, which `signal_check` sets, is reused
  by `volume_apply` 0x58D3 for the mute state, so it cannot be read back at draw time). The
  analogue inputs (6, 8) show "Analog input" either way and stay grey.
  The tint belongs to the text the loader decided. The refresh's own draw (`hn_hold`'s stock
  path at 0x4081, after the loader) marks itself in bit 1 of `HN_SIG`, and the hand-over from
  `small_text_render` (`hm_status_r`) keeps the tint only for a marked draw. Every other page-1
  draw at y 135 has put its own text into XDATA 0x50 (`input_apply`'s placeholder through
  0x4BC9, the BT key's "BT Reconnect" at 0x10A1, `eq_show`'s description at 0x396A, 0x532E):
  it is grey, and `HN_SIG` becomes 1 until the loader runs again. The exit wipe, `hn_home_now`
  and the volume page draw the loader's text with its tint as before. Up to hn10 every draw
  used the last check's result, so after an input change from an input without a signal the
  placeholder stayed reddish for the 2 to 3 s until the refresh (seen on the amp with hn8).
- **Speed.** A whole home (home_refresh and the status line) takes 12.4 ms; the stock refresh
  took about 45 ms. The main loop now loses fewer ticks at the refreshes after power-on, so
  the first unmute comes 0.12 to 0.18 s earlier than on fast-lcd (see "Per input").
- **Fonts** (15271 bytes, all 4-level anti-aliased run-length): the home name face disp54 2954
  (A-Z, space, `.`, `-`), the status mono28 4738 (the 59 characters of every firmware string),
  the tag mono16 3122 (the same set plus `x`, and the caption's minus sign and infinity as `_`
  and `~`: it is also the volume page's small face), the home volume num33 906, the three
  icons 403, the box edges 44; the volume page's name disp36 943 (the letters of the six input
  names) and its numerals num84 2161.

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

The `lcall 0x3325` at 0x5B2A becomes `lcall uk_tasks`.
- First it serves the re-mute request as 0x3325..0x332E do (0x21.4 set: clear it and 0x22.4,
  `lcall volume_apply` 0x58D3), then it looks at the tick flag.
- No tick: it returns (0x3325 would find no request and no tick, and return at 0x345B).
- Tick: it calls 0x3325, then, if RAM 0x4F is 1 (amp on), runs `hn_step`, which ends in
  `hn_after`: `hn_spring`, then `hn_roll`.

Up to hn8 the no-tick path tail-jumped to 0x3325. A tick that the Timer0 ISR flagged between
`uk_tasks`' test and 0x3325's own (at 0x332F) was then handled by the stock without a step. In
the emulator that happened on 3 of the 17 ticks after a volume key on the open page; the wipes
lost steps the same way (the tests counted steps, not ticks). Now such a tick is seen on the
next pass of the main loop, and the frames of a roll come on consecutive ticks (tested). The
stock bytes of 0x3325..0x3331 and the `ret` at 0x345B are asserted by the build, and a unit test
compares `uk_tasks` with `main_tick_tasks` for every combination of request and tick.

Order within a tick, all after the tick's stock work:
1. the wipe step (`hn_step`), as in hn8;
2. the line's spring (`hn_spring`): during a wipe it redraws only columns right of the edge the
   step has just drawn, and the step's own draw of the line inside the band uses the split on
   screen (`HN_SPL`), so right of the edge the line always reads: accent up to the spring's
   split, track after it;
3. the number roll (`hn_roll`): only on the idle page, so never in the same tick as a wipe step.

The step comes after all of that tick's stock work. A page render in the same tick (for
example the Timer0 return home) has already started the wipe, and the unmute and format
poll are never delayed by a step. Hooking this call was chosen over:
- the flag test at 0x332F, which would put the step before the tick's duties;
- the main loop's `lcall 0x5B22` at 0x5422, where `post_power_on` and the power-off path
  share the call.

A step never waits. The main loop keeps its timing, and a lost tick only delays the wipe
by one tick.

### A step (`hn_step`)

State lives in XDATA: mode (0 idle, 1 in, 2 out), step 0..STEPS (32), edge x. `ease` holds 33
edge positions for the way in, `round(318 (1 − ease(k / 32)))` with the mock's cubic ease:
318 318 318 317 316 313 310 305 298 290 279 266 251 233 211 187 159 131 107 85 67 52 39 28 20 13
8 5 2 1 0 0 0 (moves of 0, 0, 1, 1, 3, 3, 5, 7, 8, 11, 13, 15, 18, 22, 24, 28, 28, 24, … px). The
way out uses 318 − x. The table is symmetric (asserted), so turning a wipe round maps step k to
32 − k at the same x.

Each step:
1. Takes the next x. If it is the previous x (and this is not the last step), the step ends
   here: nothing drawn, nothing revealed, the flags unchanged. The first steps of either wipe
   therefore draw nothing; the edge appears with the first step that moves it.
2. Draws the 2-px accent edge at [x, x+1] (outside the band), except on the last step, where
   the band runs to the screen edge.
3. Fills the band the edge swept since the last step with black (the new page's background).
   The old edge's two columns go last: on the way in they are the band's top end, and
   `uk_fill` goes up in x; on the way out they are its bottom end, so the rest of the band is
   filled first.
4. Marks as "not on screen" every element of either page that the band or the edge
   columns touched.
5. On the way in, redraws the part of the position line inside the band, at the split on
   screen (the spring's, `HN_SPL`).
6. Draws every element of the new page that is not on screen and that the edge has fully
   passed:
   - on the way in, when its left edge is right of the edge (x0 >= x + 2);
   - on the way out, when its right edge is left of it (x1 < x);
   - on the last step, everything.

The wipe ends after its last step (32).

A band is the columns the edge left: on the way in x + 2 .. previous x + 1, on the way out
previous x .. x − 1, so as wide as the move (1 to 28 columns); moves of 0 end the step before
it, and the last step's band (to the screen edge) is at least 2 wide. So `uk_fill` never gets
a 0-wide band. On a 1-px move the new edge covers one of the old edge's columns and the band is
the other one, filled after the new edge is drawn.

GRAM therefore always holds a whole edge between the first step that moves the edge and the
last step: the new one is there before the old one goes. The panel reads one row (firmware x) per line time, 48 µs,
and a band column takes 64 µs to fill. So whichever way the scan runs, a frame that misses
the new edge still reads the old one before its columns are erased.

The `tour` group runs `panel_video.py`'s scan model over an entry and an exit, both scan
directions, at four frame phases. Every frame between the end of the first step that moves the
edge and the start of the last step has a whole 2-px edge (hn4 failed this in 11 of the 16
cases).

| Way in: element | Columns | Appears at step (edge x) |
|---|---|---|
| (the edge) | | 3 (317): steps 1, 2 do not move it |
| "max 60" | 245..304 | 13 (233) |
| "VOL" | 164..202 | 16 (159) |
| number, divider | 156..304, 150 | 17 (131) |
| position line | 16..303 | drawn in parts inside each band; in full at 25 (13) |
| name, dB caption | 16..125, 16..96 | 25 (13) |
| status line | 18..147 | 26 (8): the step after the name's |

| Way out: element | Drawn by | Appears (OPTICAL, "No signal") |
|---|---|---|
| (the edge) | | 3 (1): steps 1, 2 do not move it |
| icon 12..45, accent bar 18..45 | `home_draw_output_icon` 0x5744 (`hm_icon`), `uk_fill` | 11 (52) |
| volume 47..82 | `home_draw_volume` 0x5916 (`hm_volume`) | 13 (85) |
| status line 18..end of the text | `hm_status`, buffer XDATA 0x50 | 18 (211): once the stock refresh has loaded the buffer (before step 11), and the edge has passed its end, not in the name's step; USB 17 (187), BT 20 (251) |
| input name 16..end of the text | `hm_name`, buffer XDATA 0x35 | 17 (187); USB 14 (107), BT 12 (67) |
| format tag 228..269 | `home_draw_format_tag` 0x41CA (`hm_fmt`) | 21 (266) |
| EQ tag 276..309 | `home_draw_eq_tag` 0x49A1 (`hm_eq`) | 26 (310) |

The status line waits for its buffer:
- The stock refresh loads XDATA 0x50 10 ticks after the return home (0x27:0x28 = 10 after
  the render). `hn_hold` notes when it has run (`HN_SBUF`).
- The status line is drawn on the first step after that on which the edge has passed its
  end. On the last step it is drawn in any case. With 32 steps the buffer is always there
  before the edge reaches the status line's end (step 11 against 17 at the earliest).
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
- During a wipe, `hn_draw_volume` only records the value (`HN_VOL`, `HN_NUM`, `HV_DB`). It
  draws the number (in its final state, no roll) and the dB caption only if the wipe has already
  revealed them. The line is the spring's: it follows `HN_VOL` by itself.
- The wipe draws them with the latest value when it reaches them.
- Without a wipe, on the page: the caption at once, and the number rolls from the next tick
  (see "The number roll"). Without a wipe and the page not on screen: the number, the line (the
  spring snapped to its target) and the caption at once (`hn_dyn_now`, as hn8 drew them).
- The page-2 renderer (0x2143, `hn_volpage`) does the same during a wipe, and draws the whole
  page when idle, the number and the line in their final state.

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

The stock refresh therefore draws nothing during the exit. Its next run (50 ticks after the
first, so 28 ticks = 0.29 s after the 32-tick exit ends; hn9: 0.41 s after a 20-tick exit), draws exactly the same pixels over the revealed screen (tested). The end state
is the hn3 home screen.

### Interruptions and how a wipe is cancelled

- **Any stock clear cancels.** The first instruction of `ui_clear_screen` (0x5D42, 16
  callers: menu, Source, standby, the other pages, `post_power_on`, "go home" on page 2)
  becomes `ljmp hn_cancel`. `hn_cancel` (through `hn_stop`) sets mode, the volume-page flags and
  the home flags to 0, stops a roll and puts the spring at home (0, still, split 16), then runs
  the stock clear (`lcall 0x5CBC ; ljmp 0x5D45`). `hn_clear` for any other page, and for page 1
  while an exit already runs, goes the same way.
- **The exit's start during a roll** (the return home comes 2 s after the last key, the roll
  takes 0.14 s, so only in theory): `hn_clear` draws the roll's last frame first (`hv_num`),
  then starts the exit.
- **Volume key during the entry:** the value is recorded and drawn when revealed (or at once
  if its box already is).
- **Volume key during the exit:** the key handler sets page 2. `hn_enter_vol` turns the wipe
  round at its x (step STEPS − k), and the edge heads left again. Volume-page elements the
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

## The volume page

The mock's volume page, with the small texts in the tag size (16 px) and the name at 36 px,
sizes chosen by eye against hn7's home (not yet in `sizing.html`; the positions are constants
in `build_patch.py`, `V*`). Everything is drawn with `uk_text`; the kit's stock-font painter
`uk_paint` is no longer linked into the image.

| Element | Routine | Columns |
|---|---|---|
| input name | `hv_name`: the name for inputs 1..6 (`hn_name_ptr`), disp36 | 16..125 (the widest, COAXIAL) |
| status line | `hv_status`: `hn_stat_load`, then XDATA 0x50 in mono16, grey or reddish (`hn_dim_ink`), black up to x 147 after it | 18..147 ("Digital input") |
| divider | `hv_div` | 150 |
| "VOL" | `hv_vol`, letter-spaced 3, accent | 164..202 |
| number | `hv_num`, num84, right-aligned | 156..304 |
| position line | `hv_line` → `hn_line_seg` twice (halves of 144 px: `uk_fill` takes widths up to 255) | 16..303 |
| dB caption | `hv_cap` | 16..96 |
| "max 60" | `hv_capr`, #4d5257, right-aligned | 245..304 |

- **Status line.** The stock only loads XDATA 0x50 in the page-1 periodic refresh, and the entry
  clears the buffers, so the page loads it itself: `hn_stat_load` sets `HN_SLD` and jumps into
  the stock loader at 0x4016 (signal check, then the input's string or its sample rate). That
  code runs on into the `lcall home_refresh` at 0x4081, which is `hn_hold`: with `HN_SLD` set
  it clears the flag and returns to `hn_stat_load`'s caller instead. The text is exactly what
  the home shows (tested against the base image's loader, with strings' texts, for every input, with and
  without a signal). The page shows the status as of when it was drawn; the stock shows nothing there.
- **Number.** `hv_num` is `hn_num_at` with the new text, no offset, in white: it draws the
  number right-aligned to end at x 304 (`uk_textc`, which leaves the number's first column in
  `TP_X`), clipped to the roll box 156..304 x 42..119, then fills black the rest of the box:
  columns 156 up to the number over all its rows, and the rows above and below the cell over the
  number's columns. A step from 10 to 9 therefore clears the tens digit's columns without
  blanking the number; the digits themselves redraw in place (each cell carries its background),
  so nothing flickers.
- **dB caption.** The NJW1194 code table at 0x9289 (`code = table[60 - step]`, see the main
  README, "Volume scale") gives the level below step 60 in half-dB: `code - 35`. `hv_cap`
  formats it as `_75.5 dB` .. ` _0.5 dB`, `  0.0 dB` (no sign at step 60), always 8 cells so
  a shorter value draws its own background; `_` and `~` are the minus sign and the infinity of
  the mono raster (`MONO_ALIAS`), and step 0 shows `  _~ dB ` from code. This is the mock's
  `fmtDb`; the test computes it from the mock's copy of the table.
- **Redraws.** On the open page `hn_draw_volume` (0x5936, every knob or remote step) draws the
  dB caption, arms the roll and moves the spring's target; the number and the line follow over
  the next ticks. With the page not on screen it draws the number, the line and the caption at
  once: 6.4 ms (the stock's 2-digit draw: about 40). `hn_volpage` draws the whole page in 11.5 ms
  (hn8: 10.5; `hv_num` now also blacks the rows of the box around the number).
- **Entry order.** Right to left: "max 60" appears at step 13, "VOL" at 16, the divider and the
  number at 17, the name, the line and the caption at 25, the status line at 26: if the name
  was drawn in a step, the status line (with its load, an I2C read on BT and HDMI) waits for
  the next one, as the exit does for the home's name and status line; the last step draws
  whatever is left. An exit turned back into an entry loads and draws the status line again (the exit
  had cleared its buffer; `hn_reverse` marks it not drawn), black up to x 147 after the text.

### The number roll

The mock (`update`, `drawVol`): on a new label, `prev = cur`, `k = 0`, and for 0.14 s
(`k += dt / 0.14`) with `e = 1 - (1 - k)^3` and `shift = 20 * dir` (dir 1 when the volume went
up), it draws in the clip rectangle 146, 38, 164 x 82: the old label at alpha `1 - e`, baseline
`112 - shift * e`, and the new one at alpha `e`, baseline `112 + shift * (1 - e)`.

The panel is write-only and `uk_text` streams its cells with their background, so two
translucent numbers cannot be mixed. The reduction: 14 frames, one per executed 10 ms tick,
frame n at `k = n / 14`; each frame draws **one** number on black: the old one while `e < 0.5`,
the new one from then on, at the mock's offset for it rounded to rows, with its alpha as the ink
(white × alpha as an RGB565 grey; the 1/4 and 3/4 anti-aliasing colours follow from ink and
background as `uk_text` computes them). A step down is the mirror image (the offsets negated).
The table is generated by `build_patch.py` from the formula (`roll_frames`, `ro_tab`):

| Frame | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12..14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Number | old | old | new | new | new | new | new | new | new | new | new | new |
| Rows (a step up) | −4 | −7 | +10 | +7 | +5 | +4 | +3 | +2 | +1 | 0 | 0 | 0 |
| Ink | CE59 | A514 | 8410 | A514 | BDD7 | CE79 | DEFB | EF5D | F79E | F7DE | FFDF | FFFF |

Frame 14 is `hv_num` itself, so the page ends pixel-identical to the static page (frames 12 and
13 draw the same; the table keeps the mock's 14 steps). The old number shows for two frames only:
the mock's cubic ease is past 0.5 by frame 3.

- **Clip box.** Columns 156..304 (`VNUM_LEFT`..`VNUM_RIGHT`), rows 42..119: the mock's 38..119,
  cut below "VOL"'s cell (rows 25..41, whose columns overlap the number's) and above the line
  (136). The build asserts that the box holds the number at rest (rows 51..112) and touches no
  other element. Every frame draws the number clipped to the box (`uk_textc`, the kit's row
  clip, and the box's columns as the x clip), then blacks the rest of the box, so after each
  frame the box is exactly that one number, shifted, clipped, dimmed, on black, whatever the
  previous frame left (a wider number, the other direction), and nothing outside it changes.
- **When.** A volume change with no wipe running (`HN_MODE` 0), the page on screen (`HN_VF`
  all) and the text changed: `hn_draw_volume` keeps the text shown so far in `HR_OLD`, sets
  `HR_DIR` (1 when the volume went down) and `HR_F` 1, and draws the dB caption at once; the
  frames come from the tick driver (`hn_roll`). A change during a roll restarts it with the
  previous target's text as the old one (the mock's `prev = cur`).
- **Not during a wipe.** A key during the entry or the turned-round exit draws the number in its
  final state when it is revealed (or at once if it is), as in hn8. `hn_volpage` idle and
  `hn_dyn_now` draw it at once; so does `hn_clear` at the exit's start if a roll runs.
- **Stops.** `hv_num` ends a roll (`HR_F` 0). Every stock clear (`hn_cancel`) stops it;
  `hn_roll` also stops, drawing nothing, when the mode is not 0, the page not on screen or
  `HR_F` is not a frame (XDATA after a cold start).
- **Cost.** 6.1 ms for the worst frame in the unit test (a 2-digit number shifted, its left
  columns and the uncovered rows blacked), 5.8 ms in the whole firmware including the spring.

### The spring on the line

The mock: `spring(this.s, show ? vol / 60 : 0, dt, 200, 28)`, integrated at 240 Hz (3 substeps
of 1/300 s per 10 ms frame), fill `round(288 * s.x)`.

- **State** in XDATA: position `SP_P` and velocity `SP_V` in pixels × 64 (signed 16 bits),
  velocity per tick. With the target fixed the integrator is linear, so one tick of it (the 3
  substeps) is a 2 x 2 matrix on (position − target, velocity); `build_patch.py` composes it
  from k, c and dt and keeps it as four Q16 fractions (`sp_kt`: 819, 53878, 1188, 48474):
  `e' = e − e·K1 + V·K2`, `V' = V·K4 − e·K3`, each product rounded half away from 0
  (`hn_sp_mulx`, a 16 x 16 multiply). A tick with |e'| < 0.5 px and |V'| < 6/64 px per tick
  settles on the target and stops.
- **Target** (`hn_sp_t6`): `4v + (4v + 2) / 5 = round(4.8 v)` pixels for volume v on the idle
  page and during the entry, 0 during the exit (the mock's `c.show`). A volume key only changes
  `HN_VOL`; an exit turned round by a volume key gets the volume as target again and goes on
  from where position and velocity are.
- **Home** (exit ended, `hn_cancel`, `hn_home_now`, and a fresh entry from home): position 0,
  velocity 0, split 16 (`hn_sp_reset`), so the fill grows from 0 as the page opens.
  `hn_volpage` idle and `hn_dyn_now` put it on its target, still (`hn_sp_snap`).
- **Drawing.** The split on screen is `HN_SPL` = 16 + round(position / 64), clamped to the line
  (`hn_sp_split`). Each tick only the columns between the old and the new split are drawn,
  through `hn_line_seg` (accent when growing, track when shrinking): everything on the idle
  page, during either wipe only right of the edge (x + 2 on); the wipe's own draw of the band
  and `hv_line` use `HN_SPL` too.
- **Accuracy** (Python model of the 8051 arithmetic, `spring_model` in the test, against the
  mock's float integrator, every volume pair 0..60 -> 0..60 and 1287 target changes in flight):
  at most 1.05 px off the mock at any tick, never past the target, ends exactly on the split of
  the volume, and still after at most 63 ticks (0 -> 60). The 8051 code equals the model tick
  by tick (0 -> 60, 60 -> 0, ±1 steps, target changes mid-flight, entry and exit).
- **Cost.** At most 0.07 ms a tick (the fill of a few columns of 3 rows).

## Timing

Worst tick measured (hn10): **7.09 ms**, on the entry's step 17 (the divider and the number,
with the cubic's widest band, 28 px, plus the spring's columns). The budget is 8 ms, inside the
10 ms tick, so no reveal had to be split further. A tick is timed from `hn_step`'s entry to
`uk_tasks`' return: the wipe step, the spring and the roll. Unit test:

| Tick | Worst |
|---|---|
| Entry step (+ spring) | 7.09 ms (step 17: divider, number; hn9: 6.90 on step 11; hn8: 5.96) |
| Exit step (+ spring), OPTICAL, "No signal" | 5.87 ms (hn9: 5.68) |
| Exit step, USB, "2.8224MHz" | 4.86 ms |
| Exit step, BT, "Searching..." | 5.06 ms |
| Roll frame (alone; the spring adds at most 0.07) | 6.13 ms |
| Spring tick | 0.07 ms |

In the whole firmware, including the `timer3_isr` calls that land inside a tick (about 5 µs
every 0.5 ms): wipes 6.74 ms at worst (tour 6.73, with a 1-digit number; hn9: 6.54), roll
frames with the spring 5.45 ms for single steps and 5.76 ms at knob speed (the page at 9..15).

The wipe's length is one constant (`STEPS`). Measured on throwaway builds with the same cubic
(unit test, worst step with the spring): 20 steps: entry 8.07 ms (step 11, the number, over the
8 ms budget: that length would need the number's reveal split), exit 6.83 ms; 26 steps: entry
7.48 ms, exit 6.26 ms; 32 steps (hn10): 7.09 / 5.87 ms.
For comparison, a whole hn8 home takes 13.9 ms, the whole volume page 11.5 ms, and the stock
periodic home refresh blocks the main loop for about 45 ms every 0.5 s.

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
| USB, 7.4 s after power-on | both wipe | 0.08 s earlier |
| HDMI, 0.5 s after the switch | both wipe | 0.06 s earlier |
| USB, 0.05 s after switching from HDMI | both wipe | 0.05 s earlier |
| USB, unmute due within the wipe | both wipe | 0.14 s earlier |
| Vol+ during the power-on logo | wipe starts, `post_power_on` cancels it | 0.18 s earlier |

Earlier, because fast-lcd's own 40 ms volume draw loses ticks and the wipe does not, and the
faster home refreshes after power-on (see above). Measured on hn9, and on hn8 rebuilt from its
commit: the same values (the table showed 0.02 to 0.03 s, from before hn5).

## Hooks

Twenty-three hook sites: eighteen 3-byte hooks of the theme, fix-auto-off's, plus the four
places the volume keys open the volume page (hn9 adds none). Every stock byte is asserted by
`build_patch.py`, and so are the bytes `uk_tasks` relies on: `main_tick_tasks`' re-mute part
0x3325..0x3331 and its `ret` at 0x345B.

| Address | Stock bytes | Now | What |
|---|---|---|---|
| 0x2106 | `12 5D 42` lcall `ui_clear_screen` | lcall `hn_clear` | `ui_render_page`'s clear: page 2 starts the entry, page 1 with the volume page on screen starts the exit; otherwise cancel + stock clear |
| 0x2143 | `02 21 67` ljmp `volpage_render` | ljmp `hn_volpage` | page-2 jump-table entry |
| 0x5936 | `AB 07 E5` | ljmp `hn_draw_volume` | number, line and dB caption; only recorded during a wipe |
| 0x2A25 | `E4 78 02` | ljmp `hn_align_big` | page 1: at y 75 `hm_name` draws and returns; other texts start at x 16 |
| 0x3A82 | `E4 78 02` | ljmp `hn_align_small` | page 1: at y 135 `hm_status` draws and returns; other texts start at x 16 |
| 0x5C99 | `02 59 16` | ljmp `hn_home_tail` | `home_refresh`'s tail: the volume, then the accent bar |
| 0x5744 | `30 11 0B` (`home_draw_output_icon`) | ljmp `hm_icon` | the icon |
| 0x5916 | `AB 07 E5` (`home_draw_volume`) | ljmp `hm_volume` | the home volume |
| 0x4F18 | `7D 0A 7C` (`eq_tag_paint`) | ljmp `hm_eq` | the EQ tag |
| 0x425D | `12 4F 20` lcall `small_text_at` | lcall `hm_fmt` | the format tag |
| 0x41E8 | `02 00 26` ljmp `tag_box_clear` | ljmp `hm_fmt_clear` | no format (BT, ARC, AUX, PHONO): the tag's area black |
| 0x41FC | `12 00 26` lcall `tag_box_clear` | lcall `hm_fmt_clear` | the format changed: the same |
| 0x5B2A | `12 33 25` lcall `main_tick_tasks` | lcall `uk_tasks` | the driver: the re-mute request, then after each tick a wipe step, the spring, the roll |
| 0x4081 | `12 5C 8B` lcall `home_refresh` | ljmp `hn_hold` | periodic refresh held back during a wipe; returns to `hn_stat_load` when the volume page runs the status loader |
| 0x4016 | `12 52 32` lcall `signal_check` | lcall `hn_signal` | the status loader's signal check: its result kept in `HN_SIG` for the status colour |
| 0x5D42 | `12 5C BC` (`ui_clear_screen`'s first call) | ljmp `hn_cancel` | every stock clear cancels a wipe |
| 0x4A85 | `E5 47 14` (`home_draw_input_name`) | ljmp `hn_name_guard` | a name drawn during an exit: the whole home first, then the name |
| 0x3FF8 | `C2 0B C2` (`clr 0x21.3; clr 0x20.6`) | ljmp `hn_flag_path` | the refresh's flag path during a wipe: flags and page as stock, the 0x412F fill skipped |
| 0x55B9 | `02 5D 42` ljmp `ui_clear_screen` | ljmp `fx_auto_off` | fix-auto-off (`INCLUDES`) |
| 0x91ED | `"No Connected\0"` | `"Disconnected\0"` | strings (`INCLUDES`): an in-place patch, not a hook |
| 0x0D33, 0x0DB3, 0x0E5A, 0x0F02 | `12 5D 42 7B FF …` | `12 DE 54 80 11` (lcall `hn_enter_vol` ; sjmp site+0x16) | volume-key entry sites A-D |

## Memory

- **Code:** 22349 bytes at 0x9800..0xEF4C (15271 of them fonts, fix-auto-off's 14 at the
  end), plus the version string at 0xEF4D. Image length 61279 bytes; 1185 bytes are left under
  the 0xF400 split (hn10: 1199, hn9: 1231, hn8: 2220). hn10.1 added 12 bytes of code (the mark in
  `hn_hold`, `hm_status_r`, less `hn_home_now`'s own status draw) and 2 of version string.
  hn10 added 32 bytes: the ease table's 12 more words
  and the still-step test in `hn_step`. hn9 added 989 bytes: the kit's row clip (`uk_textc`, the
  row-clipped decoder `tx_yclip`, format 2 only here: about 190), the roll (about 250 with its
  39-byte frame table), the spring (about 480 with its multiply and constants), less hn8's
  61-byte split table (`vsplit`, now computed). `house_numerals.asm` is the generated listing.
- **XDATA** 0x0100..0x01C1. The EEPROM sectors and everything fast-lcd/direct-select use
  stay untouched. hn9 added 0x01B3..0x01C1, and `uk_text`'s block grew by 5 bytes (the row clip)
  and now starts at 0x015B, in what was free below it.

| Address | Name | Holds |
|---|---|---|
| 0x0100, 0x0102 | `HN_N`, `HN_C` | `uk_fill`'s pixel count and colour |
| 0x0104 | `HN_VOL` | the volume shown (0..60) |
| 0x0105..0x0107 | `HN_NUM` | its decimal text (no leading zero) and a NUL |
| 0x0108 | `HN_MODE` | 0 idle, 1 wipe in, 2 wipe out |
| 0x0109 | `HN_VF` | volume-page elements on screen (name, status, divider, VOL, number, line, dB, max) |
| 0x010A | `HN_HF` | home elements drawn by the exit (icon, volume, bar, name, format, EQ, status) |
| 0x010B | `HN_STEP` | step 0..20 |
| 0x010C | `HN_SBUF` | the stock refresh has loaded the status buffer during this exit |
| 0x010D, 0x010F | `HN_X`, `HN_XP` | edge x, previous x |
| 0x0111 | `HN_LIM` | this step's reveal limit |
| 0x0113, 0x0115 | `HN_D0`, `HN_D1` | damaged columns (band and edge) |
| 0x0117, 0x0119 | `HN_B0`, `HN_B1` | the band |
| 0x011B, 0x0123 | `HN_NAMER`, `HN_STATR` | right end of the home name / status line |
| 0x011D, 0x011F | `HN_S0`, `HN_S1` | `hn_line_seg`: columns |
| 0x0121 | `HN_SPL` | the line's split column on screen (the spring's, 16..304) |
| 0x0130..0x0155 | | free (hn7's `uk_paint` block; the kit still reserves it) |
| 0x015B..0x0191 | `TP_*` | `uk_text`'s parameters and work area; `TP_YC0`, `TP_YC1` the row clip, `TP_YA`, `TP_YN`, `TP_YZ` the cell's rows above, in and below it |
| 0x0192 | `HM_VS` | the home volume as text |
| 0x0196 | `HM_TAG` | a tag's text, trailing spaces cut |
| 0x019C..0x019E | `HM_TX`, `HM_TW`, `HM_TWD` | `hm_tag`: box x (- 192), box width, text width |
| 0x019F..0x01A4 | `HM_RL`, `HM_RY`, `HM_RH`, `HM_RX` | `hm_rest`: last column, rows, next column |
| 0x01A5, 0x01A6 | `HM_TR`, `HM_TL` | `hm_tag`: where the box ends, where the tag's area starts (- 192) |
| 0x01A7 | `HN_HF0` | a step's `HN_HF` / `HN_VF` at its start (the name and the status line don't share a step) |
| 0x01A8 | `HN_SLD` | `hn_stat_load` is running the status loader: `hn_hold` returns |
| 0x01A9..0x01B1 | `HV_DB` | the dB caption, 8 characters and a NUL |
| 0x01B2 | `HN_SIG` | the status loader's signal check: 1 = signal (`hn_signal`), or 1 after a status draw that was not the loader's; bit 1: the next page-1 status draw is the loader's (`hn_hold`, cleared by `hm_status_r`) |
| 0x01B3, 0x01B5 | `SP_P`, `SP_V` | the spring: position (pixels × 64) and velocity (pixels × 64 per tick), signed |
| 0x01B7, 0x01B9, 0x01BB | `SP_T`, `SP_E`, `SP_W` | a spring tick's target × 64, error, first product |
| 0x01BD | `HR_F` | the roll's next frame 1..14, 0 idle |
| 0x01BE | `HR_DIR` | the roll's direction: 0 up, 1 down |
| 0x01BF..0x01C1 | `HR_OLD` | the roll's old text (the previous target's) and a NUL |

- **Stack:** the tour (with two entries and two exits) was run with a canary above SP. The
  deepest idata used is 0xB3, the same as fast-lcd. That is stock's own peak: the delay
  leaves (0x0006, 0x0016) at SP 0xA0 with `timer3_isr` on top. Before `Amp` ran Timer3 the
  tour measured 0xAF (Timer0 ISR on top).

## Emulator results

`python3 tools/run_tests.py` gives **ALL PASS** for every feature (hn9: 137 s wall,
house-numerals 137 s, most of it the sweep). `emu_test.py` has four groups: `unit`, `tour`,
`int1`, `sweep`; `unit tour` alone runs in about a minute.

- **Status tint** (hn10.1). Unit: the refresh's draw keeps the loader's tint (three no-signal texts
  reddish, a sample rate grey); four draws at y 135 that are not the loader's, after a no-signal
  check, are grey and stay grey when redrawn. Whole firmware, six cases (Source, direct-select BT
  and AUX from USB without a signal, with and without an optical lock; Source and the BT key from
  Bluetooth searching): the status before the key is reddish, the text 0.3 s after the key is grey,
  and once the loader has run it is reddish exactly when the new input has no signal. Against
  hn10 five of the six 0.3 s checks fail (reddish), as seen on the amp; AUX is grey either way.
- **Image diff:** only the fifteen hook sites and strings' patch at 0x91ED (plus the version
  pointer) differ from fast-lcd inside the base image. The labels in `SmslAo300Labels.java` match this build.
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
- **`hn_draw_volume`:** every value 0..60 in three themes (page not on screen: all at once).
  During a wipe it records and draws only the revealed number and caption, never a roll.
- **Number roll, unit** (`test_roll`, against `roll_frame` / `roll_box`, written from the mock's
  formula independently of the build's table, and the table checked equal to it): 25↔26, 9↔10,
  60↔59, 0↔1, 5↔47, both ways. The key draws only the caption and arms the roll; each of the
  14 frames leaves the box exactly `roll_box` (one number, shifted, clipped, dimmed, on black)
  and nothing outside it changed; frame 14 = the static page; then idle. A key during a roll
  restarts it from the previous target (26 during 25 -> 26; 10 -> 9 turned back at frame 2);
  the same value again: no roll. Stopped at frame 4 by `ui_clear_screen`, by `hn_volpage` (the
  final number at once) and by the exit's start (the final number first). No roll during a
  wipe; a bogus `HR_F`, mode or page flag stops it without drawing. Worst frame 6.13 ms.
- **Spring** (`test_spring`): `spring_model` (the 8051 arithmetic in Python) against the mock's
  float integrator for all 61 x 61 volume pairs and 1287 target changes in flight: within
  1.05 px at every tick, at most 0 px past the target, exact end, at most 63 ticks. Then the
  8051: `hn_sp_t6` for every volume, `hn_sp_mulx` on 2163 products, `hn_sp_split` on 407
  positions, and `hn_spring` tick by tick against the model with the line on screen checked at
  each tick (0 -> 60, 60 -> 0, ±1 steps, changes mid-flight); during a wipe it draws only right
  of the edge; `ui_clear_screen` and an entry from home put it at 0; at rest it draws nothing.
- **`hn_step`, unit:** starting from a pattern screen, each of the 20 entry steps checks:
  - x from the table;
  - the old page left of the edge, then the accent edge;
  - the volume page right of it with only the passed elements, and the line right of the edge
    at `spring_model`'s split (the spring grows from 0 during the entry);
  - the element flags, and the spring's state against the model.

  The same for the exit on three inputs, including the status-buffer rule, with the line right
  of the edge retracting as the model says. The entry ends as the page with the line at the
  spring's split; the spring then settles tick by tick as the model (23 more ticks) and the page
  is pixel-identical to `hn_volpage`. The exit ends pixel-identical to the stock home refresh,
  the spring at home. Steps that do not move the edge draw nothing (before the first move the
  screen is untouched). Reversals after every step 1..31 each way (the still and 1-px steps at
  both ends included) end on the right page; the exit reversal redraws with the new volume.
- **Logic:** `hn_enter_vol` and `hn_clear` in every mode; `hn_cancel` from both modes;
  `hn_hold` in each mode; `hn_name_guard`; `uk_tasks` (a step only after a tick, only with
  0x4F = 1; the re-mute request and the tick as `main_tick_tasks` runs them, for all four
  combinations against the base image; a tick set during the request's `volume_apply` gets its
  step); a bogus mode stops.
- **Tour** (whole firmware, lockstep with fast-lcd, real Timer0 ISR):
  - each step lands on the same page, power, volumes, input and output;
  - home screens equal to `home_model`; volume pages exactly as `hn_volpage`; menus and
    standby identical to fast-lcd;
  - both entries and both exits take 32 steps with the table's x, and the screen at entry
    step 10 is checked (the line right of the edge at the split on screen);
  - after a key from home the page is checked 0.8 s later (hn8: 0.5), once the spring rests;
  - the volume write comes before the first step;
  - the home refresh is held during the exit and resumes 0.29 s after it (hn9: 0.41), drawing
    the same pixels;
  - home (page 1) comes back at the same moment as fast-lcd (within 0.05 s); the home screen
    is whole when the exit ends, 0.32 s after that (checked; hn9: 0.20 s; fast-lcd draws its
    home at its first refresh, 0.10 s after the switch, in about 45 ms);
  - audio states in the same order, none more than 0.10 s later; same argument sets for every
    audio writer.
- **Per input:** the eight scenarios above, each checking entry, exit, screens, the unmute
  and the audio.
- **Keys during a wipe:** 16 scenarios, each with the final screens and audio checked
  against fast-lcd:
  - Vol+ during the entry, and in its still tail (step 30, x 0);
  - Vol+ and Vol- during the exit (turned round; Vol- at step 4, x 2, in the 1-px stretch), and
    Vol+ before the exit's edge first moves (step 1): the entry's tail from there;
  - Menu, Source, Power and direct-select (HDMI), each during the entry and during the exit;
  - Source late in the exit (step 29 of 32);
  - the BT key (IR 0x0E) during the exit on Bluetooth;
  - Source with 0x21.3 set during the exit.

  For keys on page 1 during the exit, the screen 0.15 s after the key must equal a whole
  refresh for that state, and the screen at the end must equal `home_model`.
- **Source, then Vol+ 0.2, 1.0 or 2.0 s later** (the refresh's flags still set, so its flag
  path runs mid-exit): 32 + 32 steps. Two ticks after the exit the screen is a whole home,
  and later it matches fast-lcd.
- **Keys on the open page** (`roll_scenarios`, whole firmware, lockstep with fast-lcd, the
  page at 9): Vol+ 9 -> 10, Vol- 10 -> 9, 9 -> 8, 8 -> 9: the 14 frames come on 14 consecutive
  Timer0 ticks, each frame's box = `roll_box`, the line's split moves monotonically to the
  volume's over 27 ticks, then the page is the static one and the state as fast-lcd's; worst
  tick 5.45 ms. Knob speed (6 keys 60 ms apart, each way): 6 rolls, the page at rest = the
  static page, worst tick 5.76 ms. Audio as fast-lcd. A roll cut at frame 6 by Menu (home, as
  `read_key` makes it on page 2), Source (home) and Power (standby identical to fast-lcd):
  no roll left, same state and audio as fast-lcd.
- **Panel scan:** see "A step" above: 16 or 17 frames inside each 32-step wipe, from the end of
  the first step that moves the edge to the start of the last.
- **INT1** (`int1`, 100 whole-firmware runs per image, 7 s):
  - Setup: USB, settled, Vol+ from home with INT1's RAM effects injected at the press
    (0x21.4, 0x43:0x44 = 30, 0x4E = 0xFF), the press moved in 1 ms steps across one
    10-tick format-poll period.
  - Results: the DAC reconfiguration (0x46A0) always comes before the unmute, and the unmute
    is 0.12 s earlier to 0.02 s later than fast-lcd (hn8 rebuilt: the same).
  - Near a format poll the main loop takes the key's volume write or the poll's DAC
    reconfiguration first, depending on where in the loop and in the 10-tick poll period the
    press is seen. Both orders are stock behaviour. hn5's poll period is shifted against
    fast-lcd's, because fast-lcd's slower home refreshes after power-on lose more ticks, so
    at 10 offsets in hn9 (0..2, 45..52 ms; hn8 rebuilt: 9, the same without 45) the two images
    take the two in a different order. At
    those offsets the test requires the same number of audio states, the same final state
    and the DAC reconfiguration no later than fast-lcd's + 0.10 s (hn5's is up to 100 ms
    earlier). At every other offset the audio states match in order and time.
- **IR sweep:** 256 commands x 5 states, against fast-lcd, 72 s. Page-1 screens must equal
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

- **Panel timing: same as fast-lcd.** `uk_fill` and `uk_text` use fast-lcd's byte timing (the
  WR pulse the blit-test build proved on the panel; see fast-lcd's README, Bus timing).
- **The main loop now runs during the wipes.** A tick's step, spring and roll take at most
  6.9 ms, after the tick's own work. The volume keys, format poll, unmute and re-mute run as on fast-lcd (tested
  against it, including the INT1 case the hn3 review raised).
- **The tick driver's re-mute part** (hn9): `uk_tasks` runs `main_tick_tasks`' first
  instructions itself (0x21.4 set: clear it and 0x22.4, `lcall volume_apply`), so the stock
  code at 0x3325 is duplicated in ours; the build asserts those bytes, and a unit test compares
  the two for every combination of request and tick. The INT1 sweep and the audio comparisons
  against fast-lcd pass as before.
- **Stock routines called from a step** (`home_draw_output_icon`, `home_draw_volume`,
  `home_draw_format_tag`, `home_draw_eq_tag`, `big_text_load`, the status loader 0x4016 with
  its signal check and I2C reads) run in the main loop, as they do from
  `home_refresh_periodic`. The stack peak is unchanged (0xAF with Timer0
  only, 0xB3 with Timer3; see Stack above).
- **Recovery: unchanged.** The reset vector, the standby key handler (0x59B2) and
  `read_key`'s Source-in-standby jump to the bootloader (0x3DB8) are untouched.

## What to look for on the amp

hn10.1, the status tint: on an input without a signal (status reddish), press Source or a direct
input key. The next input's first status text ("Digital input", "initializing") is grey at once.
It turns reddish 2 to 3 s later only if that input has no signal either. The BT key's
"BT Reconnect" and the EQ key's description are grey too.

hn9, the animations:
- Vol+/Vol- on the open page: the old number slides out (up on Vol+, down on Vol-) and the new
  one slides in from the other side, getting brighter, in about 0.14 s. Is one number per frame
  enough, or does it read as a flicker? Is the old one's two frames (20 ms) visible at all?
- Nothing of the number shows over "VOL" or the line while it slides, and nothing is left
  behind (a step from 10 to 9, 9 to 10, fast knob turns).
- The line's fill glides to the new position (about 0.3 s for a step, 0.6 s for 0 to 60)
  without overshooting; opening the page, it grows from the left while the edge wipes in; on
  the way home it shrinks while the edge wipes back.
- Knob turned fast: the number keeps rolling to the latest value and the page ends clean.
- Menu, Source or Power right after a volume step: the page goes as before, no half-drawn
  number.

hn8, the volume page:
- Vol+/Vol- on home: the page is the mock's: input name and status line left, "VOL" and the
  large number right, the line with the dB level and "max 60" under it. Are 36 px for the
  name and 16 px for the small texts right next to hn7's home? (Sizing by eye is not in
  `sizing.html` for this page yet.)
- Turn the volume: only the number, the line and the dB value change; a step from 10 to 9 or
  from 60 to 59 leaves nothing behind and nothing flickers.
- The status line on the page is the one the home showed (sample rate, "No signal", ...),
  reddish when there is no signal. On BT it shows "Searching..." / the codec.
- Home: the tag boxes have soft corners; without a signal (optical with nothing connected)
  the status line is reddish, grey again once the signal is back.
- Vol+ while the edge is going back: the page comes back with the status line redrawn.

hn10, the wipes: the edge now starts slowly, is fastest in the middle and slows into the far
side (the mock's cubic), 0.32 s each way instead of 0.20 s. Does the slow start read as a delay
after the key (the edge first moves on the entry's third tick)? Is 0.32 s too slow on the way
home? A key during the slow ends (just after pressing, or just before the edge arrives) turns
the wipe round cleanly.

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
  has passed it, then VOL and the divider, then the line, the name and the captions, the
  status line last.
- 2 s after the last key: the edge sweeps back to the right. The icon, volume and bar
  appear first, then the status line and name, the format tag, and the EQ tag last. The
  finished screen must not change when the periodic refresh comes about 0.4 s later.
- Vol+ while the edge is going back: it turns round and the volume page comes back with the
  new value.
- Menu, Source, Power or a direct input key during either wipe: the wipe stops and the
  stock screen follows, without leftovers of the volume page.
- On Bluetooth, optical without signal, headphones, right after power-on or an input
  switch: the same wipes; the unmute comes at the same moment as without a key.
- Digits sharp, no torn columns or colour shifts (a dropped bus byte shows as a colour
  shift, see fast-lcd's README, Bus timing).
- Accent: SMSL orange on the White theme, the theme colour otherwise.

## How to go back

Flash `features/fast-lcd/build/flash_fastlcd.bin` (stock UI, fast pixel path) or
`features/direct-select/build/flash_patched.bin` (stock UI, stock pixel path, direct
input selection over IR).

## Files

- `layout.json` is the home layout; `sizing.html` edits it (see "Layout").
- `TODO.md`: what is left against the mock, and what to investigate.
- `build_patch.py` builds `build/flash_house_numerals.bin` from
  `features/fast-lcd/build/flash_fastlcd.bin` and writes the listing
  `house_numerals.asm`. It uses the text instructions added to `tools/patch/asm51.py`
  (`Asm.op`, `#hi(label)` / `#lo(label)`).
- `emu_test.py` runs the unit tests, the whole-firmware scenarios, the INT1 sweep and the IR
  sweep above.
