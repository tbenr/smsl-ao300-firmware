# Status-line flicker ("the C flickers")

Status: analysed, not fixed. No build in this folder yet.

## Symptom

On the home screen a single big letter of the input name briefly dims, every few seconds.
Users describe it as "the C flickering" because it is the C of OPTICAL. On COAXIAL it is
the second A (video 2, frame 282), and one event hit the L. It is not tied to the letter.
Reported to have appeared with a firmware later than 1.0; present in v1.4.

## What the videos show

Two phone clips, 30 fps, analysed frame by frame with per-pixel differences against the
neighbouring frames (see `evidence/`).

- The change is always a strip about one small-font cell wide (14 px) taken out of the
  big letter directly above the cell of the status line being written at that moment.
  - OPTICAL / "44.1kHz": the C's left stroke, which sits over the "k" of kHz
    (`optical_C_over_k_frames33-34.png`, `optical_diff_frame34.png`).
  - COAXIAL / "No signal": the second A's left stroke, over the "l" of signal
    (`coaxial_A_frame282.png`).
  - A third event hit the L, over the empty right margin of the status line.
- The strip goes dark for a single frame and is intact in the next one: a transient of
  a few milliseconds, not a persistent corruption.
- With a live optical stream the events recurred 15 frames apart (500 ms). With no
  signal on coaxial they were sparser (200 and 116 frames apart).

## What the firmware does

Display: ST7789-class panel on an 8-bit parallel bus. Data on P1; P0.3 = D/C,
P0.5 = WR strobe, P0.7 = chip-select, toggled per byte (`0x567A` data byte,
`0x5C9C` command byte). Window set by `0x4437` (CASET/RASET with a 0x23 column offset).
The panel is used rotated: the code's first coordinate is the panel column = screen
vertical; cells advance along panel rows = screen horizontal.

Text lines are character-cell buffers in XDATA, rendered on demand:

| Line | Buffer | Cells | Renderer | Glyph painter | Glyph size |
|---|---|---|---|---|---|
| big input name (y param 0x4B) | XDATA 0x35, 20 cells | 30 px advance (17 for narrow) | `0x298B` | `0x3F3C` -> blit `0x345C` | 32x30 bits, 120 B, table at 0x6A23 |
| status line (y param 0x87) | XDATA 0x50, 25 cells | 14 px | `0x3A53` | `0x2DF8` | 14x24 bits, 42 B, table at 0x5DAB |

Both renderers centre the string on a 320 px width, clear the left margin cell by cell
(`0x5161` for the big line, `0x5119` for the small one), paint each glyph, then clear
the right margin. Glyphs are painted by overwriting their cell (foreground or black per
bit), with no clear step in between.

Who redraws the status line:
- `0x3FE3`, re-armed every 500 ms from the 100 Hz tick (`0x3325`), rebuilds the status
  text: sample rate via `0x3CDC` for digital inputs, "Digital input" / "Analog input" /
  "No signal" otherwise (`0x4048` branch), through `0x4D3A` into the 0x50 buffer.
- `0x4638`, the 100 ms sample-rate poll, redraws the rate/format area when the code read
  from the receiver differs from the last one (RAM 0x4E); INT1 activity forces 0x4E to
  0xFF so the next poll redraws.
- The big line is only redrawn on input change, Source press, or a page redraw
  (`0x2101` when bit 0x22.3 is set).

## What has been ruled out

- The big-font C bitmap is a normal C; all letters have the same pixel extents.
- The renderers have no letter-specific path except the narrow-character list
  (space . - + = I) for advance width.
- The small-line windows never overlap the big line's band: big line occupies panel
  columns 0x6E..0x8B, status line 0xAA..0xC1.
- No interrupt handler writes P0 or P1; the Timer 0 handler only clears P2.5.
- The AO300 PRO v1.2 display routines are functionally identical (register renames
  only), so the Pro is not a source of a fix.

## Working conclusion

A write the code addresses to the status line transiently disturbs the big line's
pixels in the same column range, i.e. the panel or its interface, not a wrong
coordinate. Candidates: the per-byte chip-select toggling on the 8080 bus, or a panel
artefact when GRAM is written during its own refresh in that row band. Confirming this
needs a logic analyser on the bus or test builds that vary the write sequence.

## Fix candidate (no root cause needed)

Skip the redraw when the status line's content has not changed: keep a shadow copy of
the last rendered string (26 bytes of XDATA) plus its y, compare in `0x3A53` (or in its
callers) and return early on a match. In steady state the periodic writes stop and the
flicker with them; the line still updates immediately on a rate or signal change.
Estimated 40 bytes of new code. Test in the emulator by driving the renderer with the
same string twice and asserting the second call issues no bus writes.

Alternative if the above is not enough: throttle the 500 ms refresh to only run when
the signal-present state or the rate code changed (RAM 0x22.5 / 0x4E), which removes
the periodic path entirely.

## Open questions

- Exact panel controller part and interface timing spec (CS per byte allowed?).
- Whether the events with no signal are INT1-driven (receiver lock flapping) or from the
  500 ms path; a longer no-signal recording with the receiver cable unplugged would tell.
- Whether the same transient hits the small line itself (a strip of "44.1kHz" dimming)
  when the big line is redrawn; that would confirm the interface-level explanation.
