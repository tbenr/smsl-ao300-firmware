#!/usr/bin/env python3
"""Guarded macOS/Linux flasher for the SMSL AO300 control MCU (STC8C2K64S2).

A thin wrapper around stcgal that adds the checks the bare tool lacks. Every
value it checks against was read from a real AO300 with `stcgal -D` and matched
against the vendor updater's container.

Subcommands (all need -p PORT, e.g. /dev/cu.usbserial-10 or a pyserial URL such as
rfc2217://host:4000 for a port forwarded from another machine):

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

# ---- pyserial URLs (rfc2217://, socket://) ---------------------------------
# stcgal opens the port with serial.Serial(port=...), which only takes device paths.
# Route anything that looks like a URL through serial.serial_for_url instead, so a
# port forwarded from another machine works; plain device paths are untouched.
_REAL_SERIAL = serial.Serial


def open_port(port=None, **kw):
    if isinstance(port, str) and "://" in port:
        return serial.serial_for_url(port, **kw)
    return _REAL_SERIAL(port=port, **kw)


serial.Serial = open_port

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
    "eae8f6eda5f0cf4b07dc797b3a311706aca4195666b392a8b68002418083e8d0": "direct-select + tuned-blit test on Vol+/Vol-, 5 s hold fixed, 'v1.4 tbenr blit' (features/blit-test, removed on 2026-09-29, last present at commit c28c4dc)",
    "b292a64855975584dda5fe3fb282103bfde77f7f7237ca9945ac4b5442dae859": "direct-select + fast LCD paths, 'v1.4 tbenr fast' (features/fast-lcd/build/flash_fastlcd.bin)",
    "deada16ae67023e7fd9bb5c9668dc5a77f35b5738a19350ac138cd06470f86f1": "fast-lcd + House Numerals home and volume page, 'v1.4 tbenr hn' (features/house-numerals/build/flash_house_numerals.bin)",
    "2819e0b0f935f93012fd88d9799b6efcdd253c04269375a0d1acbb52965d787f": "fast-lcd + House Numerals v2 (200 ms wipe after the volume write, none while the unmute countdown runs), 'v1.4 tbenr hn2' (features/house-numerals/build/flash_house_numerals.bin)",
    "2c4809ab470ba0d161c460ffa69ac57fc5b54f42536c2fdbc2077fad00b920b6": "fast-lcd + House Numerals v3 (wipe also on Bluetooth and no-signal inputs, counts the unmute countdown during it), 'v1.4 tbenr hn3' (features/house-numerals/build/flash_house_numerals.bin)",
    "86aacb8be3f2d811a3bacab3c4316800eed582f07a3682943016ee82e0436623": "fast-lcd + House Numerals v4 (non-blocking eased wipes in and out of the volume page, text painter), 'v1.4 tbenr hn4' (features/house-numerals/build/flash_house_numerals.bin)",
    "5eddb6df9dc63b15a4cfaa920ba2bb745eaf14bec1a0f2b89e14d2514834bf8d": "fast-lcd + House Numerals v4.1 (edge drawn before the band, mid-exit stock redraws fixed), 'v1.4 tbenr hn4.1' (features/house-numerals/build/flash_house_numerals.bin)",
    "510fd1385bc7f56271b40820a6e1f71e689c87eeb04b9017646d265e8e79abc2": "fast-lcd + House Numerals v5 (the mock's home screen in its own typefaces), 'v1.4 tbenr hn5' (features/house-numerals/build/flash_house_numerals.bin)",
    "7b74e95069b9dfac5affae2d08122158502fdd771ba8abff0ce5b3f3f6139d0a": "fast-lcd + House Numerals v6 (hn5 with larger volume, tags and status line from layout.json), 'v1.4 tbenr hn6' (features/house-numerals/build/flash_house_numerals.bin)",
    "8f0ab9b208ebe95519c31319e9db08501c7f910aa6766746031e35bfae67df7d": "fast-lcd + House Numerals v6.1 (hn6 + fix-auto-off: Dimmer Auto OFF armed after power-on), 'v1.4 tbenr hn6.1' (features/house-numerals/build/flash_house_numerals.bin)",
    "41ce98074fcedf7f18497b856c26aea4d55f92660584c38f70273fb882250015": "fast-lcd + House Numerals v7 (hn6.1 with new sizes: status 28, name 54, tags 16; name and status in separate exit steps), 'v1.4 tbenr hn7' (features/house-numerals/build/flash_house_numerals.bin)",
    "f9b5d14d39a2437e5a7b92089101eb9c71e166df5fb37960abb370ebf420eb01": "direct-select + Auto OFF armed after power-on (AO300 PRO V1.2 fix), 'v1.4 tbenr aof1' (features/fix-auto-off/build/flash_fixautooff.bin)",
    "122a963c35cf4d64e01e8534b301e4d86e2d1b74a336e24e15a9e19b18bcebcd": "fast-lcd + House Numerals v8 (hn7 with the mock's volume page: name, status, VOL, 84-px number, 288-px line, dB caption, max 60; rounded tag corners; reddish status without a signal), 'v1.4 tbenr hn8' (features/house-numerals/build/flash_house_numerals.bin)",
    "b45331a8b812ed583daa6d914c905ad147b9713552c5da09ab03f67001b69916": "fast-lcd + House Numerals v9 (hn8 with the volume page's number roll and the spring on the position line; uk_text row clip, tick driver serves the re-mute request itself), 'v1.4 tbenr hn9' (features/house-numerals/build/flash_house_numerals.bin)",
    "45c22bf1faf01ccd3e103da0f90094cb791d5e691750d73fbbdb4f6f5b176a46": "fast-lcd + House Numerals v10 (hn9 with the mock's cubic ease on both wipes, 32 ticks each way), 'v1.4 tbenr hn10' (features/house-numerals/build/flash_house_numerals.bin)",
    "59d33243e749be8c7f699f16f8480c4bc6689e21d7ffd40b751ac85274ee1fd3": "direct-select + corrected stock texts (HDMI ARC without a link: 'Disconnected' for 'No Connected'), 'v1.4 tbenr str1' (features/strings/build/flash_strings.bin)",
    "89a6ed991e16b810a6bf3f0be6065075d08ab8815285589fe6d03d8b72b16a60": "fast-lcd + House Numerals v10.1 (hn10 with the status tint fix: only the status loader's own text is reddish, so an input's placeholder after Source is grey; strings included: 'Disconnected' on ARC), 'v1.4 tbenr hn10.1' (features/house-numerals/build/flash_house_numerals.bin)",
    "9b7e8b930d0b9f038d1996445e888ae08db4e928e2ec6755acb2564113912046": "direct-select v2 (a direct command for the input already selected is ignored, no re-initialisation), 'v1.4 tbenr ds2' (features/direct-select/build/flash_patched.bin)",
    "6d186a817762b8d705f75ffe178089483e4584fc01ebe55884fbb88b114cec7d": "direct-select v2 + fast LCD paths, 'v1.4 tbenr fast2' (features/fast-lcd/build/flash_fastlcd.bin)",
    "f1e4ef1c6bf9a75d8eb4bd252f423611662127c52b770ab5581eaa32077246aa": "direct-select v2 + Auto OFF armed after power-on (AO300 PRO V1.2 fix), 'v1.4 tbenr aof2' (features/fix-auto-off/build/flash_fixautooff.bin)",
    "6050a846a6153f5a2c1fa319260bee831763057e4ab15a3297659144bcfd382a": "fast-lcd fast2 + House Numerals v11 (hn10 on direct-select v2: same-input direct command ignored; without hn10.1's fixes), 'v1.4 tbenr hn11' (features/house-numerals/build/flash_house_numerals.bin)",
    "472184f144181062ae4fb78c8290e8f56708514575751d6e7476307bdf7fb3bf": "direct-select v2 + corrected stock texts ('Disconnected' on ARC), 'v1.4 tbenr str2' (features/strings/build/flash_strings.bin)",
    "3aa0f2d68351486a0746eaa9c4473ccf4184b68fd25839766ad9706a1e354d60": "fast-lcd fast2 + House Numerals v11.1 (hn10.1 on direct-select v2: status tint fix, strings, same-input direct command ignored), 'v1.4 tbenr hn11.1' (features/house-numerals/build/flash_house_numerals.bin)",
    "30c1e6fe785dc725037e5925d53f5b82305618037532b4a0cd7397a0774f560b": "stock + fast LCD paths only (the flattened graph: no direct-select in it), 'v1.4 tbenr fast3' (features/fast-lcd/build/flash_fastlcd.bin)",
    "1fb644707c1ce4d59760f2e37a288903b7eb622fefe4969f09af6027856858ff": "stock + Auto OFF armed after power-on only (AO300 PRO V1.2 fix), 'v1.4 tbenr aof3' (features/fix-auto-off/build/flash_fixautooff.bin)",
    "6c5611ad8985f599877793e81c90b1e37b0eb352140878caf85d037a9004454d": "stock + corrected stock texts only ('Disconnected' on ARC), 'v1.4 tbenr str3' (features/strings/build/flash_strings.bin)",
    "5f406b5d828965a59a0773af4f62879a4749ae2e61a264e5ed2378765e3f3dc5": "fast-lcd fast3 + House Numerals v12 (hn11.1 with direct-select linked in as a fix instead of stacked under fast-lcd; same behaviour), 'v1.4 tbenr hn12' (features/house-numerals/build/flash_house_numerals.bin)",
    "50ad41194c00b4265c8c9b297b821818d088ae42c0c123afa56c68347de36a27": "stock + start-volume only (volume at power-on capped: speakers 25, headphones 20), 'v1.4 tbenr sv1' (features/start-volume/build/flash_startvolume.bin)",
    "e91e3a208841a11ecf54aee94a4c6e5b676529e0572117fdb9dec8553d2d99e1": "fast-lcd fast3 + House Numerals v13 (hn12 + start-volume: volume at power-on capped, speakers 25, headphones 20), 'v1.4 tbenr hn13' (features/house-numerals/build/flash_house_numerals.bin)",
    "1e5691d899f6c7b091fa746b53ed2ee11f58f98b686d75e87232b5b3faf7ecc0": "fast-lcd fast3 + House Numerals, the MUTE state's branch build (hn12 with the volume page's MUTE state: the mute key shows the page, also when it is open; without start-volume). Its RESET page also says 'v1.4 tbenr hn13', like e91e3a20: tell them apart by this sha; hn14 is the two merged",
    "3bef4bb7c66ab6ccd4a795569b6d8003500c070def939a4f5a956ac2b01f8161": "fast-lcd fast3 + House Numerals v14 (hn13 with the volume page's MUTE state: the mute key shows the page, also when it is open), 'v1.4 tbenr hn14' (features/house-numerals/build/flash_house_numerals.bin)",
    "e2075861e79451ca18f7923aa76d4238eb11cb43d135945f767cec839d805e65": "stock + fix-volume-pop only (volume keys on Optical/Coaxial without a signal leave the mute pins and the NJW1194 alone), 'v1.4 tbenr vp1' (features/fix-volume-pop/build/flash_fixvolumepop.bin)",
    "d39d321c88127a9af0f5ed313b957f7e3483c6edc9edac576fb86ae73f3dc0d3": "fast-lcd fast3 + House Numerals, the pop fixes' first branch build (hn13 + fix-volume-pop: no pop on the first volume key on Optical/Coaxial without a signal; without the MUTE state). Its RESET page also says 'v1.4 tbenr hn14', like 3bef4bb7: tell them apart by this sha; hn16 has both",
    "693bdef6b17a2f8cec93c40a0d138d826fb7061463f51dadcc2c52d8bbada279": "stock + fix-menu-input only (an input chosen in the menu is switched as the Source key switches it: no P4.0 supply cycle, no second chip setup), 'v1.4 tbenr mi1' (features/fix-menu-input/build/flash_fixmenuinput.bin)",
    "7a4af92f44d7c22a775706b33d28133299c0937b7424e3a73b444dda4f3054e6": "fast-lcd fast3 + House Numerals v15, the pop fixes' second branch build (hn13 + fix-volume-pop + fix-menu-input: no supply cycle and no pop on an input change through the menu; without the MUTE state), 'v1.4 tbenr hn15'; hn16 is this merged with the MUTE state",
    "7ee88992ee9a5bb3cbf8f4cb5ccc3896c376a8c2be19931e549f22e2d5dbea5a": "fast-lcd fast3 + House Numerals v16 (hn14 + fix-volume-pop + fix-menu-input: the MUTE state, start-volume and both pop fixes in one image), 'v1.4 tbenr hn16' (features/house-numerals/build/flash_house_numerals.bin)",
    "782eb5089f5cd03881faedee37b32840179b283663e0044ada933b1c47323e8a": "fast-lcd fast3 + House Numerals v17 (hn16 with the stock big font's area reclaimed: every big text is the theme's, 5015 bytes of its fonts at 0x6A23..0x7DB9, image ends at 0xDD19), 'v1.4 tbenr hn17' (features/house-numerals/build/flash_house_numerals.bin)",
    "24bd8f2e9b41360ee8c29cbe2ab61aeab2f801b1d307947120a654fa45f240f0": "stock + probe pr1 (NEC 0x16 on the home page dumps the I2C address scan, the expander, receiver and clock-generator registers, the ports and RAM over the header at 115200 baud; read-only) + the six fixes, 'v1.4 tbenr pr1' (flashed 2026-10-05, superseded by pr2)",
    "280c3f996fe20b95050f9a9d2e0adecbf1520ce9a5f9f670d2108fc2dff98284": "stock + probe pr2 (the same dump on the remote's FN button, NEC 0x08, instead of 0x16) + the six fixes, 'v1.4 tbenr pr2' (flashed 2026-10-05, thirteen dumps; superseded by pr3)",
    "d0146e353fa8ae5efc1ab6a456de3f72b7e13b9efde9d1ddddee83bf55719e08": "stock + auto-switch stage 1 as1 (to HDMI when the TV comes on, to Bluetooth when a phone connects, from any input while the selected input is silent; one receiver register written, the calculator target) + the six fixes, 'v1.4 tbenr as1' (flashed 2026-10-05, the TV wake confirmed; superseded by as2)",
    "d6f91fcf98e07ce55790ae5efd2445651d1c42a5d7da54a3b12ee42390bc233a": "stock + auto-switch stage 1 as2 (as1 with HDMI the only enabled source: the Bluetooth module is off on the other inputs, so a phone cannot connect there) + the six fixes, 'v1.4 tbenr as2' (features/auto-switch/build/flash_autoswitch.bin)",
    "b4836c461f554ae2ed707bdfc48e7c9fb00fa5692f2f7a44f4757504d3bf3776": "stock + probe pr3 (pr2 plus the FS line: the receiver's rate calculator pointed at each of its eight ports and restored, the probe's one register write) + the six fixes, 'v1.4 tbenr pr3' (features/probe/build/flash_probe.bin)",
    "38a1499efef590147b87393aba62314c4d5de43f1019d9c17729136862e2ae1d": "fast-lcd fast3 + Phosphor Panel pp1 (study 2 of the UI mock: the VFD-style home with a dot-matrix name and a row of lamps, the seven-segment volume page with afterglow and a bar, sequenced fades between them; the stock big font's area holds its data) + the six fixes, 'v1.4 tbenr pp1' (flashed 2026-10-10, works; superseded by pp2)",
    "f5ca8bba9048d0daacb459299f2565f5fb043751be72177e80c6947d1e39098e": "fast-lcd fast3 + Phosphor Panel pp2 (pp1 with each name glyph placed on the dot grid where it keeps the most ink: the left edge of O and C no longer cut) + the six fixes, 'v1.4 tbenr pp2' (features/phosphor-panel/build/flash_phosphor_panel.bin; flashed 2026-10-10, confirmed)",
    "425460c3516a0bb14a7c31bb8983034de576b7633b59a8a9084cd92d5d87c418": "direct-select v3 (ds2 plus idempotent power over IR: NEC 0x16 powers on only from standby, 0x17 powers off only when on, from a menu page too), 'v1.4 tbenr ds3' (features/direct-select/build/flash_patched.bin)",
    "b3455f2b9dfd1f871d9fb03e632a8f699b4df2d1586930631c9413fc0aa802fd": "fast-lcd fast3 + House Numerals v18 (hn17 on direct-select v3: idempotent power commands 0x16/0x17), 'v1.4 tbenr hn18' (features/house-numerals/build/flash_house_numerals.bin)",
    "273edf8fbe362c78239e3e6d28fafdfbb828730034d24cc28a0bec6a6e5cfd35": "fast-lcd fast3 + Phosphor Panel pp3 (pp2 on direct-select v3: idempotent power commands 0x16/0x17) + the six fixes, 'v1.4 tbenr pp3' (features/phosphor-panel/build/flash_phosphor_panel.bin)",
    "aa43a3e5df82225646f4cdd0a4682e78f9cd75a3ef973f112a8715f624ca14f2": "stock + auto-switch stage 1 as3 (as2 on direct-select v3: idempotent power commands 0x16/0x17) + the six fixes, 'v1.4 tbenr as3' (features/auto-switch/build/flash_autoswitch.bin)",
    "e4a5bd1ed73bf35cf85ea03f3e4a4c87cbe1e9774ee6912cb14af51aed6c086e": "stock + probe pr4 (pr3 on direct-select v3: idempotent power commands 0x16/0x17; the dump stays on the FN button) + the six fixes, 'v1.4 tbenr pr4' (features/probe/build/flash_probe.bin)",
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
    ap.add_argument("-p", "--port", required=True, help="serial device, e.g. /dev/cu.usbserial-10, or a pyserial URL like rfc2217://host:4000")
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
