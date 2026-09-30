# House Numerals: what is left

State as of hn8 (`v1.4 tbenr hn8`, tried on the amp on 2026-09-30, works). The reference is
study 3 in `features/ui-theme/ui_themes.html`.

## To investigate: reddish status after a Source change

Seen on the amp with hn8: coming from an input whose status line was reddish ("No
Connected" on HDMI, "No signal", "Searching..."), a Source press shows the next input's
status reddish too for a while; a later refresh turns it grey. Not yet reproduced in the
emulator, so not called a bug yet.

What to check first:
- The tint comes from `HN_SIG`, written only by `hn_signal` (the status loader's signal
  check at 0x4016). If the Source path draws the status line through another route, for
  example `input_apply` (0x5640) loading "Digital input" / a sample rate into XDATA 0x50 and
  rendering it at y 135 without running the loader, `hm_status` tints it with the previous
  input's `HN_SIG` until the periodic refresh (0x3FE3, on page 1 every 0.5 s) runs the
  loader. A ~10 s wait would fit the optical/coax detect timeout instead.
- Reproduce in the emulator: `Amp(NEW)`, HDMI selected with the expander reporting no
  connection (status "No Connected", `HN_SIG` 0), then `NEC_SOURCE` or a direct-select key,
  and watch `hm_status` calls (colour written to `TP_INK`), the loader (0x4016) and `HN_SIG`
  over the next seconds. `features/house-numerals/emu_test.py`'s `tour` has the hooks
  (`Watch`, `home_ok`); the `hdmi` and `source` steps are the place to add a check.
- Candidate fixes, once the path is known: set `HN_SIG` to 1 (grey) when the input changes
  (the name draw 0x4A85 is already hooked, `hn_name_guard`; `input_apply` 0x5640 is not),
  or tint only text that the loader's no-signal branch (0x4048) produced, by marking it
  there instead of at the signal check.

## Missing against the mock

Volume page:
- **dB mode.** The mock's `S.mode === 'db'`: the number shows "−29.0", the label "VOL · dB",
  the captions "step 32 / 60" and "0 dB = step 60", numerals at 72 px. Needs a way to switch
  (menu entry or IR command) and a decision on whether the choice survives power cycles
  (EEPROM; sectors at offsets 0x0000, 0x0200, 0x0400 are in use). The dB value itself is
  done (`hv_cap`, from the NJW1194 code table).
- **Number roll.** The old number slides out and the new one in, fading, over 0.14 s
  (`this.k`, cubic ease, shift 20 px, clip 146..310 x 38..120). Needs a y clip in `uk_text`
  (only x clips exist) and a small per-tick animation in `uk_tasks`.
- **Spring on the line.** The filled part follows the volume with a spring (k 200, damping
  28); ours jumps. Per-tick task, fixed-point.
- **Sizing.** `sizing.html` covers the home only; the volume page's positions are constants
  in `build_patch.py` (`V*`). A second tab with the same save path (`layout.json`,
  `"volume"`) would let the sizes be picked by eye. Flash is tight: 2220 bytes left.
- **MUTE state** (red speaker, "MUTE" at 64 px, dark-red line): unreachable in this firmware
  (the mute key goes home, the volume keys unmute first). Only worth doing if a muted volume
  page is wanted on purpose.

Wipes:
- **Timing.** The mock's edge wipe takes 0.32 s in and 0.42 s out with a cubic ease; ours is
  20 ticks (about 200 ms) each way with a cosine ease, chosen on the amp.
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
