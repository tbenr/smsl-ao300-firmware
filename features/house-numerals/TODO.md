# House Numerals: what is left

State as of hn10.1 (`v1.4 tbenr hn10.1`, tried on the amp on 2026-09-30, works). The reference is
study 3 in `features/ui-theme/ui_themes.html`.

## Missing against the mock

Volume page:
- **dB mode.** The mock's `S.mode === 'db'`: the number shows "−29.0", the label "VOL · dB",
  the captions "step 32 / 60" and "0 dB = step 60", numerals at 72 px. Needs a way to switch
  (menu entry or IR command) and a decision on whether the choice survives power cycles
  (EEPROM; sectors at offsets 0x0000, 0x0200, 0x0400 are in use). The dB value itself is
  done (`hv_cap`, from the NJW1194 code table).
- **Number roll: one number per frame.** The mock crossfades the old and the new number (both
  drawn, each at its alpha); hn9 draws only the one with the larger alpha in each frame, in its
  grey on black (the panel is write-only and `uk_text` streams whole cells), so the old number
  shows for 2 of the 14 frames and the two never overlap. Its clip box is also cut to rows
  42..119 (the mock's 38..119 overlaps "VOL"'s cell) and to the number's columns 156..304.
  A blend would need the old number's pixels per cell (a second decode stream in `uk_text`).
- **Spring: fixed point.** Within 1.05 px of the mock's float integrator, and it stops on the
  target (the float one never quite does); settles in at most 0.63 s.
- **Sizing.** `sizing.html` covers the home only; the volume page's positions are constants
  in `build_patch.py` (`V*`). A second tab with the same save path (`layout.json`,
  `"volume"`) would let the sizes be picked by eye. Flash is tight: 1185 bytes left.
- **MUTE state** (red speaker, "MUTE" at 64 px, dark-red line): unreachable in this firmware
  (the mute key goes home, the volume keys unmute first). Only worth doing if a muted volume
  page is wanted on purpose.

Wipes:
- **Timing.** hn10 uses the mock's cubic ease, 0.32 s (32 ticks) each way. The mock's exit takes
  0.42 s; ours keeps one length both ways so a reversal maps step k to 32 − k at the same x. A
  longer exit would need its own table and a reversal that looks up the x. The length is
  `STEPS` in `build_patch.py` (measured: 26 steps fit the 8 ms budget, 20 do not without splitting
  the number's reveal step).
- **Column reveal.** The mock reveals the new page column by column at the edge; ours draws
  an element once the edge has fully passed it. The painter could draw the columns inside
  the band (as the position line already is), at the cost of a text draw per step.

Home:
- Nothing known. The tags' corners, the reddish status and the sizes are in.

## Housekeeping

- The kit's `uk_paint` (stock fonts) is no longer linked into this image; its XDATA block
  0x0130..0x0155 is still reserved by `Kit(fp_base=0x0130)`. Free it if the space is needed.
- `MONO_CHARS` carries the 59-character status set for the tag face; if flash gets tight, the
  volume page's status could drop the rarely used characters (`!'`).
