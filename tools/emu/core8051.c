/* C core of tools/emu/emu8051.py: the same 8051 interpreter, STC8 clock counts and
 * ST7789 bus model, instruction for instruction. PyEmu8051 in emu8051.py is the
 * reference; tools/emu/test_core.py checks that both give identical state. Change
 * both together.
 *
 * Memory (code, iram, sfr, xram, the LCD's gram) belongs to Python bytearrays and
 * arrays; this file only reads and writes through the pointers in S. core_run()
 * returns to Python whenever Python has to act: a hooked pc, a due Timer0 tick, a
 * write to a watched SFR, or a stop condition. The Python side (cemu8051.py) acts
 * and calls core_run() again, so a hook or tick may itself run nested code.
 */
#include <stdint.h>
#include <stdlib.h>

enum { EV_STOP, EV_CYCLES, EV_LIMIT, EV_HOOK, EV_TICK, EV_WATCH, EV_BADOP };

#define ACC 0xE0
#define B_ 0xF0
#define PSW 0xD0
#define SP 0x81
#define DPL 0x82
#define DPH 0x83
#define P0 0x80
#define P1 0x90
#define LCD_COLS 240
#define LCD_ROWS 320

typedef struct {
    uint8_t *code, *iram, *sfr, *xram;
    uint8_t *hookmap;                   /* 65536 bytes: 1 = hook at this pc */
    uint8_t *pin_mask, *pin_val;        /* 256 bytes each: forced input pins */
    uint8_t *watch_mode, *watch_mask;   /* 256 bytes each: 1 every write, 2 masked change */
    uint16_t *gram;
    int64_t *log_cycles;                /* LCD command log, grown here */
    uint8_t *log_cmds;
    int64_t cycles, steps, next_tick, tick_every;
    int64_t w_cycles, pixels, log_n, log_cap;
    int32_t pc, skip_checks, pending_tick;
    int32_t w_pending, w_addr, w_old, w_new;
    int32_t cmd, nparams, cs, ce, rs, re, col, row, hi;
    int32_t params[4];
    int32_t oom;
} S;

/* ---- LCD ------------------------------------------------------------------ */
static void lcd_log(S *s, int64_t cycle, int v)
{
    if (s->log_n == s->log_cap) {
        int64_t cap = s->log_cap ? s->log_cap * 2 : 4096;
        int64_t *c = realloc(s->log_cycles, cap * sizeof *c);
        if (c) s->log_cycles = c;
        uint8_t *m = realloc(s->log_cmds, cap);
        if (m) s->log_cmds = m;
        if (!c || !m) { s->oom = 1; return; }
        s->log_cap = cap;
    }
    s->log_cycles[s->log_n] = cycle;
    s->log_cmds[s->log_n] = (uint8_t)v;
    s->log_n++;
}

void lcd_byte(S *s, int dc, int v, int64_t cycle)
{
    if (!dc) {                          /* command */
        s->cmd = v; s->nparams = 0; s->hi = -1;
        lcd_log(s, cycle, v);
        if (v == 0x2C) { s->col = s->cs; s->row = s->rs; }
        return;
    }
    if (s->cmd == 0x2C) {
        if (s->hi < 0) { s->hi = v; return; }
        int px = (s->hi << 8) | v;
        s->hi = -1;
        if (s->col >= 0 && s->col < LCD_COLS && s->row >= 0 && s->row < LCD_ROWS)
            s->gram[s->row * LCD_COLS + s->col] = (uint16_t)px;
        s->pixels++;
        s->col++;
        if (s->col > s->ce) {
            s->col = s->cs;
            s->row++;
            if (s->row > s->re) s->row = s->rs;
        }
        return;
    }
    if (s->nparams < 4) s->params[s->nparams] = v;
    if (s->nparams < 5) s->nparams++;
    if (s->nparams == 4 && (s->cmd == 0x2A || s->cmd == 0x2B)) {
        int a = (s->params[0] << 8) | s->params[1];
        int b = (s->params[2] << 8) | s->params[3];
        if (s->cmd == 0x2A) { s->cs = a; s->ce = b; }
        else { s->rs = a; s->re = b; }
    }
}

void core_free(S *s)
{
    free(s->log_cycles); free(s->log_cmds);
    s->log_cycles = 0; s->log_cmds = 0; s->log_n = s->log_cap = 0;
}

/* ---- memory helpers (as in PyEmu8051) ------------------------------------ */
#define A (s->sfr[ACC])
#define CY (s->sfr[PSW] >> 7)
#define DPTR ((s->sfr[DPH] << 8) | s->sfr[DPL])
#define RBASE (s->sfr[PSW] & 0x18)
#define R(n) (s->iram[RBASE + (n)])
#define F(n) (s->code[(s->pc + (n)) & 0xFFFF])
#define REL(x) ((int8_t)(x))

