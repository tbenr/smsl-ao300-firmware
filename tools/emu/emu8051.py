"""8051 emulator with STC8 instruction timing and an LCD-bus model of the AO300.

Good enough to run stock firmware routines and patch code end to end:

* full 8051 instruction set, register banks, bit space, PSW flags and parity;
* clock counts from the STC8 instruction table (STC8G reference manual, chapter
  "指令系统"): most instructions take 1 clock, MOVC 4, MOVX 2-3, LCALL/RET/LJMP/SJMP 3,
  conditional jumps 1 not taken / 3 taken, DJNZ and most CJNE 2 / 3, MUL 2, DIV 6;
* interrupts only on request: `tick_every` / `on_tick` call back every N clocks,
  and `interrupt(vector)` runs a handler to completion there (for example the
  firmware's real 10 ms Timer0 ISR at 0x000B);
* `hooks[pc] = fn(emu)` runs fn before the instruction at pc; fn may call
  `emu.ret()` to skip a stock routine that needs real hardware;
* the LCD bus (P1 data, P0.5 WR, P0.7 CS, P0.3 D/C) is sampled on every WR rising
  edge with CS low and fed to an ST7789 model, which can be saved as a PNG.

MOVX @Ri ignores P2 and addresses XDATA page 0, which is how the stock firmware
uses it (its scratch variables at 0x00..0xFF are reached both ways consistently).

Input pins: `pins[port_sfr] = (mask, value)` forces what source reads and bit tests
see on those pins (JB P4.5, MOV A,P4...). Read-modify-write instructions still use the
latch, as on the chip.
"""
import struct
import zlib

ACC, B, PSW, SP, DPL, DPH = 0xE0, 0xF0, 0xD0, 0x81, 0x82, 0x83
P0, P1 = 0x80, 0x90
SENTINEL = 0xFFF0          # return address used by call(); execution stops there


