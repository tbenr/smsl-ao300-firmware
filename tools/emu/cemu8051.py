"""C core for emu8051: the same emulator as PyEmu8051, about 100x faster.

CEmu8051 has PyEmu8051's interface (and inherits its helpers: R, setR, push, pop, ret,
call, interrupt, run_for, the A / C / DPTR properties). Memory stays in Python
bytearrays that the C code (core8051.c) reads and writes in place, so e.iram[0x45],
e.xram[...] and e.sfr[...] work as before. core_run() hands control back to Python
for hooks, Timer0 ticks, watched SFR writes and stop conditions.

One difference from PyEmu8051: an sfr_watch callback runs after the instruction that
wrote the SFR, not in the middle of it. emu.cycles reads as at the write, as in
PyEmu8051; pc and registers are already those after the instruction.

The library is compiled on first use with the system C compiler (CC, default cc) into
tools/emu/build/, named after a hash of the source, so edits rebuild it.
"""
import ctypes
import hashlib
import os
import subprocess
import sys
from array import array

from emu8051 import PyEmu8051, LCD

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "core8051.c")
CFLAGS = ["-O2", "-shared", "-fPIC"]

EV_STOP, EV_CYCLES, EV_LIMIT, EV_HOOK, EV_TICK, EV_WATCH, EV_BADOP = range(7)

u8p, u16p, i64p = ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_int64)
i64, i32 = ctypes.c_int64, ctypes.c_int32


class S(ctypes.Structure):
    """Mirror of struct S in core8051.c; keep the field order identical."""
    _fields_ = [(n, u8p) for n in ("code", "iram", "sfr", "xram", "hookmap", "pin_mask", "pin_val",
                                   "watch_mode", "watch_mask")] + [
        ("gram", u16p), ("log_cycles", i64p), ("log_cmds", u8p)] + [
        (n, i64) for n in ("cycles", "steps", "next_tick", "tick_every", "w_cycles", "pixels",
                           "log_n", "log_cap")] + [
        (n, i32) for n in ("pc", "skip_checks", "pending_tick", "w_pending", "w_addr", "w_old", "w_new",
                           "cmd", "nparams", "cs", "ce", "rs", "re", "col", "row", "hi")] + [
        ("params", i32 * 4), ("oom", i32)]


