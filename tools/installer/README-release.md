# SMSL AO300 custom firmware

A replacement firmware for the SMSL AO300 amplifier's control chip. It keeps everything the
amp does and adds, on top of a new look for the display:

- **Volume cap at power-on.** The amp starts at most at a volume you choose (speakers and
  headphones each), instead of wherever it was left. The volume keys are not limited.
- **No pop** from the volume keys on Optical and Coaxial when there is no signal, and no
  pop when an input is chosen in the menu.
- **Auto OFF** of the display works after power-on, as on the AO300 PRO.
- **Direct input selection** over infrared (six extra NEC commands for programmable remotes).
- **Two looks** for the display: House Numerals (large, clean numerals and a sliding volume
  page) or Phosphor Panel (a VFD-style dot-matrix name, lamps and seven-segment digits).

The amp's RESET menu page shows the firmware's name (for example `v1.4 tbenr pp2`), so you
can always see which one is running. This firmware is built from SMSL's own v1.4 image, which
you supply; it is not included.

## What you need

- An SMSL AO300 on firmware v1.4 (the vendor updater `SMSL_AO300_UPDATE_VER0A5_EN.EXE`),
  downloaded from SMSL's support pages.
- A **3.3 V USB-to-serial adapter** (CH340, CP2102, FTDI or similar) wired to the amp's
  4-pin header: GND, TX, RX (the adapter's TX to the amp's RX and vice versa). Do not connect
  the adapter's 5 V or 3.3 V to the amp.
- A Mac or a Linux computer with Python 3.8 or newer. (The installer does not run on
  Windows, but it can make a Windows updater for you: see "Flashing from Windows" below.)
- The remote, to wake the amp's bootloader (standby, then Source).

## Steps

1. Unzip this package somewhere convenient.
2. Put the vendor updater (the `.EXE` file) in the `original` folder of the package.
3. Connect the serial adapter to the amp's header and to the computer. Power the amp.
4. Open a terminal in the package folder and run:

   ```bash
   ./install.sh
   ```

   The first run creates a private Python environment and downloads three small packages
   (stcgal, pefile, pyserial). Then the installer asks you:

   - which look you want;
   - the volume caps for speakers and for headphones (a step 0 to 60 as the display shows
     it; 60 means no cap). Enter keeps the defaults.

   It builds your firmware image and checks it against the known reference build.
5. Choose **Flash** in the menu. The installer finds the serial adapter (or asks which one),
   then hands over to the flasher, which waits for the amp. **Put the amp in standby and
   press Source on the remote.** The flasher checks that the chip is a factory AO300 before
   it erases anything, writes the image (about 15 seconds) and the amp restarts with the new
   firmware.

Nothing is written to the amp before you choose Flash, and the installer never asks for your
password: do not run it with `sudo`. On Linux, if the serial port is not accessible, add
yourself to the serial group once (`sudo usermod -aG dialout "$USER"`, `uucp` on Arch) and
log in again.

## Flashing from Windows

If the serial adapter is on a Windows PC, choose **Make a Windows updater (.exe)** in the
menu instead of Flash. The installer writes an `.exe` next to your image in `build/out`: a
copy of SMSL's updater that carries your firmware instead of the stock one. Copy it to the
Windows PC and use it exactly like SMSL's updater: start it, click its start button, then
put the amp in standby and press Source on the remote.

This needs the vendor `.EXE` in the `original` folder (a bare `flash.bin` is not enough).
The updater does not run the checks the installer's own flasher runs, so use it only on an
AO300. To go back to stock from Windows, run SMSL's original updater.

## If something goes wrong

- **The flasher stops before writing** ("CHECK FAILED"): nothing changed, the amp restarts
  as it was. Check the wiring (TX/RX swapped is the usual cause) and try again.
- **The flasher fails after the erase**: the amp has no firmware and stays dark, but its
  bootloader is in ROM and cannot be lost. Run `./install.sh` again and choose **Restore the
  stock firmware** (or Flash again). Unplug the amp's mains, and plug it back in when the
  flasher waits for the bootloader: a cold power-up always enters the bootloader.
- **Back to stock at any time**: the same **Restore the stock firmware** item writes SMSL's
  v1.4 image back.
- **Check the connection only** reads the chip's identity and runs the checks without writing.

Every flasher run is logged in `tools/flash/flash_ao300.log` inside the package; attach it
when asking for help.

## Changing your mind

Run `./install.sh` again: it reuses the extracted stock image, asks the questions again and
flashes the new build. Your image and a text file describing it (sha256, settings, date) are
in `build/out`.
