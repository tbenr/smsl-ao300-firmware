#!/usr/bin/env python3
"""Emulator test for start-volume (a cap on the volume at power-on, set at build time).

  * the image differs from stock only in the hook's target, the version pointer and the
    appended code;
  * the hook: post_power_on's `lcall audio_chips_init` (0x5596) reaches audio_chips_init with
    g_volume (0x31) = min(volume, SPEAKER_LIMIT) and g_volume_hp (0x52) = min(volume,
    HEADPHONE_LIMIT), for every volume 0..60, and with nothing else changed;
  * the config: each limit works alone, and a disabled one leaves its volume as stock does
    (all four combinations, on images built in memory); an out-of-range value stops the build;
  * all 256 NEC commands through the IR translate routine (0x5D10) behave as in stock;
  * whole firmware from reset with the real timer ISRs, stock and patched side by side, on an
    EEPROM model (reads, writes and erases of the stock IAP routines), so a cold power-up
    turns the amp on by itself as the real one does:
      - stored volumes above the limits: the patched amp never sends the NJW1194 a volume
        louder than the limit, on speakers and on headphones; stock sends the stored one;
      - the capped volume is what the stock save then stores;
      - stored volumes at or below the limits: the same audio events as stock;
      - Vol+ after power-on goes above the limit (the cap acts at power-on only);
      - standby and on again: back at the limit; stock keeps the volume.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
from emu8051 import Emu8051  # noqa: E402
from ao300 import Amp, CLOCK_HZ, TICK, NEC_POWER, NEC_VOL_UP  # noqa: E402
import build_patch as bp     # noqa: E402
import features              # noqa: E402  (tools/patch, on the path through build_patch)
from asm51 import Asm        # noqa: E402

INTEGRATION = True           # `emu_test.py --in <feature>`: the cap's promises in that image
import start_volume as sv    # noqa: E402

TEST_IMG = bp.OUT_IMAGE
BASE_IMG = bp.BASE_IMAGE
HOOK_SITE = 0x5596                   # post_power_on: lcall audio_chips_init
HOOK_RETURN = 0x5599
AUDIO_CHIPS_INIT = 0x50D1
VOLUME_APPLY = 0x4DDC                # R7 = g_volume; uses g_volume_hp when the output is headphones
APPLY_TAIL = 0x5640                  # input_apply, needs real hardware
EEPROM_READ_DATA = 0x5970            # eeprom_read: mov R7,IAP_DATA
EEPROM_WRITE = 0x58AF                # R6:R7 address, R5 byte
EEPROM_ERASE = 0x59D0                # R6:R7 address
VOL_TABLE = 0x9289                   # NJW1194 code = table[60 - step]
VOL_MAX = 60
MUTE_CODE = 0xFF
EE_VOLUME, EE_OUTPUT, EE_VOLUME_HP = 0x0201, 0x0203, 0x0209
# what a used amp holds: magic and power-on flag (sector 0), the settings record (sector 0x0200)
FACTORY = {0x0001: 0x45, 0x0002: 1, 0x0201: 20, 0x0202: 1, 0x0203: 1, 0x0204: 0, 0x0205: 1, 0x0206: 9,
           0x0207: 9, 0x0208: 1, 0x0209: 20, 0x020A: 0, 0x020B: 1, 0x020C: 1}

fails = []


def check(name, ok, detail=""):
    print("  %-66s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def capped(volume, limit):
    return volume if limit is sv.DISABLED else min(volume, limit)


def code_of(image, step):
    return image[VOL_TABLE + VOL_MAX - step]


def image_diff():
    print("\nImage diff vs stock")
    a = open(BASE_IMG, "rb").read()
    b = open(TEST_IMG, "rb").read()
    changed = [i for i in range(len(a)) if a[i] != b[i]]
    check("only the hook target (0x5597, 0x5598) and version pointer changed",
          {0x5597, 0x5598} <= set(changed) <= {0x22CB, 0x22CD, 0x5597, 0x5598},
          str(["%04X" % i for i in changed]))
    check("gap up to 0x%04X is 0xFF" % bp.CODE_ADDR, all(x == 0xFF for x in b[len(a):bp.CODE_ADDR]))
    check("hook is lcall sv_limit",
          b[0x5596] == 0x12 and b[0x5597:0x5599] == bytes([bp.CODE_ADDR >> 8, bp.CODE_ADDR & 0xFF]))


def build_with(speaker, headphone):
    """Stock plus the fix with these limits, in memory (no version string)."""
    img = bytearray(open(BASE_IMG, "rb").read())
    addr, orig, op, label = sv.HOOK
    assert img[addr:addr + 3] == orig
    a = Asm(bp.CODE_ADDR)
    sv.emit(a, speaker, headphone)
    code = a.resolve()
    img += b"\xFF" * (bp.CODE_ADDR - len(img)) + code
    t = a.labels[label]
    img[addr:addr + 3] = bytes([op, t >> 8, t & 0xFF])
    return bytes(img)


def at_hook(image, speaker, headphone, output):
    """Run the hook site up to its return; audio_chips_init is recorded, not run."""
    e = Emu8051(image)
    e.sfr[0x81] = 0x88
    e.iram[0x31], e.iram[0x52], e.iram[0x2B] = speaker, headphone, output
    e.iram[0x4F], e.iram[0x45] = 1, 1
    e.seen = None

    def init(em):
        em.seen = (em.iram[0x31], em.iram[0x52])
        em.ret()
    e.hooks[AUDIO_CHIPS_INIT] = init
    e.pc = HOOK_SITE
    e.run(HOOK_RETURN, 10_000)
    return e


def hook_cases(image, speaker_limit, headphone_limit, label):
    stock = open(BASE_IMG, "rb").read()
    wrong, side = [], []
    for output in (1, 2):
        for v in range(VOL_MAX + 1):
            for spk, hp in ((v, VOL_MAX - v), (v, v)):
                t = at_hook(image, spk, hp, output)
                b = at_hook(stock, spk, hp, output)
                if t.seen != (capped(spk, speaker_limit), capped(hp, headphone_limit)):
                    wrong.append((spk, hp, t.seen))
                if b.seen != (spk, hp):
                    wrong.append(("stock", spk, hp, b.seen))
                others = [i for i in range(256) if i not in (0x31, 0x52) and b.iram[i] != t.iram[i]]
                if others or b.sfr[0x81] != t.sfr[0x81] or b.xram != t.xram:
                    side.append((spk, hp, others))
    check("%s: audio_chips_init sees min(volume, limit), 0..60 both outputs" % label, not wrong, str(wrong[:3]))
    check("%s: other RAM, XDATA and SP as stock" % label, not side, str(side[:3]))


def hook_test():
    print("\nThe hook: post_power_on's lcall audio_chips_init at 0x5596")
    hook_cases(open(TEST_IMG, "rb").read(), sv.SPEAKER_LIMIT, sv.HEADPHONE_LIMIT,
               "built image (%s / %s)" % (sv.SPEAKER_LIMIT, sv.HEADPHONE_LIMIT))


def config_test():
    print("\nThe config: two independent limits, each a level or DISABLED")
    D = sv.DISABLED
    for spk, hp in ((25, 20), (25, D), (D, 20), (D, D), (10, 40), (0, 60), (60, 0)):
        hook_cases(build_with(spk, hp), spk, hp, "speakers %s, headphones %s" % (spk, hp))
    mine, built = build_with(sv.SPEAKER_LIMIT, sv.HEADPHONE_LIMIT), open(TEST_IMG, "rb").read()
    check("built image carries the config's code (%s / %s)" % (sv.SPEAKER_LIMIT, sv.HEADPHONE_LIMIT),
          mine[bp.CODE_ADDR:] == built[bp.CODE_ADDR:len(mine)] and mine[HOOK_SITE:HOOK_RETURN] == built[HOOK_SITE:HOOK_RETURN])
    sizes = {k: len(build_with(*k)) for k in ((25, 20), (25, D), (D, 20), (D, D))}
    check("a disabled side emits no code", sizes[(D, D)] < sizes[(25, D)] == sizes[(D, 20)] < sizes[(25, 20)],
          str(sorted(v - bp.CODE_ADDR for v in sizes.values())))
    for bad in ((61, 20), (25, -1), (25, 61), ("25", 20), (25.0, 20), (True, 20)):
        try:
            build_with(*bad)
            stopped = False
        except SystemExit as ex:
            stopped = "start-volume" in str(ex)
        check("limits %r stop the build with a message" % (bad,), stopped)


def make(img_path, cmd, power, page):
    e = Emu8051(open(img_path, "rb").read())
    e.sfr[0x81] = 0x88                       # SP as set by the firmware
    e.sfr[0xA8] = 0x80                       # EA on, as in normal running
    e.iram[0x6A] = cmd
    e.iram[0x4F] = power
    e.iram[0x45] = page
    e.iram[0x47] = 0x99
    e.iram[0x2B] = 1
    e.iram[0x31], e.iram[0x52] = 55, 45
    e.iram[0x48], e.iram[0x49] = 0xFF, 0xFF  # theme text colour (white theme)
    e.applied = None

    def apply(em):
        em.applied = em.iram[0x47]
        em.ret()
    e.hooks[APPLY_TAIL] = apply
    return e


def sweep():
    print("\nAll 256 NEC commands vs the stock image")
    diffs = 0
    for power, page in ((1, 1), (0, 1), (1, 0), (1, 2), (1, 3)):
        for cmd in range(256):
            r = []
            for img in (BASE_IMG, TEST_IMG):
                e = make(img, cmd, power, page)
                e.call(0x5D10, max_steps=10_000)
                r.append((e.R(7), e.iram[0x47], e.applied, e.iram[0x6F], e.iram[0x31], e.iram[0x52],
                          e.lcd.pixels))
            if r[0] != r[1]:
                diffs += 1
                print("    cmd 0x%02X power %d page %d: %s vs %s" % (cmd, power, page, r[0], r[1]))
    check("identical results for every command, power, page", diffs == 0, "(%d diffs)" % diffs)


class Run:
    """One amp from reset on an EEPROM model: the stock IAP routines read, write and erase
    `eeprom` (offset -> byte, erased = 0xFF). Every volume_apply call is logged with the step
    it will send; NJW1194 volume codes come from amp.events."""

    def __init__(self, image, eeprom):
        self.image = image
        self.eeprom = dict(eeprom)
        self.amp = Amp(image)
        e = self.amp.e
        self.applied = []                    # (time, step) per volume_apply call

        def read(em):
            em.sfr[0xC2] = self.eeprom.get((em.sfr[0xC3] << 8) | em.sfr[0xC4], 0xFF)

        def write(em):
            self.eeprom[(em.R(6) << 8) | em.R(7)] = em.R(5)

        def erase(em):
            sector = ((em.R(6) << 8) | em.R(7)) & ~0x1FF
            for k in [k for k in self.eeprom if k & ~0x1FF == sector]:
                del self.eeprom[k]

        def apply(em):
            step = em.R(7) if em.iram[0x2B] == 1 else em.iram[0x52]
            self.applied.append((em.cycles / CLOCK_HZ, step))
        e.hooks[EEPROM_READ_DATA] = read
        e.hooks[EEPROM_WRITE] = write
        e.hooks[EEPROM_ERASE] = erase
        e.hooks[VOLUME_APPLY] = apply
        self.amp.boot(8.0)                   # cold power-up: on by itself, unmuted, settings saved

    @property
    def volumes(self):
        return self.amp.e.iram[0x31], self.amp.e.iram[0x52]

    def steps(self, since=0.0):
        return [s for t, s in self.applied if t >= since]

    def loudest_code(self, since=0.0):
        """The lowest (loudest) code sent to the NJW1194 volume registers; mute (0xFF) if none."""
        codes = [int(regs.split("R5=")[1][:2], 16) for c, name, regs in self.amp.events
                 if name == "njw1194_write" and c / CLOCK_HZ >= since
                 and int(regs.split("R7=")[1][:2], 16) >> 4 in (0, 1)]       # select 0, 1: the two volume registers
        return min(codes) if codes else MUTE_CODE

    def keys(self, cmd, n, gap=0.3):
        for _ in range(n):
            self.amp.press(cmd)
            self.amp.wait(gap)

    def standby_and_on(self):
        self.amp.wait(4.0)                   # the volume page closes, settings are saved
        self.amp.press(NEC_POWER)
        self.amp.wait(3.0)
        was_off = not self.amp.powered
        t = self.amp.t
        self.amp.press(NEC_POWER)
        self.amp.wait(8.0)
        return was_off, t


def stored(volume, volume_hp, output=1):
    ee = dict(FACTORY)
    ee[EE_VOLUME], ee[EE_VOLUME_HP], ee[EE_OUTPUT] = volume, volume_hp, output
    return ee


def power_on_cases(image, label, limits):
    """Cold power-up and standby wake with stored volumes above the limits, on one image."""
    spk_limit, hp_limit = limits
    for output, name, limit, vol in ((1, "speakers", spk_limit, 55), (2, "headphones", hp_limit, 45)):
        want = capped(vol, limit)
        r = Run(image, stored(55, 45, output))
        check("%s, %s: on by itself after the cold power-up" % (label, name), r.amp.powered and r.amp.page == 1)
        check("%s, %s: volumes %d / %d" % (label, name, capped(55, spk_limit), capped(45, hp_limit)),
              r.volumes == (capped(55, spk_limit), capped(45, hp_limit)), str(r.volumes))
        check("%s, %s: every volume applied is step %d" % (label, name, want),
              r.steps() and set(r.steps()) == {want}, str(r.steps()))
        check("%s, %s: loudest NJW1194 code is step %d's (0x%02X)" % (label, name, want, code_of(image, want)),
              r.loudest_code() == code_of(image, want), "(0x%02X)" % r.loudest_code())
        check("%s, %s: the save stores %d / %d" % (label, name, capped(55, spk_limit), capped(45, hp_limit)),
              (r.eeprom.get(EE_VOLUME), r.eeprom.get(EE_VOLUME_HP)) == (capped(55, spk_limit), capped(45, hp_limit)),
              str((r.eeprom.get(EE_VOLUME), r.eeprom.get(EE_VOLUME_HP))))

        # Vol+ five times: the cap is at power-on only
        r.keys(NEC_VOL_UP, 5)
        up = min(want + 5, VOL_MAX)
        check("%s, %s: five Vol+ reach %d" % (label, name, up), r.volumes[output - 1] == up, str(r.volumes))
        was_off, t = r.standby_and_on()
        back = capped(up, limit)
        check("%s, %s: standby, on again: %d" % (label, name, back),
              was_off and r.amp.powered and r.volumes[output - 1] == back and set(r.steps(t)) == {back},
              "%s %s" % (r.volumes, r.steps(t)))
        check("%s, %s: after the wake the loudest code is step %d's" % (label, name, back),
              r.loudest_code(t) == code_of(image, back), "(0x%02X)" % r.loudest_code(t))


def scenario_capped():
    print("\nFull firmware, stored volumes 55 / 45: stock restores them, the patch caps them")
    stock = open(BASE_IMG, "rb").read()
    power_on_cases(stock, "stock", (sv.DISABLED, sv.DISABLED))
    power_on_cases(open(TEST_IMG, "rb").read(), "patch", (sv.SPEAKER_LIMIT, sv.HEADPHONE_LIMIT))


def low(limit, below):
    return VOL_MAX - below if limit is sv.DISABLED else max(limit - below, 0)


def scenario_below():
    print("\nFull firmware, volumes that stay at or below the limits: identical to stock")
    # stored at the limit; two below it and raised to it by two Vol+; well below
    for below, presses in ((0, 0), (2, 2), (7, 2)):
        vols = low(sv.SPEAKER_LIMIT, below), low(sv.HEADPHONE_LIMIT, below)
        for output in (1, 2):
            runs = [Run(open(img, "rb").read(), stored(vols[0], vols[1], output)) for img in (BASE_IMG, TEST_IMG)]
            for r in runs:
                r.keys(NEC_VOL_UP, presses)
                r.standby_and_on()
            b, f = runs
            # the hook's own clocks can move a tick-driven action into the next 10 ms tick
            near = len(b.amp.events) == len(f.amp.events) and all(
                n1 == n2 and v1 == v2 and abs(c1 - c2) < 2 * TICK for (c1, n1, v1), (c2, n2, v2)
                in zip(b.amp.events, f.amp.events))
            what = "stored %d / %d, %d Vol+, output %d" % (vols[0], vols[1], presses, output)
            check("%s: same audio events in order" % what, near,
                  "(%d vs %d events)" % (len(b.amp.events), len(f.amp.events)))
            check("%s: same volumes, EEPROM and screen" % what,
                  b.volumes == f.volumes and b.eeprom == f.eeprom and b.amp.lcd.gram == f.amp.lcd.gram,
                  "%s %s" % (b.volumes, f.volumes))


def integration(img_path, label):
    """What the cap promises in any image that contains it, on that image alone (run_tests.py runs
    this as "start-volume in <feature>" for every image that includes the fix)."""
    print("\nIntegration, %s: limits %s / %s at cold power-up and after standby"
          % (label, sv.SPEAKER_LIMIT, sv.HEADPHONE_LIMIT))
    image = open(img_path, "rb").read()
    limits = (sv.SPEAKER_LIMIT, sv.HEADPHONE_LIMIT)
    power_on_cases(image, "image", limits)

    # the home screen after a capped wake is the home screen of an amp that never went above the limit
    at = low(sv.SPEAKER_LIMIT, 0), low(sv.HEADPHONE_LIMIT, 0)
    loud, quiet = Run(image, stored(*at)), Run(image, stored(*at))
    loud.keys(NEC_VOL_UP, 5)
    for r in (loud, quiet):
        r.standby_and_on()
        r.amp.wait(4.0)
    check("home screen after a capped wake = home screen of an amp left at the limit",
          loud.amp.page == 1 and quiet.amp.page == 1 and loud.amp.lcd.gram == quiet.amp.lcd.gram
          and loud.volumes == quiet.volumes, "%s %s" % (loud.volumes, quiet.volumes))


def finish():
    print("\n" + ("ALL PASS" if not fails else "FAILURES: %s" % ", ".join(fails)))
    sys.exit(1 if fails else 0)


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--in":        # run_tests.py: this fix inside another image
        integration(features.image(sys.argv[2]), sys.argv[2])
        finish()
    image_diff()
    hook_test()
    config_test()
    sweep()
    scenario_capped()
    scenario_below()
    integration(TEST_IMG, "the standalone image")
    finish()


if __name__ == "__main__":
    main()