static inline void set_c(S *s, int v) { s->sfr[PSW] = (s->sfr[PSW] & 0x7F) | (v ? 0x80 : 0); }
static inline void set_dptr(S *s, int v) { s->sfr[DPH] = (v >> 8) & 0xFF; s->sfr[DPL] = v & 0xFF; }

static inline int psw(S *s)
{
    s->sfr[PSW] = (s->sfr[PSW] & 0xFE) | (__builtin_popcount(A) & 1);
    return s->sfr[PSW];
}

static inline int rd(S *s, int a)
{
    if (a < 0x80) return s->iram[a];
    if (a == PSW) return psw(s);
    return s->sfr[a];
}

static inline int rdp(S *s, int a)      /* source operand: forced pins where set */
{
    int v = rd(s, a), m = s->pin_mask[a];
    return (v & ~m) | (s->pin_val[a] & m);
}

static inline void wr(S *s, int a, int v)
{
    v &= 0xFF;
    if (a < 0x80) { s->iram[a] = (uint8_t)v; return; }
    int old = s->sfr[a];
    s->sfr[a] = (uint8_t)v;
    /* WR = P0.5 rising edge with CS = P0.7 low latches P1; D/C = P0.3 */
    if (a == P0 && !(old & 0x20) && (v & 0x20) && !(v & 0x80))
        lcd_byte(s, (v & 0x08) != 0, s->sfr[P1], s->cycles);
    int m = s->watch_mode[a];
    if (m == 1 || (m == 2 && ((old ^ v) & s->watch_mask[a]))) {
        s->w_pending = 1; s->w_addr = a; s->w_old = old; s->w_new = v; s->w_cycles = s->cycles;
    }
}

static inline int bit_byte(int b) { return b < 0x80 ? 0x20 + (b >> 3) : (b & 0xF8); }
static inline int getbit(S *s, int b) { return (rd(s, bit_byte(b)) >> (b & 7)) & 1; }
static inline int getpin(S *s, int b) { return (rdp(s, bit_byte(b)) >> (b & 7)) & 1; }

static inline void setbit(S *s, int b, int v)
{
    int a = bit_byte(b), cur = rd(s, a);
    wr(s, a, v ? (cur | (1 << (b & 7))) : (cur & ~(1 << (b & 7))));
}

static inline void push(S *s, int v)
{
    int sp = (s->sfr[SP] + 1) & 0xFF;
    s->sfr[SP] = (uint8_t)sp;
    s->iram[sp] = v & 0xFF;
}

static inline int pop(S *s)
{
    int sp = s->sfr[SP], v = s->iram[sp];
    s->sfr[SP] = (sp - 1) & 0xFF;
    return v;
}

static inline void add(S *s, int val, int carry)
{
    int a = A, c = carry ? CY : 0, r = a + val + c;
    int ac = ((a & 0xF) + (val & 0xF) + c) > 0xF;
    int ov = ((a ^ r) & (val ^ r) & 0x80) != 0;
    int p = s->sfr[PSW] & ~(0x80 | 0x40 | 0x04);
    p |= (r > 0xFF ? 0x80 : 0) | (ac ? 0x40 : 0) | (ov ? 0x04 : 0);
    s->sfr[PSW] = p & 0xFF;
    A = r & 0xFF;
}

static inline void subb(S *s, int val)
{
    int a = A, c = CY, r = a - val - c;
    int ac = ((a & 0xF) - (val & 0xF) - c) < 0;
    int ov = ((a ^ val) & (a ^ r) & 0x80) != 0;
    int p = s->sfr[PSW] & ~(0x80 | 0x40 | 0x04);
    p |= (r < 0 ? 0x80 : 0) | (ac ? 0x40 : 0) | (ov ? 0x04 : 0);
    s->sfr[PSW] = p & 0xFF;
    A = r & 0xFF;
}

static inline void alu(S *s, int kind, int v)
{
    switch (kind) {
    case 0x2: add(s, v, 0); break;
    case 0x3: add(s, v, 1); break;
    case 0x9: subb(s, v); break;
    case 0x4: A = A | v; break;
    case 0x5: A = A & v; break;
    case 0x6: A = A ^ v; break;
    }
}

static inline int logic(int kind, int a, int b)
{
    return kind == 0x4 ? (a | b) : kind == 0x5 ? (a & b) : (a ^ b);
}

