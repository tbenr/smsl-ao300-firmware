#!/usr/bin/env python3
"""Differential test: the C core (CEmu8051) against the Python reference (PyEmu8051).

Run after any change to emu8051.py, cemu8051.py or core8051.c. Three parts, all
compared on the complete machine state (pc, clocks, steps, next tick, IRAM, SFRs,
XRAM, LCD pixels, command log and GRAM) plus every callback the emulator made:

  * every opcode, one instruction from random states: random memory, forced input
    pins, SFR watches (every write or masked), Timer0 ticks due now or soon, hooks
    at the pc (some of them return with ret()), an LCD window open for pixel data;
  * random programs of up to 3000 instructions from random states;
  * the firmware (stock image unless --image): boot from reset with the real Timer0
    ISR, Power, Vol+, Menu, Down, Source, Power off through ao300.Amp. The machine
    state is compared at every 10 ms tick, so a failure names the first tick that
    differs.

The Python side is slow, so the work is spread over worker processes (-j).
"""
import argparse
import hashlib
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from emu8051 import PyEmu8051           # noqa: E402
from cemu8051 import CEmu8051           # noqa: E402

STOCK = os.path.join(ROOT, "original", "extracted", "flash.bin")
PORTS = (0x80, 0x90, 0xA0, 0xB0, 0xC0, 0xC8, 0xE8)
WATCHABLE = PORTS + (0xD0, 0xE0, 0xF0, 0x81, 0x82, 0x83, 0xA8, 0x88)
SCENARIO = [(None, 1.0), (0x01, 6.0), (0x0A, 1.0), (0x03, 1.0), (0x06, 0.5), (0x07, 2.0), (0x01, 1.5)]


def state(e):
    lcd = e.lcd
    return (e.pc, e.cycles, e.steps, e._next_tick, bytes(e.iram), bytes(e.sfr), bytes(e.xram),
            lcd.pixels, list(lcd.log), list(lcd.gram) if lcd.pixels else None)


def make_case(seed, op=None):
    """A random starting state, as a recipe both emulators can be built from."""
    rng = random.Random(seed)
    code = bytearray(rng.randbytes(0x10000))
    pc = rng.randrange(0x0100, 0xFF00)
    if op is not None:
        code[pc] = op
    c = dict(code=bytes(code), pc=pc, iram=rng.randbytes(256), sfr=rng.randbytes(256),
             xram=rng.randbytes(0x10000), cycles=rng.randrange(1 << 30),
             pins={p: (rng.randrange(256), rng.randrange(256)) for p in PORTS if rng.random() < 0.4},
             watch={a: (rng.randrange(1, 256) if rng.random() < 0.5 else None)
                    for a in rng.sample(WATCHABLE, rng.randrange(4))},
             tick=(rng.randrange(1, 12), rng.randrange(0, 12)) if rng.random() < 0.5 else None,
             hook=rng.choice((None, None, None, "log", "ret")),
             lcd=[(False, 0x2A)] + [(True, v) for v in (0, rng.randrange(8), 0, rng.randrange(8, 240))]
             + [(False, 0x2B)] + [(True, v) for v in (0, rng.randrange(8), 1, 0x3F)] + [(False, 0x2C)]
             if rng.random() < 0.5 else [])
    return c


def build(cls, c, calls):
    e = cls(c["code"])
    e.iram[:] = c["iram"]
    e.sfr[:] = c["sfr"]
    e.xram[:] = c["xram"]
    e.pc, e.cycles = c["pc"], c["cycles"]
    for p, mv in c["pins"].items():
        e.pins[p] = mv
    for a, mask in c["watch"].items():
        e.sfr_watch[a] = lambda em, old, new, a=a: calls.append(("watch", a, old, new, em.cycles))
        if mask is not None:
            e.sfr_watch_mask[a] = mask
    if c["tick"]:
        every, first = c["tick"]
        e.tick_every = every
        e._next_tick = e.cycles + first

        def tick(em):
            calls.append(("tick", em.pc, em.cycles))
            em.iram[0x30] = (em.iram[0x30] + 1) & 0xFF
        e.on_tick = tick
    if c["hook"]:
        def hook(em, kind=c["hook"]):
            calls.append(("hook", em.pc, em.cycles, em.A))
            if kind == "ret":
                em.ret()
        e.hooks[c["pc"]] = hook
    for dc, v in c["lcd"]:
        e.lcd.byte(dc, v, 0)
    return e


def run_case(c, steps):
    results = []
    for cls in (PyEmu8051, CEmu8051):
        calls = []
        e = build(cls, c, calls)
        try:
            e.run(None, steps)
            err = None
        except RuntimeError as ex:
            err = str(ex)
        results.append((err, state(e), calls))
    return results