def _load():
    cc = os.environ.get("CC", "cc")
    src = open(SRC, "rb").read()
    tag = hashlib.sha256(src + repr((cc, CFLAGS, sys.platform)).encode()).hexdigest()[:12]
    path = os.path.join(HERE, "build", "core8051-%s.so" % tag)
    if not os.path.exists(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = "%s.%d.tmp" % (path, os.getpid())       # parallel test runs may build at once
        subprocess.run([cc] + CFLAGS + ["-o", tmp, SRC], check=True)
        os.replace(tmp, path)
    lib = ctypes.CDLL(path)
    lib.core_run.argtypes = [ctypes.POINTER(S), i64, i64, i64]
    lib.core_run.restype = ctypes.c_int
    lib.lcd_byte.argtypes = [ctypes.POINTER(S), ctypes.c_int, ctypes.c_int, i64]
    lib.lcd_byte.restype = None
    lib.core_free.argtypes = [ctypes.POINTER(S)]
    lib.core_free.restype = None
    return lib


LIB = _load()


def _ptr(buf, ctype):
    """Pointer into a bytearray or array; the struct field keeps the buffer alive."""
    return ctypes.cast((ctype._type_ * len(buf)).from_buffer(buf), ctype)


class _Synced(dict):
    """dict that calls sync(key) after every change, to mirror itself into C tables."""

    def __init__(self, sync):
        super().__init__()
        self._sync = sync

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self._sync(k)

    def __delitem__(self, k):
        super().__delitem__(k)
        self._sync(k)

    def pop(self, k, *default):
        v = super().pop(k, *default)
        self._sync(k)
        return v

    def setdefault(self, k, v=None):
        if k not in self:
            self[k] = v
        return self[k]

    def update(self, *a, **kw):
        for k, v in dict(*a, **kw).items():
            self[k] = v

    def clear(self):
        keys = list(self)
        super().clear()
        for k in keys:
            self._sync(k)

    def popitem(self):
        k, v = super().popitem()
        self._sync(k)
        return k, v


class _Log:
    """LCD command log as a read-only sequence of (cycle, cmd), built from the C buffer."""

    def __init__(self, s):
        self._s = s
        self._cache = []

    def __len__(self):
        return self._s.log_n

    def _list(self):
        s, c = self._s, self._cache
        if len(c) > s.log_n:                 # reset_stats() since the last read
            del c[:]
        if len(c) < s.log_n:
            a = len(c)
            c.extend(zip(s.log_cycles[a:s.log_n], s.log_cmds[a:s.log_n]))
        return c

    def __iter__(self):
        return iter(self._list())

    def __getitem__(self, i):
        return self._list()[i]

    def __eq__(self, other):
        return self._list() == list(other)

    def __repr__(self):
        return repr(self._list())


class CLCD(LCD):
    """LCD whose state lives in the C struct; same attributes and methods as LCD."""

    def __init__(self, s):
        self._s = s
        self._gram = array("H", bytes(2 * self.COLS * self.ROWS))
        s.gram = _ptr(self._gram, u16p)
        s.cmd, s.hi = -1, -1
        s.cs, s.ce, s.rs, s.re = 0, self.COLS - 1, 0, self.ROWS - 1
        self._log = _Log(s)

    @property
    def gram(self):
        return self._gram

    @gram.setter
    def gram(self, values):
        self._gram[:] = array("H", values)

    @property
    def pixels(self):
        return self._s.pixels

    @pixels.setter
    def pixels(self, v):
        self._s.pixels = v

    @property
    def log(self):
        return self._log

    def reset_stats(self):
        self._s.pixels = 0
        self._s.log_n = 0

    def byte(self, dc, v, cycle):
        LIB.lcd_byte(ctypes.byref(self._s), int(bool(dc)), v, cycle)


def _field(name):
    return property(lambda self: getattr(self._s, name), lambda self, v: setattr(self._s, name, v))


class CEmu8051(PyEmu8051):
    pc = _field("pc")
    steps = _field("steps")
    tick_every = _field("tick_every")
    _next_tick = _field("next_tick")

    def __init__(self, code):
        self._s = s = S()
        self._cyc = None                     # cycles as seen by an sfr_watch callback
        self.code = bytearray(code) + b"\xFF" * (0x10000 - len(code))
        self.iram = bytearray(256)
        self.sfr = bytearray(256)
        self.xram = bytearray(0x10000)
        self._hookmap = bytearray(0x10000)
        self._pin_mask, self._pin_val = bytearray(256), bytearray(256)
        self._watch_mode, self._watch_mask = bytearray(256), bytearray(256)
        for name in ("code", "iram", "sfr", "xram"):
            setattr(s, name, _ptr(getattr(self, name), u8p))
        for name in ("hookmap", "pin_mask", "pin_val", "watch_mode", "watch_mask"):
            setattr(s, name, _ptr(getattr(self, "_" + name), u8p))
        self.sfr[0x81] = 0x07
        self.sfr[0x80] = self.sfr[0x90] = 0xFF
        self.hooks = _Synced(self._sync_hook)
        self.sfr_watch = _Synced(self._sync_watch)
        self.sfr_watch_mask = _Synced(self._sync_watch)
        self.pins = _Synced(self._sync_pin)
        self.on_tick = None
        self.lcd = CLCD(s)

    def __del__(self):
        s = getattr(self, "_s", None)
        if s is not None:
            LIB.core_free(ctypes.byref(s))

    @property
    def cycles(self):
        return self._s.cycles if self._cyc is None else self._cyc

    @cycles.setter
    def cycles(self, v):
        self._s.cycles = v

    def _sync_hook(self, pc):
        self._hookmap[pc & 0xFFFF] = 1 if pc in self.hooks else 0

    def _sync_watch(self, a):
        self._watch_mode[a] = 0 if a not in self.sfr_watch else 2 if a in self.sfr_watch_mask else 1
        self._watch_mask[a] = self.sfr_watch_mask.get(a, 0) & 0xFF

    def _sync_pin(self, a):
        m, v = self.pins.get(a, (0, 0))
        self._pin_mask[a], self._pin_val[a] = m & 0xFF, v & 0xFF

    def run(self, stop_pc, max_steps, stop_cycles=None):
        """Run until pc == stop_pc, or until stop_cycles clocks have elapsed in total."""
        s = self._s
        ref = ctypes.byref(s)
        limit = s.steps + max_steps
        sp = -1 if stop_pc is None else stop_pc
        sc = -1 if stop_cycles is None else stop_cycles
        run = LIB.core_run
        while True:
            ev = run(ref, sp, limit, sc)
            if ev == EV_TICK:
                if self.on_tick:
                    self.on_tick(self)
            elif ev == EV_HOOK:
                before = s.pc
                self.hooks[before](self)
                if s.pc == before:
                    s.skip_checks = 1
            elif ev == EV_WATCH:
                s.w_pending = 0
                fn = self.sfr_watch.get(s.w_addr)
                if fn:
                    self._cyc = s.w_cycles
                    try:
                        fn(self, s.w_old, s.w_new)
                    finally:
                        self._cyc = None
            elif ev in (EV_STOP, EV_CYCLES):
                break
            elif ev == EV_LIMIT:
                raise RuntimeError("step limit at pc 0x%04X" % s.pc)
            else:
                raise RuntimeError("undefined opcode 0x%02X at 0x%04X" % (self.code[s.pc & 0xFFFF], s.pc))
            if s.oom:
                raise MemoryError("LCD command log")
        return s.cycles
