# UI themes (design stage)

Visual themes for the AO300's 320 × 170 colour LCD. A theme restyles the two screens
the stock firmware shows most, the home screen and the volume screen, and the
transitions between them. Menus, the RESET page and the standby screen stay stock.
Nothing here is built into firmware yet.

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

The fast pixel path the themes rely on is built. `features/fast-lcd` routes the stock UI
through it, and its README has the bus timing the blit-test build verified on the amp.

Constraints the designs follow:

- no framebuffer, so screens are generated as they are sent;
- transitions repaint the screen at most once, which is why they are wipes and reveals;
- colours are RGB565.

The screen layout, fonts and bus details are in the main README's hardware map. The
steps-vs-dB mapping is in its "Volume scale" section.

Next steps toward a build:

1. Pick a theme and a dB reference.
2. Build on top of fast-lcd, so full repaints are cheap.
3. Replace the home refresh at 0x5C8B, the two-digit volume draws at 0x5916 and 0x5936,
   and the volume page renderer at 0x2167. Follow the feature pattern in `AGENTS.md`:
   a build script, a listing, an emulator test that includes a full-firmware UI tour,
   and a README.

House Numerals has a first build in `features/house-numerals/` (emulator-verified, not
yet tried on hardware). Step 3's hooks are done there: 0x5916 (`home_draw_volume`) stays
stock, called as before from the new home-refresh tail; 0x5936 (`volpage_draw_volume`)
is replaced outright; and the page-2 renderer (0x2167) is replaced too, though the tour
found the volume keys actually open page 2 through four inline sites in the key
handlers, not through that renderer — see the feature README for all ten hooks.
