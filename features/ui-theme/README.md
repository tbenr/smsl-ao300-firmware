# UI theme designs (the mock)

Visual themes for the AO300's 320 × 170 colour LCD. A theme restyles the two screens
the stock firmware shows most, the home screen and the volume screen, and the
transitions between them. Menus, the RESET page and the standby screen stay stock.
Two of the six designs here are built: House Numerals (`features/house-numerals/`) and
Phosphor Panel (`features/phosphor-panel/`).

A theme sits on top of the stock COLOR menu. The firmware's eight COLOR settings only
choose the text colour (table 0x9241). Each theme uses that colour as its tint, so
COLOR keeps working with any theme.

`ui_themes.html` is an interactive design page. Open it in a browser; it needs internet
access only for its web fonts. It contains:

- the stock v1.4 home and volume screens, rebuilt from the firmware's draw calls, with a
  table of element positions and routine addresses;
- six themes: Blue Meter, Phosphor Panel, House Numerals, Halo Ring, Level Ladder and
  Colour Orb. Each has a home screen carrying the stock information (the volume next to
  the output icon included), a volume screen, and a transition in each direction. The
  screen returns home 2 s after the last step;
- controls for volume, mute, input, signal, the COLOR tint, a 0–60 or dB readout, and a
  frame rate throttled to the stock LCD driver or the fast pixel path.

Constraints the designs follow:

- no framebuffer, so screens are generated as they are sent;
- transitions repaint the screen at most once, which is why they are wipes and reveals;
- colours are RGB565.

The screen layout, fonts and bus details are in `docs/hardware.md` (the hardware map's
Display row); the steps-against-dB mapping is in its "Volume scale" section. The fast pixel
path the themes rely on is `features/fast-lcd`, whose README has the bus timing.

## From a design to a build

A theme is built on top of fast-lcd with `tools/patch/uikit.py` (`docs/ui-kit.md`), following
the feature pattern in `AGENTS.md`: a build script, a listing, an emulator test that includes
a whole-firmware UI tour, and a README. The stock sites a theme takes over are the home
refresh at 0x5C8B, the two-digit volume draws at 0x5916 and 0x5936, and the volume page:
the page-2 renderer at 0x2167, and the four inline sites in the key handlers through which
the volume keys actually open page 2. Each theme's README lists its hooks and what it
reduced from the mock.