class Emu8051:
    def __init__(self, code):
        self.code = bytearray(code) + b"\xFF" * (0x10000 - len(code))
        self.iram = bytearray(256)
        self.sfr = bytearray(256)          # indexed by SFR address 0x80..0xFF
        self.xram = bytearray(0x10000)
        self.sfr[SP] = 0x07
        self.sfr[P0] = self.sfr[P1] = 0xFF
        self.pc = 0
        self.cycles = 0
        self.steps = 0
        self.hooks = {}
        self.sfr_watch = {}                # addr -> fn(emu, old, new)
        self.tick_every = 0
        self.on_tick = None
        self._next_tick = 0
        self.lcd = LCD()
        self.pins = {}                     # port SFR -> (mask, value) forced on pin reads
        self.sfr_watch[P0] = self._p0_write
        self.ops = [self._bad] * 256
        self._build()

    # ---- memory helpers ---------------------------------------------------
    def reg_base(self):
        return self.sfr[PSW] & 0x18

    def R(self, n):
        return self.iram[(self.sfr[PSW] & 0x18) + n]

    def setR(self, n, v):
        self.iram[(self.sfr[PSW] & 0x18) + n] = v & 0xFF

    def rd(self, a):                        # direct address read
        if a < 0x80:
            return self.iram[a]
        if a == PSW:
            return self.psw()
        return self.sfr[a]

    def wr(self, a, v):                     # direct address write
        v &= 0xFF
        if a < 0x80:
            self.iram[a] = v
            return
        old = self.sfr[a]
        self.sfr[a] = v
        w = self.sfr_watch.get(a)
        if w:
            w(self, old, v)

    def rdp(self, a):
        """Direct read as a source operand: port SFRs return pins, where forced."""
        v = self.rd(a)
        if self.pins and a in self.pins:
            m, val = self.pins[a]
            v = (v & ~m) | (val & m)
        return v

    def getpin(self, b):
        """Bit read by a test or move (JB, JNB, MOV C,bit...): pins where forced."""
        a, n = self.bit_addr(b)
        return (self.rdp(a) >> n) & 1

    def psw(self):
        a = self.sfr[ACC]
        p = bin(a).count("1") & 1
        self.sfr[PSW] = (self.sfr[PSW] & 0xFE) | p
        return self.sfr[PSW]

    def bit_addr(self, b):
        if b < 0x80:
            return 0x20 + (b >> 3), b & 7
        return b & 0xF8, b & 7

    def getbit(self, b):
        a, n = self.bit_addr(b)
        return (self.rd(a) >> n) & 1

    def setbit(self, b, v):
        a, n = self.bit_addr(b)
        cur = self.rd(a)
        self.wr(a, (cur | (1 << n)) if v else (cur & ~(1 << n)))

    @property
    def A(self):
        return self.sfr[ACC]

    @A.setter
    def A(self, v):
        self.sfr[ACC] = v & 0xFF

    @property
    def C(self):
        return self.sfr[PSW] >> 7

    @C.setter
    def C(self, v):
        self.sfr[PSW] = (self.sfr[PSW] & 0x7F) | (0x80 if v else 0)

    @property
    def DPTR(self):
        return (self.sfr[DPH] << 8) | self.sfr[DPL]

    @DPTR.setter
    def DPTR(self, v):
        self.sfr[DPH] = (v >> 8) & 0xFF
        self.sfr[DPL] = v & 0xFF

    def push(self, v):
        sp = (self.sfr[SP] + 1) & 0xFF
        self.sfr[SP] = sp
        self.iram[sp] = v & 0xFF

    def pop(self):
        sp = self.sfr[SP]
        v = self.iram[sp]
        self.sfr[SP] = (sp - 1) & 0xFF
        return v

    def ret(self):
        hi = self.pop()
        lo = self.pop()
        self.pc = (hi << 8) | lo
        self.cycles += 3

    # ---- running ----------------------------------------------------------
    def call(self, addr, max_steps=200_000_000):
        """Call addr as a subroutine; return when it returns."""
        self.push(SENTINEL & 0xFF)
        self.push(SENTINEL >> 8)
        self.pc = addr
        return self.run(SENTINEL, max_steps)

    def run(self, stop_pc, max_steps, stop_cycles=None):
        """Run until pc == stop_pc, or until stop_cycles clocks have elapsed in total."""
        code, ops, hooks = self.code, self.ops, self.hooks
        limit = self.steps + max_steps
        while self.pc != stop_pc:
            if stop_cycles is not None and self.cycles >= stop_cycles:
                break
            if self.steps >= limit:
                raise RuntimeError("step limit at pc 0x%04X" % self.pc)
            h = hooks.get(self.pc)
            if h:
                before = self.pc
                h(self)
                if self.pc != before:
                    continue
            op = code[self.pc]
            ops[op](op)
            self.steps += 1
            if self.tick_every and self.cycles >= self._next_tick:
                self._next_tick += self.tick_every     # fixed schedule, no drift
                if self.on_tick:
                    self.on_tick(self)
        return self.cycles

    def start_ticks(self):
        self._next_tick = self.cycles + self.tick_every

    def interrupt(self, vector):
        """Run an interrupt handler to completion between two instructions.

        Nested interrupts are ignored; the handler's own RETI ends it.
        """
        if getattr(self, "_in_irq", False):
            return
        self._in_irq = True
        pc = self.pc
        try:
            self.call(vector)
        finally:
            self.pc = pc
            self._in_irq = False

    def run_for(self, seconds, clock_hz=24_000_000):
        """Run freely (e.g. the firmware main loop) for a stretch of emulated time."""
        return self.run(None, 1 << 40, stop_cycles=self.cycles + int(seconds * clock_hz))

    # ---- LCD bus ------------------------------------------------------------
    def _p0_write(self, emu, old, new):
        # WR = P0.5 rising edge with CS = P0.7 low latches P1; D/C = P0.3
        if not (old & 0x20) and (new & 0x20) and not (new & 0x80):
            self.lcd.byte(bool(new & 0x08), self.sfr[P1], self.cycles)

    # ---- instruction table ------------------------------------------------
    def _bad(self, op):
        raise RuntimeError("undefined opcode 0x%02X at 0x%04X" % (op, self.pc))

    def _fetch(self, n):
        return self.code[(self.pc + n) & 0xFFFF]

    def _rel(self, off):
        return off - 0x100 if off & 0x80 else off

    def _build(self):
        O = self.ops
        e = self

        def nop(op):
            e.pc += 1; e.cycles += 1
        O[0x00] = nop

        # --- jumps and calls
        def ajmp(op):
            a = ((e.pc + 2) & 0xF800) | ((op & 0xE0) << 3) | e._fetch(1)
            e.pc = a; e.cycles += 3
        def acall(op):
            a = ((e.pc + 2) & 0xF800) | ((op & 0xE0) << 3) | e._fetch(1)
            r = e.pc + 2
            e.push(r & 0xFF); e.push(r >> 8)
            e.pc = a; e.cycles += 3
        for i in range(8):
            O[0x01 + 32 * i] = ajmp
            O[0x11 + 32 * i] = acall

        def ljmp(op):
            e.pc = (e._fetch(1) << 8) | e._fetch(2); e.cycles += 3
        def lcall(op):
            r = e.pc + 3
            e.push(r & 0xFF); e.push(r >> 8)
            e.pc = (e._fetch(1) << 8) | e._fetch(2); e.cycles += 3
        def ret(op):
            e.ret()
        O[0x02] = ljmp; O[0x12] = lcall; O[0x22] = ret; O[0x32] = ret

        def sjmp(op):
            e.pc = (e.pc + 2 + e._rel(e._fetch(1))) & 0xFFFF; e.cycles += 3
        O[0x80] = sjmp

        def jmp_a_dptr(op):
            e.pc = (e.A + e.DPTR) & 0xFFFF; e.cycles += 4
        O[0x73] = jmp_a_dptr

        def condjump(test):
            def f(op):
                if test():
                    e.pc = (e.pc + 2 + e._rel(e._fetch(1))) & 0xFFFF; e.cycles += 3
                else:
                    e.pc += 2; e.cycles += 1
            return f
        O[0x40] = condjump(lambda: e.C == 1)
        O[0x50] = condjump(lambda: e.C == 0)
        O[0x60] = condjump(lambda: e.A == 0)
        O[0x70] = condjump(lambda: e.A != 0)

        def jbit(kind):
            def f(op):
                b = e._fetch(1)
                v = e.getpin(b)
                take = v if kind != "jnb" else not v
                if kind == "jbc" and v:
                    e.setbit(b, 0)
                if take:
                    e.pc = (e.pc + 3 + e._rel(e._fetch(2))) & 0xFFFF; e.cycles += 3
                else:
                    e.pc += 3; e.cycles += 1
            return f
        O[0x10] = jbit("jbc"); O[0x20] = jbit("jb"); O[0x30] = jbit("jnb")

        def cjne(get_a, get_b, length, fast):
            def f(op):
                a, b = get_a(), get_b()
                e.C = 1 if a < b else 0
                if a != b:
                    e.pc = (e.pc + length + e._rel(e._fetch(length - 1))) & 0xFFFF; e.cycles += 3
                else:
                    e.pc += length; e.cycles += 1 if fast else 2
            return f
        O[0xB4] = cjne(lambda: e.A, lambda: e._fetch(1), 3, True)
        O[0xB5] = cjne(lambda: e.A, lambda: e.rdp(e._fetch(1)), 3, False)
        for i in range(2):
            O[0xB6 + i] = cjne(lambda i=i: e.iram[e.R(i)], lambda: e._fetch(1), 3, False)
        for n in range(8):
            O[0xB8 + n] = cjne(lambda n=n: e.R(n), lambda: e._fetch(1), 3, False)

        def djnz_r(op):
            n = op & 7
            v = (e.R(n) - 1) & 0xFF
            e.setR(n, v)
            if v:
                e.pc = (e.pc + 2 + e._rel(e._fetch(1))) & 0xFFFF; e.cycles += 3
            else:
                e.pc += 2; e.cycles += 2
        for n in range(8):
            O[0xD8 + n] = djnz_r

        def djnz_d(op):
            d = e._fetch(1)
            v = (e.rd(d) - 1) & 0xFF
            e.wr(d, v)
            if v:
                e.pc = (e.pc + 3 + e._rel(e._fetch(2))) & 0xFFFF; e.cycles += 3
            else:
                e.pc += 3; e.cycles += 2
        O[0xD5] = djnz_d

        # --- operand accessors: (getter, setter, length)
        def src_imm():   return e._fetch(1)
        def src_dir():   return e.rd(e._fetch(1))
        def ri(i):       return e.R(i)

        # --- arithmetic
        def add(val, carry):
            a = e.A
            c = e.C if carry else 0
            r = a + val + c
            ac = ((a & 0xF) + (val & 0xF) + c) > 0xF
            ov = ((a ^ r) & (val ^ r) & 0x80) != 0
            psw = e.sfr[PSW] & ~(0x80 | 0x40 | 0x04)
            psw |= (0x80 if r > 0xFF else 0) | (0x40 if ac else 0) | (0x04 if ov else 0)
            e.sfr[PSW] = psw & 0xFF
            e.A = r

        def subb(val):
            a = e.A
            c = e.C
            r = a - val - c
            ac = ((a & 0xF) - (val & 0xF) - c) < 0
            ov = ((a ^ val) & (a ^ r) & 0x80) != 0
            psw = e.sfr[PSW] & ~(0x80 | 0x40 | 0x04)
            psw |= (0x80 if r < 0 else 0) | (0x40 if ac else 0) | (0x04 if ov else 0)
            e.sfr[PSW] = psw & 0xFF
            e.A = r

        def alu_family(base, fn):
            def imm(op):  fn(e._fetch(1)); e.pc += 2; e.cycles += 1
            def dr(op):   fn(e.rdp(e._fetch(1))); e.pc += 2; e.cycles += 1
            def ind(op):  fn(e.iram[e.R(op & 1)]); e.pc += 1; e.cycles += 1
            def reg(op):  fn(e.R(op & 7)); e.pc += 1; e.cycles += 1
            O[base + 4] = imm; O[base + 5] = dr
            O[base + 6] = O[base + 7] = ind
            for n in range(8):
                O[base + 8 + n] = reg
        alu_family(0x20, lambda v: add(v, False))
        alu_family(0x30, lambda v: add(v, True))
        alu_family(0x90, subb)

        def logic(v_op):
            def to_a(v):
                e.A = v_op(e.A, v)
            return to_a
        for base, f in ((0x40, lambda a, b: a | b), (0x50, lambda a, b: a & b), (0x60, lambda a, b: a ^ b)):
            alu_family(base, logic(f))
            def dir_a(op, f=f):
                d = e._fetch(1); e.wr(d, f(e.rd(d), e.A)); e.pc += 2; e.cycles += 1
            def dir_imm(op, f=f):
                d = e._fetch(1); e.wr(d, f(e.rd(d), e._fetch(2))); e.pc += 3; e.cycles += 1
            O[base + 2] = dir_a; O[base + 3] = dir_imm

        def inc_a(op):  e.A = e.A + 1; e.pc += 1; e.cycles += 1
        def dec_a(op):  e.A = e.A - 1; e.pc += 1; e.cycles += 1
        def inc_d(op):  d = e._fetch(1); e.wr(d, e.rd(d) + 1); e.pc += 2; e.cycles += 1
        def dec_d(op):  d = e._fetch(1); e.wr(d, e.rd(d) - 1); e.pc += 2; e.cycles += 1
        def inc_i(op):  a = e.R(op & 1); e.iram[a] = (e.iram[a] + 1) & 0xFF; e.pc += 1; e.cycles += 1
        def dec_i(op):  a = e.R(op & 1); e.iram[a] = (e.iram[a] - 1) & 0xFF; e.pc += 1; e.cycles += 1
        def inc_r(op):  e.setR(op & 7, e.R(op & 7) + 1); e.pc += 1; e.cycles += 1
        def dec_r(op):  e.setR(op & 7, e.R(op & 7) - 1); e.pc += 1; e.cycles += 1
        O[0x04] = inc_a; O[0x05] = inc_d; O[0x06] = O[0x07] = inc_i
        O[0x14] = dec_a; O[0x15] = dec_d; O[0x16] = O[0x17] = dec_i
        for n in range(8):
            O[0x08 + n] = inc_r; O[0x18 + n] = dec_r

        def inc_dptr(op): e.DPTR = (e.DPTR + 1) & 0xFFFF; e.pc += 1; e.cycles += 1
        O[0xA3] = inc_dptr

        def mul(op):
            r = e.A * e.sfr[B]
            e.A = r & 0xFF; e.sfr[B] = r >> 8
            e.sfr[PSW] = (e.sfr[PSW] & ~0x84) | (0x04 if r > 0xFF else 0)
            e.pc += 1; e.cycles += 2
        def div(op):
            a, b = e.A, e.sfr[B]
            if b == 0:
                e.sfr[PSW] = (e.sfr[PSW] & ~0x84) | 0x04
            else:
                e.A = a // b; e.sfr[B] = a % b
                e.sfr[PSW] &= ~0x84
            e.pc += 1; e.cycles += 6
        O[0xA4] = mul; O[0x84] = div

        def da(op):
            a = e.A
            c = e.C
            if (a & 0xF) > 9 or (e.sfr[PSW] & 0x40):
                a += 6
            if (a >> 4) > 9 or c or a > 0xFF:
                a += 0x60
            if a > 0xFF:
                c = 1
            e.A = a; e.C = c
            e.pc += 1; e.cycles += 3
        O[0xD4] = da

        # --- accumulator ops
        def clr_a(op): e.A = 0; e.pc += 1; e.cycles += 1
        def cpl_a(op): e.A = ~e.A; e.pc += 1; e.cycles += 1
        def rl(op):    a = e.A; e.A = (a << 1) | (a >> 7); e.pc += 1; e.cycles += 1
        def rr(op):    a = e.A; e.A = (a >> 1) | ((a & 1) << 7); e.pc += 1; e.cycles += 1
        def rlc(op):
            a = e.A; c = e.C; e.C = a >> 7; e.A = (a << 1) | c; e.pc += 1; e.cycles += 1
        def rrc(op):
            a = e.A; c = e.C; e.C = a & 1; e.A = (a >> 1) | (c << 7); e.pc += 1; e.cycles += 1
        def swap(op):  a = e.A; e.A = ((a << 4) | (a >> 4)); e.pc += 1; e.cycles += 1
        O[0xE4] = clr_a; O[0xF4] = cpl_a; O[0x23] = rl; O[0x03] = rr
        O[0x33] = rlc; O[0x13] = rrc; O[0xC4] = swap

        # --- carry / bit ops
        def clr_c(op):  e.C = 0; e.pc += 1; e.cycles += 1
        def setb_c(op): e.C = 1; e.pc += 1; e.cycles += 1
        def cpl_c(op):  e.C = 1 - e.C; e.pc += 1; e.cycles += 1
        def clr_b(op):  e.setbit(e._fetch(1), 0); e.pc += 2; e.cycles += 1
        def setb_b(op): e.setbit(e._fetch(1), 1); e.pc += 2; e.cycles += 1
        def cpl_b(op):  b = e._fetch(1); e.setbit(b, 1 - e.getbit(b)); e.pc += 2; e.cycles += 1
        def mov_c_b(op): e.C = e.getpin(e._fetch(1)); e.pc += 2; e.cycles += 1
        def mov_b_c(op): e.setbit(e._fetch(1), e.C); e.pc += 2; e.cycles += 1
        def orl_c(op):  e.C = e.C | e.getpin(e._fetch(1)); e.pc += 2; e.cycles += 1
        def anl_c(op):  e.C = e.C & e.getpin(e._fetch(1)); e.pc += 2; e.cycles += 1
        def orl_nc(op): e.C = e.C | (1 - e.getpin(e._fetch(1))); e.pc += 2; e.cycles += 1
        def anl_nc(op): e.C = e.C & (1 - e.getpin(e._fetch(1))); e.pc += 2; e.cycles += 1
        O[0xC3] = clr_c; O[0xD3] = setb_c; O[0xB3] = cpl_c
        O[0xC2] = clr_b; O[0xD2] = setb_b; O[0xB2] = cpl_b
        O[0xA2] = mov_c_b; O[0x92] = mov_b_c
        O[0x72] = orl_c; O[0x82] = anl_c; O[0xA0] = orl_nc; O[0xB0] = anl_nc

        # --- data moves
        def mov_a_imm(op): e.A = e._fetch(1); e.pc += 2; e.cycles += 1
        def mov_a_dir(op): e.A = e.rdp(e._fetch(1)); e.pc += 2; e.cycles += 1
        def mov_a_ind(op): e.A = e.iram[e.R(op & 1)]; e.pc += 1; e.cycles += 1
        def mov_a_reg(op): e.A = e.R(op & 7); e.pc += 1; e.cycles += 1
        O[0x74] = mov_a_imm; O[0xE5] = mov_a_dir; O[0xE6] = O[0xE7] = mov_a_ind
        def mov_dir_a(op): e.wr(e._fetch(1), e.A); e.pc += 2; e.cycles += 1
        def mov_ind_a(op): e.iram[e.R(op & 1)] = e.A; e.pc += 1; e.cycles += 1
        def mov_reg_a(op): e.setR(op & 7, e.A); e.pc += 1; e.cycles += 1
        O[0xF5] = mov_dir_a; O[0xF6] = O[0xF7] = mov_ind_a
        def mov_dir_imm(op): e.wr(e._fetch(1), e._fetch(2)); e.pc += 3; e.cycles += 1
        def mov_ind_imm(op): e.iram[e.R(op & 1)] = e._fetch(1); e.pc += 2; e.cycles += 1
        def mov_reg_imm(op): e.setR(op & 7, e._fetch(1)); e.pc += 2; e.cycles += 1
        O[0x75] = mov_dir_imm; O[0x76] = O[0x77] = mov_ind_imm
        def mov_dir_dir(op): v = e.rdp(e._fetch(1)); e.wr(e._fetch(2), v); e.pc += 3; e.cycles += 1
        def mov_dir_ind(op): e.wr(e._fetch(1), e.iram[e.R(op & 1)]); e.pc += 2; e.cycles += 1
        def mov_dir_reg(op): e.wr(e._fetch(1), e.R(op & 7)); e.pc += 2; e.cycles += 1
        def mov_ind_dir(op): e.iram[e.R(op & 1)] = e.rdp(e._fetch(1)); e.pc += 2; e.cycles += 1
        def mov_reg_dir(op): e.setR(op & 7, e.rdp(e._fetch(1))); e.pc += 2; e.cycles += 1
        O[0x85] = mov_dir_dir; O[0x86] = O[0x87] = mov_dir_ind
        O[0xA6] = O[0xA7] = mov_ind_dir
        for n in range(8):
            O[0xE8 + n] = mov_a_reg; O[0xF8 + n] = mov_reg_a; O[0x78 + n] = mov_reg_imm
            O[0x88 + n] = mov_dir_reg; O[0xA8 + n] = mov_reg_dir

        def mov_dptr(op): e.DPTR = (e._fetch(1) << 8) | e._fetch(2); e.pc += 3; e.cycles += 1
        def movc_dptr(op): e.A = e.code[(e.A + e.DPTR) & 0xFFFF]; e.pc += 1; e.cycles += 4
        def movc_pc(op): e.A = e.code[(e.A + e.pc + 1) & 0xFFFF]; e.pc += 1; e.cycles += 3
        O[0x90] = mov_dptr; O[0x93] = movc_dptr; O[0x83] = movc_pc

        def movx_a_dptr(op): e.A = e.xram[e.DPTR]; e.pc += 1; e.cycles += 2
        def movx_a_ri(op):   e.A = e.xram[e.R(op & 1)]; e.pc += 1; e.cycles += 3
        def movx_dptr_a(op): e.xram[e.DPTR] = e.A; e.pc += 1; e.cycles += 2
        def movx_ri_a(op):   e.xram[e.R(op & 1)] = e.A; e.pc += 1; e.cycles += 3
        O[0xE0] = movx_a_dptr; O[0xE2] = O[0xE3] = movx_a_ri
        O[0xF0] = movx_dptr_a; O[0xF2] = O[0xF3] = movx_ri_a

        def push_(op): e.push(e.rdp(e._fetch(1))); e.pc += 2; e.cycles += 1
        def pop_(op):  v = e.pop(); e.wr(e._fetch(1), v); e.pc += 2; e.cycles += 1
        O[0xC0] = push_; O[0xD0] = pop_

        def xch_dir(op):
            d = e._fetch(1); v = e.rd(d); e.wr(d, e.A); e.A = v; e.pc += 2; e.cycles += 1
        def xch_ind(op):
            a = e.R(op & 1); v = e.iram[a]; e.iram[a] = e.A; e.A = v; e.pc += 1; e.cycles += 1
        def xch_reg(op):
            n = op & 7; v = e.R(n); e.setR(n, e.A); e.A = v; e.pc += 1; e.cycles += 1
        def xchd(op):
            a = e.R(op & 1); v = e.iram[a]
            e.iram[a] = (v & 0xF0) | (e.A & 0x0F); e.A = (e.A & 0xF0) | (v & 0x0F)
            e.pc += 1; e.cycles += 1
        O[0xC5] = xch_dir; O[0xC6] = O[0xC7] = xch_ind; O[0xD6] = O[0xD7] = xchd
        for n in range(8):
            O[0xC8 + n] = xch_reg


