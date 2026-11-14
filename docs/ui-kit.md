# UI themes and the kit

The designs in `features/ui-theme/ui_themes.html` are built as features on top of fast-lcd.
The parts every theme needs live in `tools/patch/uikit.py`, extracted from house-numerals
(which builds byte-identical with it):

- **Routines** (a `Kit` emits them into the theme's code; XDATA for them is passed in):
  - `uk_fill`: rectangle fill in any colour, about 9 clocks per pixel.
  - `uk_paint`: streaming text painter for the stock fonts. It takes ink and background
    colours, an x clip window and scale 1 or 2, and is pixel-identical to the stock text
    renderers. `uk_home_x` gives a string's page-1 start x.
  - `uk_text`: painter for proportional fonts made from the UI mock's typefaces
    (`tools/patch/pfont.py`, `tools/fonts/`). Glyphs are 1-bit, or anti-aliased with 4 levels
    stored run-length (background, 1/4, 3/4 and ink colour, mixed on the amp by `uk_avg`).
    It takes left, right or centred alignment, letter spacing and an x clip window, and
    reports the last column drawn. About 12 clocks per pixel on the 84 px numerals.
    `uk_textc` is the same with a row clip (`TP_YC0`..`TP_YC1`, for text that slides): cells cut
    by it go through a separate decoder (`tx_yclip`, both formats, or format 2 only with
    `emit_text(one_bit=False)`), about 20 clocks per drawn pixel; `uk_text` itself sets every
    row and stays on the fast decoders (a few clocks more per call).
  - `uk_acc`: the accent colour (the COLOR tint, or the theme's own colour on White).
  - `uk_tasks`: the per-tick driver. It is hooked on `main_tasks_on`'s call to
    `main_tick_tasks` (0x5B2A) and runs the theme's step routine once per 10 ms tick,
    after the stock tick work and only while the amp is on. Animations never block the
    main loop. It serves `main_tick_tasks`' re-mute request itself before it tests the tick
    flag, so no tick is handled without the step.
- **Fonts:** descriptors and character maps of the two stock fonts for `uk_paint`; for
  `uk_text`, a `pfont.PFont` cuts a rasterised face down to the characters a theme needs and
  emits it. Sizes, for example: the 84 px numerals (digits) about 2.2 KB, the 52 px display face
  (the input-name letters) 1.3 KB, 11 px mono (all of ASCII) 1.7 KB at 1 bit or 3.3 KB
  anti-aliased.
- **Stock facts:** the stock routines, buffers and variables themes use, and a catalogue of
  hook sites with their original bytes (`STOCK_SITES`, and `VOL_ENTRY_SITES`, where the
  volume keys open page 2).
- **Helpers:** `ease_in_out()` (cosine), `ease_cubic()` / `ease_cubic_in_out()` (the UI mock's
  cubic ease, `ui_themes.html`'s `ease`, as a table of positions; it barely moves at both ends,
  so consecutive positions can be equal or 1 apart), `rgb565()`, and assembly written as text
  lines (`S`).
- **`build_image()`:** the common build, from the base sha check through to the listing.

`tools/patch/uikit_test.py` tests the kit on its own. It builds fast-lcd plus the kit and
compares `uk_paint` against the stock glyph painters and text renderers for every character
and every string in the firmware, and `uk_text` against `PFont.render` (every glyph of five
test fonts in both formats, alignment, spacing, tints, clip windows through the middle of
glyphs and runs, and `uk_textc`'s row clips: above, below, both, one row, outside, empty,
combined with x clips). `tools/emu/uitest.py` holds the helpers theme tests share.
`tools/emu/panel_video.py` renders what the glass shows, with the panel's 60 Hz line-by-line
refresh, for checking animations.

Not in the kit yet: the wipe's step engine and page-element model (still in house-numerals),
Phosphor Panel's level engine and seven-segment cell painter (still in phosphor-panel), and
per-pixel transitions. House Numerals' spring (a fixed-point spring as a per-tick matrix) and
its roll could move to the kit when a second theme needs them; the hook plumbing the two
themes share (the refresh hold, the stock-clear cancel, the flag path, the name guard, the
signal check, the mute key) is the first candidate.

Two themes are built: House Numerals (`features/house-numerals`, study 3) and Phosphor Panel
(`features/phosphor-panel`, study 2: the name as a dot matrix baked into its font, the
seven-segment cells as one run-length map streamed through a per-segment palette, and the
mock's afterglow crossfade as a sequenced fade run by a per-tick level engine). Both include
the six fixes; only one goes on the amp at a time.

## Sizing a theme's home screen

House Numerals takes its home layout from `features/house-numerals/layout.json`: every
element's font (by raster id), position, the tag boxes, the status colour and the bar.
`features/house-numerals/sizing.html` edits it. The page shows the home exactly as the
firmware draws it (same rasteriser, packing and anti-aliasing; checked pixel for pixel against
the emulator). It also shows each text's cap height on the panel in millimetres and each
font's exact size in flash, and flags overlaps and texts wider than the screen.

1. Start the font bench, a local server for the page (127.0.0.1 only; it builds nothing):

       python3 tools/fonts/rasterize.py

2. Open the sizing page at the address it prints
   (`http://127.0.0.1:8767/features/house-numerals/sizing.html`). Pick a starting point or
   `layout.json`, set the amp's state (input, status, tags, volume, mute, tint) and move
   the sliders until the checks under the screen are clear.
3. Press **Save layout and fonts**. It writes the fonts at the chosen sizes
   (`tools/fonts/raster/<id>.json`, added to `tools/fonts/specs.json`) and `layout.json`.
4. Rebuild and test by hand:

       python3 features/house-numerals/build_patch.py
       python3 tools/run_tests.py house-numerals

5. Before flashing, add the new image's sha256 (the build prints it) to `KNOWN_IMAGES` in
   `tools/flash/flash_ao300.py`, set a new `VERSION_TEXT` in `build_patch.py`, and commit
   `layout.json` with the new rasters.

The build stops with a message when `layout.json` names a font that has no raster, and asserts
that the elements don't overlap. The page needs the font bench to save; opened any other way it
previews only.