#define JUMP(len, relbyte, cyc) do { s->pc = (s->pc + (len) + REL(relbyte)) & 0xFFFF; s->cycles += (cyc); } while (0)
#define NEXT(len, cyc) do { s->pc += (len); s->cycles += (cyc); } while (0)

/* Execute one instruction. Returns 0, or EV_BADOP (nothing changed). */
static inline int step(S *s)
{
    int op = s->code[s->pc & 0xFFFF];
    int lo = op & 0x0F, hi = op >> 4;

    /* ALU families: ADD 2x, ADDC 3x, ORL 4x, ANL 5x, XRL 6x, SUBB 9x, low nibble 4..F */
    if (lo >= 4 && (hi == 0x2 || hi == 0x3 || hi == 0x4 || hi == 0x5 || hi == 0x6 || hi == 0x9)) {
        if (lo == 4) { alu(s, hi, F(1)); NEXT(2, 1); }
        else if (lo == 5) { alu(s, hi, rdp(s, F(1))); NEXT(2, 1); }
        else if (lo < 8) { alu(s, hi, s->iram[R(op & 1)]); NEXT(1, 1); }
        else { alu(s, hi, R(op & 7)); NEXT(1, 1); }
        return 0;
    }
    if ((op & 0x1F) == 0x01) {          /* AJMP */
        s->pc = ((s->pc + 2) & 0xF800) | ((op & 0xE0) << 3) | F(1);
        s->cycles += 3;
        return 0;
    }
    if ((op & 0x1F) == 0x11) {          /* ACALL */
        int a = ((s->pc + 2) & 0xF800) | ((op & 0xE0) << 3) | F(1);
        int r = s->pc + 2;
        push(s, r & 0xFF); push(s, r >> 8);
        s->pc = a; s->cycles += 3;
        return 0;
    }
    if (op >= 0xB8 && op <= 0xBF) {     /* CJNE Rn,#imm,rel */
        int a = R(op & 7), b = F(1);
        set_c(s, a < b);
        if (a != b) JUMP(3, F(2), 3); else NEXT(3, 2);
        return 0;
    }
    if (op >= 0xD8 && op <= 0xDF) {     /* DJNZ Rn,rel */
        int v = (R(op & 7) - 1) & 0xFF;
        R(op & 7) = (uint8_t)v;
        if (v) JUMP(2, F(1), 3); else NEXT(2, 2);
        return 0;
    }
    if (lo >= 8) {                      /* register forms */
        int n = op & 7;
        switch (hi) {
        case 0x0: R(n) = (uint8_t)(R(n) + 1); NEXT(1, 1); return 0;
        case 0x1: R(n) = (uint8_t)(R(n) - 1); NEXT(1, 1); return 0;
        case 0x7: R(n) = F(1); NEXT(2, 1); return 0;
        case 0x8: wr(s, F(1), R(n)); NEXT(2, 1); return 0;
        case 0xA: R(n) = (uint8_t)rdp(s, F(1)); NEXT(2, 1); return 0;
        case 0xC: { int v = R(n); R(n) = A; A = (uint8_t)v; NEXT(1, 1); return 0; }
        case 0xE: A = R(n); NEXT(1, 1); return 0;
        case 0xF: R(n) = A; NEXT(1, 1); return 0;
        }
    }

    switch (op) {
    case 0x00: NEXT(1, 1); return 0;
    case 0x02: s->pc = (F(1) << 8) | F(2); s->cycles += 3; return 0;
    case 0x12: {
        int r = s->pc + 3;
        push(s, r & 0xFF); push(s, r >> 8);
        s->pc = (F(1) << 8) | F(2); s->cycles += 3;
        return 0;
    }
    case 0x22: case 0x32: {
        int h = pop(s), l = pop(s);
        s->pc = (h << 8) | l; s->cycles += 3;
        return 0;
    }
    case 0x80: JUMP(2, F(1), 3); return 0;
    case 0x73: s->pc = (A + DPTR) & 0xFFFF; s->cycles += 4; return 0;
    case 0x40: if (CY == 1) JUMP(2, F(1), 3); else NEXT(2, 1); return 0;
    case 0x50: if (CY == 0) JUMP(2, F(1), 3); else NEXT(2, 1); return 0;
    case 0x60: if (A == 0) JUMP(2, F(1), 3); else NEXT(2, 1); return 0;
    case 0x70: if (A != 0) JUMP(2, F(1), 3); else NEXT(2, 1); return 0;
    case 0x10: case 0x20: case 0x30: {  /* JBC, JB, JNB */
        int b = F(1), v = getpin(s, b);
        int take = op != 0x30 ? v : !v;
        if (op == 0x10 && v) setbit(s, b, 0);
        if (take) JUMP(3, F(2), 3); else NEXT(3, 1);
        return 0;
    }
    case 0xB4: case 0xB5: case 0xB6: case 0xB7: {   /* CJNE */
        int a, b;
        if (op == 0xB4) { a = A; b = F(1); }
        else if (op == 0xB5) { a = A; b = rdp(s, F(1)); }
        else { a = s->iram[R(op & 1)]; b = F(1); }
        set_c(s, a < b);
        if (a != b) JUMP(3, F(2), 3); else NEXT(3, op == 0xB4 ? 1 : 2);
        return 0;
    }
    case 0xD5: {                        /* DJNZ dir,rel */
        int d = F(1), v = (rd(s, d) - 1) & 0xFF;
        wr(s, d, v);
        if (v) JUMP(3, F(2), 3); else NEXT(3, 2);
        return 0;
    }
    case 0x42: case 0x52: case 0x62: { int d = F(1); wr(s, d, logic(hi, rd(s, d), A)); NEXT(2, 1); return 0; }
    case 0x43: case 0x53: case 0x63: { int d = F(1); wr(s, d, logic(hi, rd(s, d), F(2))); NEXT(3, 1); return 0; }
    case 0x04: A = (uint8_t)(A + 1); NEXT(1, 1); return 0;
    case 0x14: A = (uint8_t)(A - 1); NEXT(1, 1); return 0;
    case 0x05: { int d = F(1); wr(s, d, rd(s, d) + 1); NEXT(2, 1); return 0; }
    case 0x15: { int d = F(1); wr(s, d, rd(s, d) - 1); NEXT(2, 1); return 0; }
    case 0x06: case 0x07: { int a = R(op & 1); s->iram[a] = (uint8_t)(s->iram[a] + 1); NEXT(1, 1); return 0; }
    case 0x16: case 0x17: { int a = R(op & 1); s->iram[a] = (uint8_t)(s->iram[a] - 1); NEXT(1, 1); return 0; }
    case 0xA3: set_dptr(s, (DPTR + 1) & 0xFFFF); NEXT(1, 1); return 0;
    case 0xA4: {
        int r = A * s->sfr[B_];
        A = r & 0xFF; s->sfr[B_] = (uint8_t)(r >> 8);
        s->sfr[PSW] = (s->sfr[PSW] & ~0x84) | (r > 0xFF ? 0x04 : 0);
        NEXT(1, 2);
        return 0;
    }
    case 0x84: {
        int a = A, b = s->sfr[B_];
        if (b == 0) s->sfr[PSW] = (s->sfr[PSW] & ~0x84) | 0x04;
        else { A = (uint8_t)(a / b); s->sfr[B_] = (uint8_t)(a % b); s->sfr[PSW] &= ~0x84; }
        NEXT(1, 6);
        return 0;
    }
    case 0xD4: {
        int a = A, c = CY;
        if ((a & 0xF) > 9 || (s->sfr[PSW] & 0x40)) a += 6;
        if ((a >> 4) > 9 || c || a > 0xFF) a += 0x60;
        if (a > 0xFF) c = 1;
        A = a & 0xFF; set_c(s, c);
        NEXT(1, 3);
        return 0;
    }
    case 0xE4: A = 0; NEXT(1, 1); return 0;
    case 0xF4: A = (uint8_t)~A; NEXT(1, 1); return 0;
    case 0x23: { int a = A; A = (uint8_t)((a << 1) | (a >> 7)); NEXT(1, 1); return 0; }
    case 0x03: { int a = A; A = (uint8_t)((a >> 1) | ((a & 1) << 7)); NEXT(1, 1); return 0; }
    case 0x33: { int a = A, c = CY; set_c(s, a >> 7); A = (uint8_t)((a << 1) | c); NEXT(1, 1); return 0; }
    case 0x13: { int a = A, c = CY; set_c(s, a & 1); A = (uint8_t)((a >> 1) | (c << 7)); NEXT(1, 1); return 0; }
    case 0xC4: { int a = A; A = (uint8_t)((a << 4) | (a >> 4)); NEXT(1, 1); return 0; }
    case 0xC3: set_c(s, 0); NEXT(1, 1); return 0;
    case 0xD3: set_c(s, 1); NEXT(1, 1); return 0;
    case 0xB3: set_c(s, 1 - CY); NEXT(1, 1); return 0;
    case 0xC2: setbit(s, F(1), 0); NEXT(2, 1); return 0;
    case 0xD2: setbit(s, F(1), 1); NEXT(2, 1); return 0;
    case 0xB2: { int b = F(1); setbit(s, b, 1 - getbit(s, b)); NEXT(2, 1); return 0; }
    case 0xA2: set_c(s, getpin(s, F(1))); NEXT(2, 1); return 0;
    case 0x92: setbit(s, F(1), CY); NEXT(2, 1); return 0;
    case 0x72: set_c(s, CY | getpin(s, F(1))); NEXT(2, 1); return 0;
    case 0x82: set_c(s, CY & getpin(s, F(1))); NEXT(2, 1); return 0;
    case 0xA0: set_c(s, CY | (1 - getpin(s, F(1)))); NEXT(2, 1); return 0;
    case 0xB0: set_c(s, CY & (1 - getpin(s, F(1)))); NEXT(2, 1); return 0;
    case 0x74: A = F(1); NEXT(2, 1); return 0;
    case 0xE5: A = (uint8_t)rdp(s, F(1)); NEXT(2, 1); return 0;
    case 0xE6: case 0xE7: A = s->iram[R(op & 1)]; NEXT(1, 1); return 0;
    case 0xF5: wr(s, F(1), A); NEXT(2, 1); return 0;
    case 0xF6: case 0xF7: s->iram[R(op & 1)] = A; NEXT(1, 1); return 0;
    case 0x75: wr(s, F(1), F(2)); NEXT(3, 1); return 0;
    case 0x76: case 0x77: s->iram[R(op & 1)] = F(1); NEXT(2, 1); return 0;
    case 0x85: { int v = rdp(s, F(1)); wr(s, F(2), v); NEXT(3, 1); return 0; }
    case 0x86: case 0x87: wr(s, F(1), s->iram[R(op & 1)]); NEXT(2, 1); return 0;
    case 0xA6: case 0xA7: s->iram[R(op & 1)] = (uint8_t)rdp(s, F(1)); NEXT(2, 1); return 0;
    case 0x90: set_dptr(s, (F(1) << 8) | F(2)); NEXT(3, 1); return 0;
    case 0x93: A = s->code[(A + DPTR) & 0xFFFF]; NEXT(1, 4); return 0;
    case 0x83: A = s->code[(A + s->pc + 1) & 0xFFFF]; NEXT(1, 3); return 0;
    case 0xE0: A = s->xram[DPTR]; NEXT(1, 2); return 0;
    case 0xE2: case 0xE3: A = s->xram[R(op & 1)]; NEXT(1, 3); return 0;
    case 0xF0: s->xram[DPTR] = A; NEXT(1, 2); return 0;
    case 0xF2: case 0xF3: s->xram[R(op & 1)] = A; NEXT(1, 3); return 0;
    case 0xC0: push(s, rdp(s, F(1))); NEXT(2, 1); return 0;
    case 0xD0: { int v = pop(s); wr(s, F(1), v); NEXT(2, 1); return 0; }
    case 0xC5: { int d = F(1), v = rd(s, d); wr(s, d, A); A = (uint8_t)v; NEXT(2, 1); return 0; }
    case 0xC6: case 0xC7: { int a = R(op & 1), v = s->iram[a]; s->iram[a] = A; A = (uint8_t)v; NEXT(1, 1); return 0; }
    case 0xD6: case 0xD7: {
        int a = R(op & 1), v = s->iram[a];
        s->iram[a] = (uint8_t)((v & 0xF0) | (A & 0x0F));
        A = (uint8_t)((A & 0xF0) | (v & 0x0F));
        NEXT(1, 1);
        return 0;
    }
    }
    return EV_BADOP;                    /* 0xA5 */
}

/* Run until an event (see the enum). stop_pc < 0: no stop address; stop_cycles < 0:
 * no cycle limit; limit: absolute step count. Same order of checks as PyEmu8051.run:
 * tick after each instruction, then stop pc, stop cycles, step limit, hook. */
int core_run(S *s, int64_t stop_pc, int64_t limit, int64_t stop_cycles)
{
    for (;;) {
        if (s->pending_tick) {
            s->pending_tick = 0;
            if (s->tick_every && s->cycles >= s->next_tick) {
                s->next_tick += s->tick_every;
                return EV_TICK;
            }
        }
        if (s->skip_checks) {           /* a hook just ran and left pc where it was */
            s->skip_checks = 0;
        } else {
            if (s->pc == stop_pc) return EV_STOP;
            if (stop_cycles >= 0 && s->cycles >= stop_cycles) return EV_CYCLES;
            if (s->steps >= limit) return EV_LIMIT;
            if (s->hookmap[s->pc & 0xFFFF]) return EV_HOOK;
        }
        if (step(s)) return EV_BADOP;
        s->steps++;
        s->pending_tick = 1;
        if (s->w_pending) return EV_WATCH;
    }
}