class LCD:
    """ST7789 model: 240 columns x 320 rows of RGB565, MADCTL MV=0 (column first)."""
    COLS, ROWS = 240, 320

    def __init__(self):
        self.gram = [0] * (self.COLS * self.ROWS)
        self.cmd = None
        self.params = []
        self.cs, self.ce, self.rs, self.re = 0, self.COLS - 1, 0, self.ROWS - 1
        self.col = self.row = 0
        self.hi = None
        self.pixels = 0              # pixels written since reset_stats()
        self.log = []                # (cycle, cmd) for every command byte

    def reset_stats(self):
        self.pixels = 0
        self.log = []

    def byte(self, dc, v, cycle):
        if not dc:                   # command
            self.cmd, self.params, self.hi = v, [], None
            self.log.append((cycle, v))
            if v == 0x2C:
                self.col, self.row = self.cs, self.rs
            return
        if self.cmd == 0x2C:
            if self.hi is None:
                self.hi = v
                return
            px = (self.hi << 8) | v
            self.hi = None
            if 0 <= self.col < self.COLS and 0 <= self.row < self.ROWS:
                self.gram[self.row * self.COLS + self.col] = px
            self.pixels += 1
            self.col += 1
            if self.col > self.ce:
                self.col = self.cs
                self.row += 1
                if self.row > self.re:
                    self.row = self.rs
            return
        self.params.append(v)
        if len(self.params) == 4 and self.cmd in (0x2A, 0x2B):
            s = (self.params[0] << 8) | self.params[1]
            t = (self.params[2] << 8) | self.params[3]
            if self.cmd == 0x2A:
                self.cs, self.ce = s, t
            else:
                self.rs, self.re = s, t

    def screen_pixel(self, x, y, col_offset=0x23):
        """Firmware coordinates: x 0..319 (panel row), y 0..169 (panel column - 0x23)."""
        return self.gram[x * self.COLS + y + col_offset]

    def save_png(self, path, width=320, height=170, scale=2):
        rows = []
        for y in range(height):
            line = bytearray()
            for x in range(width):
                p = self.screen_pixel(x, y)
                r = ((p >> 11) & 0x1F) * 255 // 31
                g = ((p >> 5) & 0x3F) * 255 // 63
                b = (p & 0x1F) * 255 // 31
                line += bytes((r, g, b)) * scale
            for _ in range(scale):
                rows.append(b"\x00" + bytes(line))
        raw = b"".join(rows)

        def chunk(t, d):
            return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
        ihdr = struct.pack(">IIBBBBB", width * scale, height * scale, 8, 2, 0, 0, 0)
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) +
                    chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))
