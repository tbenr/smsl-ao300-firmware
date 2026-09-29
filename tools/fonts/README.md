# Fonts from the UI mock

The UI mock (`features/ui-theme/ui_themes.html`) draws with three Google Fonts faces, all
under the SIL Open Font License 1.1:

- Big Shoulders Display (the input names)
- Barlow Condensed (the numerals)
- IBM Plex Mono (status lines, tags, captions)

The OFL allows this use: bitmaps rendered from the faces and embedded in firmware.

`specs.json` lists the faces and sizes the themes use, as canvas font strings. `raster.html`
renders every character of each spec with the browser's text engine, the same way the mock
draws them. It posts the anti-aliased coverage of each glyph to `rasterize.py`, which writes
`raster/<id>.json`. The rendering lives in `glyphs.js`, shared with the themes' sizing pages
(`features/house-numerals/sizing.html`), which also port `pfont.py`'s packing and drawing, so
their previews are exactly what the firmware draws. A sizing page saves the rasters of the sizes
it picks and adds their specs to `specs.json`. Raster ids are the kind and the size: `disp52`,
`num36`, `mono20`, `icons23`. Each file has one line per glyph:

- the advance;
- the ink box's offset from the pen on the baseline;
- the rows, one hex digit of coverage (0..15) per pixel.

Builds read only these files, so a build needs no browser. `tools/patch/pfont.py` turns a raster
into a font for `uk_text`. It cuts the raster down to the characters a theme needs, quantises
to 1 bit or to 4 levels, and packs the 4-level fonts run-length.

A spec with `"draw"` instead of `"font"` names a drawing routine in `raster.html` (`DRAW`), for
glyphs that are shapes rather than text. `icons16` holds the mock's speaker (`S`), the muted
speaker (`M`) and headphones in the same line weight (`H`).

`rasterize.py` is the font bench: a server on 127.0.0.1 for these pages. It serves the
repository and accepts only two saves: `raster/<id>.json` (with its spec) and a feature's
`layout.json`. It builds nothing.

To add a face or size by hand: add a spec, then run

    python3 tools/fonts/rasterize.py        # prints the pages' addresses

and open `tools/fonts/raster.html?only=<id>`. The page reports a font that failed to load and
writes nothing for it, so a fallback face never gets saved by mistake. Rasters from
different browsers or systems can differ by a pixel here and there, and `engine` in each
file records which browser made it. Only re-render existing rasters on purpose: every theme
built from them changes.

These are rasters of the open fonts above, not of the stock firmware's fonts, which never
go into git.
