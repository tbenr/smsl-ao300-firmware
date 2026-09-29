#!/usr/bin/env python3
"""Guarded macOS/Linux flasher for the SMSL AO300 control MCU (STC8C2K64S2).

A thin wrapper around stcgal that adds the checks the bare tool lacks. Every
value it checks against was read from a real AO300 with `stcgal -D` and matched
against the vendor updater's container.

Subcommands (all need -p PORT, e.g. /dev/cu.usbserial-10):

  identify            connect, print chip info, run all checks, reset. Writes nothing.
  dryrun              identify + clock calibration + baud switch + the pre-erase
                      "prepare" packet, then reset. Still writes nothing. Proves the
                      whole path up to the point where a flash would start.
  flash IMAGE.bin     identify, checks, then erase + program + write options.
                      Asks for typed confirmation first, before waiting for
                      the bootloader (-y after the image skips it).
  recover IMAGE.bin   same as flash, for an amp whose firmware no longer runs
                      (use a cold power-up to reach the bootloader).

How to reach the bootloader when the tool says "Waiting for MCU":
  * amp running: put it in standby and press Source on the remote, or
  * any state: unplug the amp's mains and plug it back in.

Options written back are exactly the ones the chip already has (stcgal reads them
at handshake and rewrites them unchanged). Clock is calibrated to 24.000 MHz, as
the vendor updater does.

Requires: pip install stcgal   (tested with stcgal 1.10)
"""
import argparse
import hashlib
import os
import sys
import time

try:
    from stcgal.protocols import Stc8dProtocol, StcProtocolException, StcFramingException
    import serial
except ImportError:
    sys.exit("stcgal is not installed: pip install stcgal")

# ---- expected chip state (from the read-only handshake of the real amp) -----
EXPECT_MAGIC = 0xF7DC                 # STC8C2K64S2
EXPECT_MODEL = "STC8C2K64S2"
EXPECT_BSL_MIN = 0x72                 # packet format with 5A A5 magics; amp has 7.3.13U
EXPECT_MSR = bytes([0xFF, 0xBF, 0xBC, 0xF7, 0xF4])   # option bytes as stcgal models them
EXPECT_SPLIT = 62464                  # code area 0xF400, EEPROM above it (2.5 KB)
EXPECT_CLOCK_HZ = 24_000_000
CLOCK_TOLERANCE = 0.005               # 0.5 %
TRIM_TARGET_HZ = 24_000_000           # what we ask stcgal to calibrate to
STATUS_PASSWORD_INDEX = 11            # vendor tool: bit3 of this status byte clear => password required
STATUS_PASSWORD_BIT = 0x08

# ---- expected image shape ----------------------------------------------------
IMAGE_RESET_VECTOR = bytes([0x02, 0x44, 0x9F])   # LJMP main_init, same in stock and patched
IMAGE_MAX = EXPECT_SPLIT
KNOWN_IMAGES = {
    # sha256 -> description (add new builds here)
    "85e8ac50ffcf47ea159a976edbcd398e81345c0ceb3b1542e97e80a800adb0cc": "stock v1.4 (original/extracted/flash.bin)",
    "bb468b29ea935150d2c43e00074a68184920329529077898011a0c334a76f43e": "direct-select + 'v1.4 tbenr' (features/direct-select/build/flash_patched.bin)",
    "eae8f6eda5f0cf4b07dc797b3a311706aca4195666b392a8b68002418083e8d0": "direct-select + tuned-blit test on Vol+/Vol-, 5 s hold fixed, 'v1.4 tbenr blit' (features/blit-test/build/flash_blittest.bin)",
    "b292a64855975584dda5fe3fb282103bfde77f7f7237ca9945ac4b5442dae859": "direct-select + fast LCD paths, 'v1.4 tbenr fast' (features/fast-lcd/build/flash_fastlcd.bin)",
    "deada16ae67023e7fd9bb5c9668dc5a77f35b5738a19350ac138cd06470f86f1": "fast-lcd + House Numerals home and volume page, 'v1.4 tbenr hn' (features/house-numerals/build/flash_house_numerals.bin)",
    "2819e0b0f935f93012fd88d9799b6efcdd253c04269375a0d1acbb52965d787f": "fast-lcd + House Numerals v2 (200 ms wipe after the volume write, none while the unmute countdown runs), 'v1.4 tbenr hn2' (features/house-numerals/build/flash_house_numerals.bin)",
    "2c4809ab470ba0d161c460ffa69ac57fc5b54f42536c2fdbc2077fad00b920b6": "fast-lcd + House Numerals v3 (wipe also on Bluetooth and no-signal inputs, counts the unmute countdown during it), 'v1.4 tbenr hn3' (features/house-numerals/build/flash_house_numerals.bin)",
    "86aacb8be3f2d811a3bacab3c4316800eed582f07a3682943016ee82e0436623": "fast-lcd + House Numerals v4 (non-blocking eased wipes in and out of the volume page, text painter), 'v1.4 tbenr hn4' (features/house-numerals/build/flash_house_numerals.bin)",
    "5eddb6df9dc63b15a4cfaa920ba2bb745eaf14bec1a0f2b89e14d2514834bf8d": "fast-lcd + House Numerals v4.1 (edge drawn before the band, mid-exit stock redraws fixed), 'v1.4 tbenr hn4.1' (features/house-numerals/build/flash_house_numerals.bin)",
    "f9b5d14d39a2437e5a7b92089101eb9c71e166df5fb37960abb370ebf420eb01": "direct-select + Auto OFF armed after power-on (AO300 PRO V1.2 fix), 'v1.4 tbenr aof1' (features/fix-auto-off/build/flash_fixautooff.bin)",
}