def diff(a, b):
    names = ("pc", "cycles", "steps", "next_tick", "iram", "sfr", "xram", "pixels", "lcd log", "gram")
    out = []
    if a[0] != b[0]:
        out.append("error %r vs %r" % (a[0], b[0]))
    out += [n for n, x, y in zip(names, a[1], b[1]) if x != y]
    if a[2] != b[2]:
        out.append("callbacks %s vs %s" % (a[2][:4], b[2][:4]))
    return out


def opcode_chunk(ops, per_op, seed):
    bad = []
    for op in ops:
        for k in range(per_op):
            c = make_case(seed * 1_000_000 + op * 1000 + k, op)
            py, cc = run_case(c, 1)
            d = diff(py, cc)
            if d:
                bad.append("op 0x%02X case %d (pc 0x%04X): %s" % (op, k, c["pc"], ", ".join(d)))
                break
    return bad


def program_chunk(seeds, steps):
    bad = []
    for sd in seeds:
        c = make_case(sd)
        py, cc = run_case(c, steps)
        d = diff(py, cc)
        if d:
            bad.append("program seed %d: %s" % (sd, ", ".join(d)))
    return bad


def firmware(cls_name, image):
    """Run SCENARIO; return the machine-state digest at every tick plus the final state."""
    from ao300 import Amp
    cls = {"py": PyEmu8051, "c": CEmu8051}[cls_name]
    amp = Amp(open(image, "rb").read(), emu=cls)
    e = amp.e
    digests = []
    amp_tick = e.on_tick

    def tick(em):                                      # every 0.5 ms; digest on Timer0 ticks
        n = amp.ticks
        amp_tick(em)
        if amp.ticks == n:
            return
        h = hashlib.sha256(bytes(em.iram) + bytes(em.sfr) + bytes(em.xram))
        h.update(repr((em.pc, em.cycles, em.steps, em.lcd.pixels, len(em.lcd.log))).encode())
        digests.append(h.hexdigest()[:16])
    e.on_tick = tick
    amp.set_pin(0xC0, 5, 0)                            # USB audio present
    for cmd, secs in SCENARIO:
        if cmd is not None:
            amp.press(cmd)
        amp.wait(secs)
    return digests, state(e), amp.events, amp.state_changes, amp.state_log


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-j", type=int, default=os.cpu_count(), help="worker processes")
    ap.add_argument("--per-op", type=int, default=300, help="random cases per opcode")
    ap.add_argument("--programs", type=int, default=400, help="random programs")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--image", default=STOCK, help="firmware image for the boot scenario")
    ap.add_argument("--no-firmware", action="store_true", help="skip the boot scenario")
    args = ap.parse_args()

    t0 = time.time()
    fails = []
    with ProcessPoolExecutor(args.j) as pool:
        fw = None if args.no_firmware else pool.submit(firmware, "py", args.image)
        ops = [op for op in range(256) if op != 0xA5] + [0xA5]
        op_jobs = [pool.submit(opcode_chunk, ops[i::args.j * 2], args.per_op, args.seed)
                   for i in range(args.j * 2)]
        seeds = list(range(args.seed * 100000, args.seed * 100000 + args.programs))
        prog_jobs = [pool.submit(program_chunk, seeds[i::args.j * 2], 3000) for i in range(args.j * 2)]

        op_bad = sum((j.result() for j in op_jobs), [])
        print("every opcode, %d random states each: %s" % (args.per_op, "OK" if not op_bad else "FAIL"))
        fails += op_bad
        prog_bad = sum((j.result() for j in prog_jobs), [])
        print("%d random programs, up to 3000 instructions: %s" % (args.programs, "OK" if not prog_bad else "FAIL"))
        fails += prog_bad

        if fw is not None:
            tc = time.time()
            c = firmware("c", args.image)
            tc = time.time() - tc
            py = fw.result()
            secs = sum(s for _, s in SCENARIO)
            first = next((k for k, (a, b) in enumerate(zip(py[0], c[0])) if a != b), None)
            names = ("tick digests", "final state", "audio events", "audio state changes", "audio state per tick")
            bad = [n for n, a, b in zip(names, py, c) if a != b]
            print("firmware %s, %.1f s emulated (C core %.2f s wall): %s" % (
                os.path.basename(args.image), secs, tc, "OK" if not bad else "FAIL"))
            if bad:
                fails.append("firmware: %s differ%s" % (", ".join(bad), "" if first is None else
                             ", first at tick %d (%.2f s)" % (first + 1, (first + 1) / 100)))
    for f in fails[:20]:
        print("  " + f)
    print("\n%s (%.0f s)" % ("ALL PASS" if not fails else "FAILURES: %d" % len(fails), time.time() - t0))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
