#!/usr/bin/env python3
"""Trace what the firmware does on its buses and pins, from reset through every setting.

    python3 tools/emu/bus_trace.py                 the stock image, summary only
    python3 tools/emu/bus_trace.py --steps         also what each key press or signal change did
    python3 tools/emu/bus_trace.py --image <bin>   another image (the hooks are stock addresses,
                                                   which every feature image keeps)

Runs the whole firmware on `Amp` with the I2C slave model (i2c.py), so the chips answer.
The tour: power on, every input signal the firmware polls (USB activity and XMOS
messages, the receiver's lock pin and rate register, the expander inputs), all six
inputs, Output, the eight EQ presets, the five filters, volume, the remote's other keys,
standby. It prints, per I2C device, every register written with the values it took, every
register read, the words sent to the NJW1194, and every MCU pin that changed. docs/bus-map.md
is written from this output and from the disassembly.

Settings come from an erased EEPROM (the emulator's IAP reads return what the SFR holds),
so the volume and tone values are not the amp's; the registers and bits are.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
from ao300 import Amp, CLOCK_HZ                 # noqa: E402
from i2c import I2CBus                          # noqa: E402

NEC_POWER, NEC_UP, NEC_BACK, NEC_ENTER, NEC_DOWN, NEC_SOURCE = 0x01, 0x02, 0x03, 0x04, 0x06, 0x07
MENU_PAGE, HOME_PAGE, CURSOR = 3, 1, 0x17        # menu item k opens page k + 4
ITEM_OUTPUT, ITEM_EQ, ITEM_FILTER = 1, 2, 5
EXP, DIR = 0xB0, 0x80
# port SFR -> (name, bits to log): not the LCD strobes and data, the NJW latch, SDA, SCL
PORTS = {0x80: ("P0", 0x57), 0xA0: ("P2", 0xFE), 0xB0: ("P3", 0x7F), 0xC0: ("P4", 0xFD), 0xC8: ("P5", 0xFF)}


class Tour:
    def __init__(self, image):
        self.amp = Amp(image)
        self.bus = I2CBus(self.amp)
        self.pins, self.steps, self.marks = [], [], [0, 0, 0]
        e = self.amp.e
        for sfr, (name, mask) in PORTS.items():
            prev = e.sfr_watch.get(sfr)
            e.sfr_watch_mask[sfr] = mask

            def watch(em, old, new, name=name, mask=mask, prev=prev):
                if prev:
                    prev(em, old, new)
                for b in range(8):
                    if (old ^ new) & mask & (1 << b):
                        self.pins.append((em.cycles, "%s.%d=%d" % (name, b, (new >> b) & 1)))
            e.sfr_watch[sfr] = watch

    def step(self, name, key=None, seconds=3.0):
        amp = self.amp
        if key is not None:
            amp.press(key)
        amp.wait(seconds)
        ev = [(t[0], I2CBus.format(t)[11:]) for t in self.bus.log[self.marks[0]:]]
        ev += [(c, "%s %s" % (n, d)) for c, n, d in amp.events[self.marks[1]:] if n in ("njw1194_write", "input_set_hw")]
        ev += self.pins[self.marks[2]:]
        self.marks = [len(self.bus.log), len(amp.events), len(self.pins)]
        self.steps.append((name, sorted(ev, key=lambda x: x[0])))

    def select(self, item, option, name):
        """Open the menu, enter item, move to option, confirm, return home."""
        e = self.amp.e
        self.step(None, NEC_ENTER, 0.8)
        for want, enter, wait in ((item, NEC_ENTER, 0.8), (option, NEC_ENTER, 3.0)):
            for _ in range(14):
                if e.iram[CURSOR] == want:
                    break
                self.step(None, NEC_DOWN if want > e.iram[CURSOR] else NEC_UP, 0.5)
            if e.iram[CURSOR] != want:
                raise SystemExit("%s: cursor %d, wanted %d" % (name, e.iram[CURSOR], want))
            self.step(name if want == option and enter == NEC_ENTER and wait == 3.0 else None, enter, wait)
        for _ in range(3):
            if self.amp.page == HOME_PAGE:
                break
            self.step(None, NEC_BACK, 1.0)


def tour(image):
    t = Tour(image)
    amp, sig = t.amp, t.bus.inputs
    t.step("reset, standby", None, 1.0)
    t.step("Power on (USB, nothing connected)", NEC_POWER, 9.0)
    amp.set_pin(0xC0, 5, 0)
    t.step("USB: P4.5 low")
    sig[(EXP, 1)] = 0x20
    t.step("USB: expander P1_5 high")
    sig[(EXP, 1)] = 0
    for fmt, rate in ((1, 1), (1, 5), (2, 1), (3, 2)):
        amp.e.iram[0x76], amp.e.iram[0x77], amp.e.iram[0x78] = fmt, rate, 0xFF     # as uart1_isr leaves them
        t.step("USB: XMOS message %d, %d" % (fmt, rate))
    amp.set_pin(0xC0, 5, 1)
    for name in ("Optical", "Coaxial"):
        t.step("Source: %s" % name, NEC_SOURCE, 4.0)
        amp.set_pin(0xC0, 2, 0)
        t.step("%s: P4.2 low (lock)" % name)
        for code in (0x08, 0x0F, 0x00):
            sig[(DIR, 0x39)] = code
            t.step("%s: receiver register 0x39 = %02X" % (name, code))
        amp.set_pin(0xC0, 2, 1)
        t.step("%s: P4.2 high" % name)
    t.step("Source: Bluetooth", NEC_SOURCE, 4.0)
    for bit in (1, 2, 3, 5, 6):
        sig[(EXP, 0)] = 1 << bit
        t.step("Bluetooth: expander P0_%d high" % bit)
    sig[(EXP, 0)], sig[(DIR, 0x38)], sig[(DIR, 0x39)] = 0x20, 0x09, 0x09
    t.step("Bluetooth: expander P0_5 high, receiver 0x38 and 0x39 = 09")
    t.step("Bluetooth: remote command 0x0E", 0x0E)
    sig[(EXP, 0)], sig[(DIR, 0x38)], sig[(DIR, 0x39)] = 0, 0, 0
    t.step("Source: HDMI", NEC_SOURCE, 4.0)
    sig[(EXP, 1)] = 0x10
    t.step("HDMI: expander P1_4 high", None, 4.0)
    sig[(EXP, 1)] = 0
    t.step("Source: AUX", NEC_SOURCE, 4.0)
    t.step("Source: USB", NEC_SOURCE, 4.0)
    t.select(ITEM_OUTPUT, 1, "Output: Headphones")
    t.step("Headphones: Vol+", 0x0A)
    t.select(ITEM_OUTPUT, 0, "Output: Speakers")
    for n, name in enumerate(("Direct", "Tone", "SDB", "Bass", "Super Bass", "Rock", "Soft", "Clear")):
        t.select(ITEM_EQ, n, "EQ: %s" % name)
    for n, name in enumerate(("FAST+LLatency", "FAST+PhComp", "SLOW+LLatency", "SLOW+PhComp", "NON+Sampling")):
        t.select(ITEM_FILTER, n, "Filter: %s" % name)
    t.step("Vol+", 0x0A)
    t.step("Vol-", 0x0B)
    for cmd in (0x09, 0x09, 0x08, 0x08, 0x05, 0x0E):
        t.step("Remote command 0x%02X" % cmd, cmd)
    t.step("Standby", NEC_POWER)
    return t


def summary(t):
    names = {0xB0: "0xB0 expander", 0x80: "0x80 digital receiver", 0xC0: "0xC0 clock generator", 0x62: "0x62 DAC"}
    written, read = {}, {}
    for cycle, site, kind, dev, reg, v, ok in t.bus.log:
        d = written if kind == "W" else read
        d.setdefault(dev, {}).setdefault(reg, []).append(v[1] if isinstance(v, tuple) and dev == 0x62 else v)
    for dev in sorted(set(written) | set(read)):
        print("\nI2C device %s" % names.get(dev, "0x%02X" % dev))
        for label, d in (("written", written), ("read", read)):
            for reg in sorted(d.get(dev, {})):
                vals = d[dev][reg]
                seen = list(dict.fromkeys(vals))
                print("  %s %s: %s  (%d transfers)" % (
                    label, ("%06X" if dev == 0x62 else "%02X") % reg, " ".join("%02X" % v for v in seen), len(vals)))
    print("\nNJW1194 words (select/address byte: data bytes seen)")
    njw = {}
    for c, n, d in t.amp.events:
        if n == "njw1194_write":
            f = dict(x.split("=") for x in d.split())
            njw.setdefault(f["R7"], []).append(f["R5"])
    for sel in sorted(njw):
        print("  %s: %s" % (sel, " ".join(dict.fromkeys(njw[sel]))))
    after_init = [p.split("=")[0] for c, p in t.pins if c > CLOCK_HZ // 10]      # not port_init's 0xFF
    print("\nMCU pins written after port_init (changes): %s" % "  ".join(
        "%s (%d)" % (p, after_init.count(p)) for p in sorted(set(after_init))))


def steps(t):
    for name, ev in t.steps:
        if name is None:
            continue
        print("\n--- %s" % name)
        count, first = {}, {}
        for c, s in ev:
            count[s] = count.get(s, 0) + 1
            first.setdefault(s, c)
        for s, c in first.items():
            print("  %9.3f  %s%s" % (c / CLOCK_HZ, s, "   (x%d)" % count[s] if count[s] > 1 else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--image", help="image to run (default: the stock image)")
    ap.add_argument("--steps", action="store_true", help="print what each step did")
    args = ap.parse_args()
    if args.image is None:
        import features
        args.image = features.image("stock")
    t = tour(open(args.image, "rb").read())
    if args.steps:
        steps(t)
    summary(t)


if __name__ == "__main__":
    main()