class Tee:
    """Duplicate stdout into a log file so the raw packet dump is kept."""
    def __init__(self, path):
        self.f = open(path, "a")
        self.out = sys.stdout
        self.f.write("\n==== %s ====\n" % time.strftime("%Y-%m-%d %H:%M:%S"))

    def write(self, s):
        self.out.write(s); self.f.write(s)

    def flush(self):
        self.out.flush(); self.f.flush()


def fail(msg):
    print("\n*** CHECK FAILED: %s" % msg)
    print("*** Nothing was written. The amp will restart normally.")
    return False


def check_chip(p):
    """Compare what the chip reported with what the vendor tool expects."""
    ok = True
    print("\nChecks:")

    def show(name, good, detail):
        nonlocal ok
        print("  [%s] %s: %s" % ("ok" if good else "FAIL", name, detail))
        ok &= good

    show("chip magic", p.mcu_magic == EXPECT_MAGIC, "0x%04X (%s)" % (p.mcu_magic, p.model.name))
    show("bootloader", p.bsl_version >= EXPECT_BSL_MIN, "%s" % p.mcu_bsl_version)
    dev = abs(p.mcu_clock_hz - EXPECT_CLOCK_HZ) / EXPECT_CLOCK_HZ
    show("clock", dev <= CLOCK_TOLERANCE, "%.4f MHz (%.2f%% from 24 MHz)" % (p.mcu_clock_hz / 1e6, dev * 100))
    msr = bytes(p.options.get_msr())
    show("option bytes", msr == EXPECT_MSR, msr.hex(" ").upper() + " (expected " + EXPECT_MSR.hex(" ").upper() + ")")
    split = p.options.get_flash_split()
    show("code/eeprom split", split == EXPECT_SPLIT, "%d (0x%X)" % (split, split))
    sp = p.status_packet
    pw_free = len(sp) > STATUS_PASSWORD_INDEX and (sp[STATUS_PASSWORD_INDEX] & STATUS_PASSWORD_BIT) != 0
    show("no download password", pw_free, "status[%d]=0x%02X" % (STATUS_PASSWORD_INDEX, sp[STATUS_PASSWORD_INDEX] if len(sp) > STATUS_PASSWORD_INDEX else 0))
    show("bootloader pin detect off", not p.options.get_pindetect(), "cold power-up always enters the bootloader" if not p.options.get_pindetect() else "P3.2/P3.3 must be low to enter the bootloader")
    return ok


def load_image(path):
    data = open(path, "rb").read()
    print("\nImage: %s" % path)
    print("  size %d bytes (0x%X), sha256 %s" % (len(data), len(data), hashlib.sha256(data).hexdigest()[:16]))
    ok = True
    if data[:3] != IMAGE_RESET_VECTOR:
        print("  [FAIL] reset vector is %s, expected %s: not an AO300 image" % (data[:3].hex(), IMAGE_RESET_VECTOR.hex()))
        ok = False
    else:
        print("  [ok] reset vector LJMP 0x449F (AO300 firmware)")
    if len(data) > IMAGE_MAX:
        print("  [FAIL] image is larger than the code area (%d bytes)" % IMAGE_MAX)
        ok = False
    else:
        print("  [ok] fits the code area (%d of %d bytes)" % (len(data), IMAGE_MAX))
    known = KNOWN_IMAGES.get(hashlib.sha256(data).hexdigest())
    print("  %s" % ("[ok] known image: " + known if known else "[info] not a registered image (fine if you just built it)"))
    if not ok:
        return None
    if len(data) % 512:
        data += b"\xff" * (512 - len(data) % 512)
    return data


