# Notices

## What the licence covers

The MIT licence in `LICENSE` covers what was written for this project: the patch code under
`features/`, the tools under `tools/` and the documentation. It does not cover the two things
below.

## Vendor firmware

The firmware of the AO300 is SMSL's. It is not in this repository, in its history or in its
release packages, in any form. The tools build an image on your computer from the updater you
download from SMSL. An image built that way, and the Windows updater the installer can make
from it, contain SMSL's code: they are for your own amplifier and must not be shared or
published.

This project is not affiliated with, authorised or endorsed by SMSL or by STC. Their names
and product names are trademarks of their owners and are used only to say what the firmware
runs on.

## Fonts

The display themes draw with bitmaps rendered from three typefaces. The rendered glyphs are
in `tools/fonts/raster/*.json` and are built into the firmware image you make. They are
derived from the fonts below and are distributed under the SIL Open Font License 1.1, not
under the MIT licence. The licence texts are in `tools/fonts/licenses/`.

- Big Shoulders Display: Copyright 2019 The Big Shoulders Project Authors
  (https://github.com/xotypeco/big_shoulders)
- Barlow Condensed: Copyright 2017 The Barlow Project Authors (https://github.com/jpt/barlow)
- IBM Plex Mono: Copyright © 2017 IBM Corp. with Reserved Font Name "Plex"

The files here are modified versions (bitmaps at fixed sizes, a subset of the characters)
and are not named after the originals. The stock firmware's own fonts are not in this
project.

## Tools the installer downloads

Installed from PyPI by `install.sh`, not distributed here: stcgal (MIT), pefile (MIT),
pyserial (BSD-3-Clause).
