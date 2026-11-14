# Phosphor Panel

Study 2 ("Phosphor Panel", after Marantz, Pioneer and Accuphase VFDs) from
`features/ui-theme/ui_themes.html`, built the way House Numerals is built: on top of fast-lcd,
through `tools/patch/uikit.py`, with direct-select, fix-auto-off, strings, start-volume,
fix-volume-pop and fix-menu-input included (auto-switch is not: still under development). The
RESET page shows `v1.4 tbenr pp4`.

## Status

pp4 (sha256 `cc2292e7…`, 2026-11-14): pp3 rebuilt on direct-select v4, where an input command in
standby powers the amp on, on that input (build-time config `direct-select.WAKE_ON_INPUT`,
default 1); nothing of the theme changed. Emulator-verified (all groups and the six fixes'
integration jobs), not flashed.

pp3 (sha256 `273edf8f…`, 2026-10-16): pp2 rebuilt on direct-select v3, which adds the idempotent
power commands NEC 0x16 (on) and 0x17 (off); nothing of the theme changed. Emulator-verified
(all groups and the six fixes' integration jobs), not flashed. pp2 ran on the amp until
2026-11-14, when house-numerals hn19 replaced it.

pp2 (sha256 `f5ca8bba…`): pp1 with the name's glyphs placed on the dot grid where they keep the
most ink. Emulator-verified on 2026-10-10 (all groups: unit, tour, int1, sweep, and the six
fixes' integration jobs), flashed on the amp the same day over the ser2net tunnel and
confirmed by the user: the O and C edges look right.

pp1 (sha256 `38a1499e…`): flashed on the amp on 2026-10-10 over the ser2net tunnel and
confirmed by the user: works, the dot-matrix name reads well. One thing seen: the left edge of
O and C looked cut off. The grid dropped the full column right behind those glyphs' faint
anti-aliased first column (their ink starts 1 px from the pen, P's and L's 2 px, so the grid's
black column fell on a different ink column per letter). pp2 moves each glyph right by 0, 1 or
2 px inside its cell to the position where the grid keeps the most ink (`dot_matrix` in
`build_patch.py`): O and C keep their full edge column.

## What the build shows

Everything lit is drawn in the *phosphor* `ph`: the COLOR tint, or mint `#5af5d8` on the White
tint. Brightness is a ladder of eight levels made from `ph` with `uk_avg` (7 = ph, 6 = 3/4, 5 =
1/2, 4 = 3/8, 3 = 1/4, 2 = 3/16, 1 = 1/8, 0 = black); level 1 is the *ghost* of an unlit VFD
segment. The screen is black (the mock's `#020504` is black on this panel).

| Element | Build |
|---|---|
| Row: output icon | icons16 at 12, baseline 23: speaker, headphones; the muted speaker red `#ff5a48` |
| Row: volume | IBM Plex Mono 16 px at x 36, ph, no leading zero (the slot to x 63 cleared) |
| Row: input lamp | USB, OPT, COAX, BT, ARC, AUX, PHONO from RAM 0x47 at x 72 (input 7: blank) |
| Row: format lamp | the stock format tag (PCM, DSD, DoP, MQA, MQA.) at x 132; blank on inputs without one |
| Row: EQ lamp | the stock EQ tag (DIR, CUS, ...) at x 192 |
| Row: MUTE lamp | "MUTE" right-aligned to x 308: red when muted, dark red `#2a0c09` otherwise |
| Name | Big Shoulders Display 54 px, ph, centred on x 160, baseline 104, as a dot matrix: every third column and row of the screen grid is black (baked into `pf_name`; the start x is kept at 1 mod 3 so the grid lines up across letters, each letter's cell padded to a multiple of 3 and the letter placed in it where the grid keeps the most of its ink) |
| Status line | IBM Plex Mono 20 px centred on x 160, baseline 136, 7/8 ph; red when the status loader's signal check found none on a digital input (only the loader's own text, as in House Numerals) |
| Volume page: cells | four seven-segment cells at x 66, 110, 154, 198, rows 32..91, 30 px wide with the mock's 0.12 skew, thickness 6, hexagonal ends, anti-aliased; cells 0 and 1 always ghosts, cells 2 and 3 the tens (blank below 10) and ones; each segment at its own level |
| Volume page: "VOL" | mono 16 at 18, baseline 90, ph (lit: the steps readout) |
| Volume page: "dB" | mono 16 at 250, baseline 90, a ghost (no dB mode) |
| Volume page: bar | 50 cells of 4 x 16 at x 10 + 6 i, y 118: lit (ph) when i < round(50 shown / 60), else ghost; muted: none lit |
| Volume page: marks | "0 15 30 45 60" mono 16 centred at x 10 + v / 60 * 298, baseline 160, 5/8 ph |
| Counter | the number shown steps one towards the volume every 2 ticks (the mock's 45/s): a knob turn rolls the digits |
| Afterglow | a segment or bar cell that lights goes to 7 at once; one that goes out fades a level every 4 ticks down to the ghost (the mock's 0.13 s decay) |
| Muted | the digits blink: lit 50 ticks, out 40 (the mock's 0.9 s), each "out" an afterglow; no bar cell lit; the MUTE lamp red |
| Entry | about 0.3 s: tick 1 the slot and the status line go black, the marks and the ghost bar appear; the name falls a level every 2 ticks while the bar scans in 3 cells a tick; once the name is black "dB" and the ghost cells appear and the digit cells and "VOL" rise a level every 2 ticks |
| Exit | about 0.33 s: the marks and "dB" go; every lit segment, bar cell and "VOL" fall a level every 2 ticks; then the ghost cells go; once every cell is black the name rises; then the slot and the status line |
| Reversal | a key during an exit turns it round through the same targets, and the other way; any stock clear stops the engine; a page-1 name or status draw during an exit ends the exit with the whole home first |
| Mute key | as House Numerals hn14: toggles as stock, then shows the volume page (also on the open page) |

## How it works

The row's lamps are the stock home painters replaced one by one (icon 0x5744, volume 0x5916, EQ
tag 0x4F18, format tag 0x425D and its clears), so every stock sequence that draws home parts
draws ours; the big text renderer hands every big text to `pp_name` (0x2A25: the name, then
the input lamp and the format lamp through the stock `home_draw_format_tag`, so the row
follows an input change at once), and the small text renderer hands the page-1 status line
(y 135) to `pp_status` (0x3A82). The row stays on screen across the volume page; only the icon
and volume slot is blacked out there.

The transitions and the volume page are driven by a per-tick engine (`uk_tasks` -> `pp_step`,
hooked on 0x5B2A, after the stock tick work, amp on). Every faded element (the name, "VOL",
the 28 segments, the 50 bar cells: `PP_LV`, one byte each, target << 4 | level) moves one level
at a time towards its target and is repainted when it moves. Each tick: the counter, the
blink, the entry's bar scan, the statics (the slot and status clear, the marks, the ghost bar,
"dB"; one a tick, and no move in a tick that painted a static), the targets (`pp_retarget`:
the gates between the name and the cells, the digits' segments from the counter, the bar's
limit), the moves (`pp_move`: ramps for the name and, while entering, the cells and "VOL";
jumps otherwise; falls every 2 ticks in a transition, every 4 as afterglow) and the settling
(`pp_settle`: the volume page once the scan is through and "dB" is shown; home once nothing
moves and the statics are gone, then the slot and the status line are drawn and the engine
stops). `PP_ST` is the state: 0 home, 1 entering, 2 the volume page, 3 exiting.

The seven-segment cell is one run-length map (`pp_cellmap`, column-major, segment index and
coverage level per run, 541 bytes, generated by the build from the mock's polygons at 4 x 4
samples a pixel) streamed by `pp_cell` through a palette of 7 segments x 3 coverage levels
computed from the segments' levels before each cell (1.4 ms a cell). Bar cells are `uk_fill`;
texts are `uk_text`.

Entry: the four volume-key sites and the page-2 renderer start it (`pp_enter_vol`); the key
handler's tail still writes the volume before anything is drawn. Exit: the Timer0 return home
sets page 1 and 0x22.3; `ui_render_page`'s clear (0x2106, `pp_clear`) starts the exit instead
of clearing, and the periodic refresh at 0x4081 (`pp_hold`) is held back while a transition
runs (its loader fills the status buffer, which the exit's end draws). Any stock clear
(`ui_clear_screen` 0x5D42, `pp_cancel`) stops the engine first; so does a page-1 draw during
an exit (`pp_busy_home`: the name guard at 0x4A85, `pp_name`, `pp_status`), which ends the exit
with the whole home screen. The flag path (0x3FF8) skips its black-out while the engine owns
the screen.

Hooks: see `HOOKS` in `build_patch.py` (every one from `uikit.STOCK_SITES`, the mute key 0x1047,
read_key's page-2 filter 0x3DD1, and the four entry sites). The stock big font is dead in this
image (as hn17): the status font, the icon font and the cell map sit in its place at
0x6A23..0x7BCA; the tests trap `big_glyph_paint` and `bignum_digit` on every run.

Tick budget: the worst engine tick measured is 6.9 ms (the name's first fall step, "OPTICAL";
"SPEAKERS", the widest big text, would add about 1 ms), under the 8 ms House Numerals works
to. A whole home draw by a stock sequence is 14.7 ms (the name's two side clears are 6 ms of
it; stock's refresh is about 45 ms).

## Memory

Code and fonts 0x9800..0xDBFD, the version string after them (the image ends at 0xDC0C:
56333 bytes), the hole 0x6A23..0x7BCA (4520 of 5040 bytes). The fonts: `pf_name` 9711 bytes (the
dot matrix breaks the run-length runs every third row: three times the plain face), `pf_row`
2107, `pf_status` 3681, `pf_icon` 298, the cell map 541. XDATA 0x0100..0x01F8.

## Files

- `build_patch.py` builds `build/flash_phosphor_panel.bin` and the listing `phosphor_panel.asm`.
- `emu_test.py` (see its docstring): `unit`, `tour`, `int1`, `sweep`; `python3 tools/run_tests.py
  phosphor-panel` runs it with the six fixes' integration jobs.
- The mock: `features/ui-theme/ui_themes.html`, study 2.

## Not in this build (the mock)

- dB mode (cells 0 and 1 and "dB" are permanent ghosts).
- The sample rate in the row (the mock shows it there when a signal has a format); it stays in
  the status line under the name.
- The transition is sequenced (the name out, then the digits up), not blended; the status
  line is cleared and redrawn, not faded; the row's lamps do not fade.
- Sizes: the row at 16 px (the mock's 10 and 12 px were the sizes House Numerals found too
  small on the amp), the status at 20 px (mock 13), the marks at 16 (mock 9), the name at 54
  (mock 58; the raster that exists). All in `build_patch.py`'s layout block.
- The brightness ladder has 8 steps (the mock fades continuously).

## Shared with House Numerals

The hook plumbing (`pp_hold`, `pp_cancel`/`pp_stop`, `pp_flag_path`, the name guard,
`pp_home_now`, the signal check, the mute key and the page-2 filter, the entry sites) and the
tag copy are House Numerals' routines adapted to this engine's state; a second engine-based
theme would be the moment to move them, and the level engine itself, into `uikit`.
