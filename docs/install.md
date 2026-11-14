# Installing the custom firmware

What the firmware adds, and the risks, are in the [README](../README.md). Read its "Read this
first" section before you flash anything.

## What you need

- An SMSL AO300. Everything here was developed and tested on one unit. The AO300 PRO is a
  different device and is not supported.
- SMSL's updater `SMSL_AO300_UPDATE_VER0A5_EN.exe` (see "Getting SMSL's updater" below). The
  installer takes the stock firmware out of it; nothing here contains it. Keep the file: it
  is also your way back to stock.
- A USB-C data cable from the amp's USB socket to the computer. The amp shows up as a USB
  serial port (a CH340), the same connection SMSL's updater uses. A charge-only cable will
  not work.
- A Mac or a Linux computer with Python 3.8 or newer. (The installer does not run on
  Windows, but it can make a Windows updater for you: see "Flashing from Windows" below.)
- The remote, to wake the amp's bootloader (standby, then Source).

## Getting SMSL's updater

The custom firmware is built on the firmware inside one particular SMSL updater,
`SMSL_AO300_UPDATE_VER0A5_EN.exe` (dated December 2023; the amp shows `v1.4` with it).

SMSL's website no longer offers firmware for the AO300: its download page lists only the
AO300 PRO. SMSL's support sent this updater to an owner in May 2024, who posted it in the
Audio Science Review thread on the AO300:
[post #384, "Received new firmware from SMSL"](https://www.audiosciencereview.com/forum/index.php?threads/new-product-smsl-ao300.47897/post-1976706),
attachment `SMSL_AO300_UPDATE_VER0A5.zip`. You can also ask SMSL's support for it.

Check what you downloaded before you use it. The `.exe` inside the zip must have this sha256
(`shasum -a 256 FILE` on macOS, `sha256sum FILE` on Linux):

```
37c756098bed260f7a8d3d6984008057da0f7cf8267e0a6c4e23c03e554df0f0
```

The installer checks the firmware it extracts as well, and refuses anything else. That
matters here, because several different firmwares show `v1.4` on the amp: the other updaters
posted in that thread (`VER0A4`, and a "factory 1.4" one) carry different firmware and will
not work.

## Steps

1. Get the files: download the package (`ao300-custom-….zip`) from the
   [latest release](https://github.com/tbenr/smsl-ao300-firmware/releases/latest) and unzip it. A clone of the repository works the same way.
2. Put SMSL's updater in the `original` folder (create the folder if it is not there). The
   file's name does not matter.
3. Connect the amp to the computer with the USB-C cable. Power the amp.
4. Open a terminal in the folder and run:

   ```bash
   ./install.sh
   ```

   (`bash install.sh` if unzipping dropped the file's executable bit.) The first run creates a private Python environment in `.venv` and downloads three small
   packages (stcgal, pefile, pyserial). Then the installer asks you:

   - which look you want;
   - the volume caps for speakers and for headphones (a step 0 to 60 as the display shows
     it; 60 means no cap);
   - whether an input command wakes the amp from standby (1: yes, 0: it is ignored there).

   Enter keeps the defaults.

   It builds your firmware image and checks it against the known reference build.
5. Choose **Flash** in the menu. The installer finds the amp's serial port (or asks which
   one), then hands over to the flasher, which waits for the amp. **Put the amp in standby
   and press Source on the remote.** The flasher checks that the chip is a factory AO300
   before it erases anything, writes the image (about 15 seconds) and the amp restarts with
   the new firmware.
6. Turn the volume down before you play anything, the first time.

Nothing is written to the amp before you choose Flash, and the installer never asks for your
password: do not run it with `sudo`. On Linux, if the serial port is not accessible, add
yourself to the serial group once (`sudo usermod -aG dialout "$USER"`, `uucp` on Arch) and
log in again.

The amp's RESET menu page shows which firmware is running: `v1.4 tbenr` and a build tag.

## Flashing from Windows

If the amp is connected to a Windows PC, choose **Make a Windows updater (.exe)** in the
menu instead of Flash. The installer writes an `.exe` next to your image in `build/out`: a
copy of SMSL's updater that carries your firmware instead of the stock one. Copy it to the
Windows PC and use it exactly like SMSL's updater: start it, click its start button, then
put the amp in standby and press Source on the remote.

- It needs SMSL's `.exe` in the `original` folder (a bare `flash.bin` is not enough).
- It contains SMSL's program and firmware code: it is for your own amp. Do not share or
  publish it.
- It does not run the checks the installer's own flasher runs, so use it only on an AO300.
- This route is less tested than the flasher: two amps have been flashed with a rebuilt
  updater, far fewer times than with the flasher (`docs/status.md`).
- To go back to stock from Windows, run SMSL's original updater.

## If something goes wrong

- **No serial port is found.** Check that the cable carries data and that the amp is powered.
  On Linux, `dmesg` shows a `ch341` line when the amp is plugged in.
- **The flasher stops before writing** ("CHECK FAILED"): nothing changed, the amp restarts
  as it was. Read the line that failed: the chip did not report what a factory AO300 reports.
- **The flasher fails after the erase**: the amp has no firmware and stays dark, but its
  bootloader is in ROM and cannot be lost. Run `./install.sh` again and choose **Restore the
  stock firmware** (or Flash again). Unplug the amp's mains, and plug it back in when the
  flasher waits for the bootloader: a cold power-up always enters the bootloader.
- **Back to stock at any time**: the same **Restore the stock firmware** item writes the
  firmware from SMSL's updater back. That is not necessarily the firmware your amp came with:
  SMSL shipped more than one, and the chip cannot be read back.
- **Check the connection only** reads the chip's identity and runs the checks without writing.

Every flasher run is logged in `tools/flash/flash_ao300.log`. The log holds your chip's
unique ID (the lines starting `Target UID`) and your serial port's name. Delete those lines
before you post the log anywhere public.

## Changing your mind

Run `./install.sh` again: it reuses the extracted stock image, asks the questions again and
flashes the new build. Your image and a text file describing it (sha256, settings, date) are
in `build/out`. The image is firmware: keep it to yourself.