def connect(port, debug):
    p = Stc8dProtocol(port, 2400, 115200, TRIM_TARGET_HZ)
    p.debug = debug
    print("Port %s. Waiting for the bootloader." % port)
    print("  -> standby + Source on the remote, or unplug/replug the amp's mains.")
    p.connect(autoreset=False)
    p.initialize()
    return p


def cmd_identify(args):
    p = connect(args.port, args.debug)
    ok = check_chip(p)
    p.disconnect()
    print("\nIdentify: %s" % ("all checks passed" if ok else "checks FAILED, do not flash"))
    return 0 if ok else 1


def cmd_dryrun(args):
    p = connect(args.port, args.debug)
    ok = check_chip(p)
    if not ok:
        p.disconnect(); return 1
    print("\nDry run: calibrating clock, switching baud, sending prepare packet (no erase)...")
    p.handshake()
    print("  calibrated to %.4f MHz, trim %s, divider %s" % (p.trim_frequency / 1e6, tuple(p.trim_value), p.trim_divider))
    p.disconnect()
    print("\nDry run complete: the chip accepted every step up to the point where an erase would start.")
    return 0


def cmd_flash(args, recover=False):
    data = load_image(args.image)
    if data is None:
        return 1

    # Ask before connecting: the bootloader must not sit idle between the
    # handshake and the erase. After this, the chip checks are the only gate.
    print("\nThis will ERASE the chip and write %d bytes, if all chip checks pass." % len(data))
    if not args.yes:
        try:
            answer = input("Type FLASH to continue, anything else to abort: ")
        except EOFError:
            answer = ""
        if answer.strip() != "FLASH":
            print("Aborted. Nothing was sent to the amp.")
            return 1

    p = connect(args.port, args.debug)
    ok = check_chip(p)
    if not ok:
        p.disconnect(); return 1
    print("\nAll checks passed. Options written back unchanged: %s" % bytes(p.options.get_msr()).hex(" ").upper())

    p.handshake()
    erased = False
    try:
        p.erase_flash(len(data), p.options.get_flash_split())
        erased = True
        p.program_flash(data)
        p.program_options()
    except (StcProtocolException, StcFramingException, serial.SerialException, IOError) as ex:
        print("\n*** ERROR during %s: %s" % ("programming" if erased else "erase", ex))
        if erased:
            print("*** The chip was erased and may not run firmware now.")
            print("*** Recovery: unplug the amp's mains, run  flash_ao300.py recover -p %s IMAGE  and plug it back in." % args.port)
        return 1
    p.disconnect()
    print("\nDone. The amp restarts with the new firmware.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-p", "--port", required=True, help="serial device, e.g. /dev/cu.usbserial-10")
    ap.add_argument("-D", "--debug", action="store_true", help="dump raw packets")
    ap.add_argument("--log", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "flash_ao300.log"),
                    help="append all output to this file (default: next to the script)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("identify")
    sub.add_parser("dryrun")
    for name in ("flash", "recover"):
        s = sub.add_parser(name)
        s.add_argument("image")
        s.add_argument("-y", "--yes", action="store_true", help="skip the typed confirmation")
    args = ap.parse_args()

    sys.stdout = Tee(args.log)
    print("flash_ao300 %s" % " ".join(sys.argv[1:]))
    try:
        if args.cmd == "identify":
            return cmd_identify(args)
        if args.cmd == "dryrun":
            return cmd_dryrun(args)
        return cmd_flash(args, recover=(args.cmd == "recover"))
    except KeyboardInterrupt:
        print("\ninterrupted"); return 2
    except (StcProtocolException, StcFramingException) as ex:
        print("\nProtocol error: %s" % ex); return 1
    except serial.SerialException as ex:
        print("\nSerial port error: %s" % ex); return 1


if __name__ == "__main__":
    sys.exit(main())
