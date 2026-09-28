# Volume screen (design stage)

A new home screen and volume screen for the AO300's 320 × 170 colour LCD. Nothing here
is built into firmware yet.

`volume_studies.html` is an interactive sketch page. Open it in a browser; it needs
internet access only for its web fonts. It contains:

- the stock v1.4 home and volume screens, rebuilt from the firmware's draw calls, with a
  table of element positions and routine addresses;
- six proposals (Blue Meter, Phosphor Panel, House Numerals, Halo Ring, Level Ladder,
  Colour Orb). Each has a home screen carrying the stock information (volume next to the
  output icon included), a volume screen, and a transition in each direction. The screen
  returns home 2 s after the last step;
- controls for volume, mute, input, signal, the eight COLOR themes, a 0–60 or dB readout,
  and a frame rate throttled to the stock LCD driver or a tuned blit;
- the "Tuned blit" write-up: the faster pixel path these screens need, with 8051 loops,
  timing against the ST7789 and a test plan.

Constraints the designs follow:

- no framebuffer, so screens are generated as they are sent;
- transitions repaint the screen at most once, which is why they are wipes and reveals;
- colours are RGB565.

The screen layout, fonts and bus details are in the main README's hardware map. The
steps-vs-dB mapping is in its "Volume scale" section.

Next steps toward a build:

1. Pick a design and a dB reference.
2. Build the tuned blit behind a debug IR command and verify it on the amp.
3. Replace the two-digit volume draws at 0x5916 and 0x5936 and the volume page renderer
   at 0x2167, following the direct-select pattern (build script, annotated .asm,
   emulator test).
