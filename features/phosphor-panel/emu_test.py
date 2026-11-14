#!/usr/bin/env python3
"""Emulator tests for Phosphor Panel (see README.md).

  python3 emu_test.py unit    image diff, then every routine at its hook: the fonts and the cell map,
                              the ladder, the cell and bar painters, the home screen against
                              home_model, the volume hook, the engine tick by tick against Engine
                              (entry, counting with afterglow, the blink, exit, reversals, cancel),
                              the entry and exit logic, the mute key's two hooks, the align hooks
  Whole-firmware scenarios and the sweep run against a reference the test builds: fast-lcd
  plus the fixes this image includes (build/reference.bin), so only the theme differs.

  python3 emu_test.py tour    whole firmware from reset, lockstep with the reference: the tour, a
                              volume key per input, keys during the transitions, the flag-path
                              exits, the mute key, the status tint across input changes, the stack
                              check and stock_page_walk (every menu page, the value pages, BT clear,
                              RESET, the front-panel keys that draw big text at home, a power cycle)
  Every emulator of this image traps the stock big glyph painters (BIG_FONT_PAINTERS): the stock
  big font's bytes hold the theme's data, so reaching one fails the run.
  python3 emu_test.py int1    INT1 receiver event at a Vol+ press, 100 offsets, against the reference
  python3 emu_test.py sweep   all 256 IR commands in five states, against the reference (the mute
                              key where it differs on purpose: against the reference muted from home)
  python3 emu_test.py         all four
"""
import multiprocessing as mp
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
import uitest as ut                                             # noqa: E402
from ao300 import Amp as StockAmp, CLOCK_HZ, NEC_POWER, NEC_UP, NEC_MENU, NEC_DOWN, NEC_SOURCE, \
    NEC_VOL_UP, NEC_VOL_DOWN, STATE_KEY                          # noqa: E402
import build_patch as bp                                         # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
import pfont                                                     # noqa: E402
import uikit                                                     # noqa: E402

BASE = open(bp.BASE_IMAGE, "rb").read()
NEW = open(bp.OUT_IMAGE, "rb").read()

# ---- the stock big font is dead in this image --------------------------------------------------
BIG_FONT_PAINTERS = {0x3F3C: "big_glyph_paint", 0x3F2A: "bignum_digit"}


class BigFontReached(AssertionError):
    pass


def trap_big_font(e):
    for pc, name in BIG_FONT_PAINTERS.items():
        def trap(em, name=name, pc=pc):
            sp = em.sfr[0x81]
            words = ["%02X%02X" % (em.iram[i], em.iram[i - 1]) for i in range(sp, 0x88, -2)]
            raise BigFontReached("%s (0x%04X) reached on page %d; stack (top first): %s"
                                 % (name, pc, em.iram[0x45], " ".join(words)))
        e.hooks[pc] = trap


def track_lamps(e):
    """The format and EQ lamps as last drawn (e.lamp_fmt, e.lamp_eq): a stock sequence draws them when it
    draws them, not when RAM changes (the format poll on the volume page), as stock's tags."""
    e.lamp_fmt = e.lamp_eq = None

    def at(em):
        x = (em.R(2) << 8) | em.R(3)
        text = buffer_text(em, bp.PP_TAG, 6)
        if x == bp.FMT_X:
            em.lamp_fmt = text
        elif x == bp.EQ_X:
            em.lamp_eq = text
    e.hooks[LAB["pp_lamp_at"]] = at

    def clear(em):
        em.lamp_fmt = ""
    e.hooks[LAB["pp_fmt_clear"]] = clear


class Amp(StockAmp):
    """ao300.Amp, with the big-font trap on every amp running this image, and the lamps tracked."""
    def __init__(self, image, **kw):
        super().__init__(image, **kw)
        if image == NEW:
            trap_big_font(self.e)
            track_lamps(self.e)


def reference_image():
    """fast-lcd plus the fixes this image includes, without the theme."""
    import features
    from asm51 import Asm
    path = os.path.join(HERE, "build", "reference.bin")

    def assemble():
        a = Asm(bp.CODE_ADDR)
        features.emit(a, bp.INCLUDES)
        return a.resolve(), a.labels, a
    uikit.build_image(base_path=bp.BASE_IMAGE, base_sha=bp.BASE_SHA, code_addr=bp.CODE_ADDR, assemble=assemble,
                      hooks=features.hooks(bp.INCLUDES), patches=features.patches(bp.INCLUDES),
                      version_text="ref", out_image=path, out_listing=path + ".asm",
                      title="reference: fast-lcd + %s" % ", ".join(bp.INCLUDES), label_prefixes=())
    return open(path, "rb").read()


REF = reference_image()
_ASM = bp.assemble()
LAB, BLOCKS = _ASM[1], _ASM[3]
W, H = 320, 170
STEP_END = 0x5B2D                        # main_tasks_on, after the lcall uk_tasks (0x5B2A)
STEP_LIMIT = 8.0                         # ms per animated tick
NEC_MUTE = 0x09
fails = []
STEP_MS = {}


def check(name, ok, detail=""):
    print("  %-72s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def emu(theme=(0xFF, 0xFF), img=NEW):
    e = ut.emu(img, theme)
    if img == NEW:
        trap_big_font(e)
    return e


px, screen, fill_screen, ink_in = ut.px, ut.screen, ut.fill_screen, ut.ink_in


def ms_of(e, fn):
    c0 = e.cycles
    fn()
    return (e.cycles - c0) * 1000 / CLOCK_HZ


def call_a(e, label, a):
    e.sfr[0xE0] = a
    e.call(LAB[label])


# ---- stock facts the models need -----------------------------------------------------------------
_TAGS = {}


def _string_at(img, addr):
    return img[addr:img.index(0, addr)].decode("latin-1")


def eq_tag_string(eq):
    """The string home_draw_eq_tag (0x49A1) paints for EQ eq (RAM 0x39)."""
    if ("eq", eq) not in _TAGS:
        e = ut.Emu8051(BASE)
        e.sfr[0x81] = 0x88
        e.iram[0x39] = eq
        got = []
        e.hooks[0x4F18] = lambda em: (got.append((em.R(2) << 8) | em.R(1)), em.ret())
        e.call(0x49A1)
        _TAGS[("eq", eq)] = _string_at(BASE, got[0])
    return _TAGS[("eq", eq)]


def format_tag_string(inp, fmt, sub):
    """The string home_draw_format_tag (0x41CA) paints for input inp, format fmt (RAM 0x3D) and RAM
    0x75, or None when it only clears the box."""
    key = ("fmt", inp, fmt, sub)
    if key not in _TAGS:
        e = ut.Emu8051(BASE)
        e.sfr[0x81] = 0x88
        e.iram[0x47], e.iram[0x3D], e.iram[0x75], e.iram[0x7E] = inp, fmt, sub, fmt
        got = []
        e.hooks[0x4F20] = lambda em: (got.append((em.R(2) << 8) | em.R(1)), em.ret())
        e.hooks[0x0026] = lambda em: em.ret()
        e.call(0x41CA)
        _TAGS[key] = _string_at(BASE, got[0]) if got else None
    return _TAGS[key]


def accent(theme):
    return bp.MINT if theme == (0xFF, 0xFF) else (theme[0] << 8) | theme[1]


def buffer_text(e, addr, n=25):
    raw = bytes(e.xram[addr:addr + n])
    return raw.split(b"\0")[0].decode("latin-1")


def muted(e):
    return bool(e.iram[0x22] & 0x02)


def firmware_strings():
    return ut.firmware_strings(BASE)


def sample_rate_strings():
    return ut.sample_rate_strings(BASE)


def volume_of(e):
    return min(60, e.iram[0x31] if e.iram[0x2B] == 1 else e.iram[0x52])


# ---- the engine: an independent model --------------------------------------------------------------
# What pp_step does to the XDATA state every tick (build_patch.py's docstring and the spec), in
# Python. An Engine is read from an emulator's XDATA (xstate) and stepped in lockstep with pp_step;
# the screen it implies is parts_for / compose.
EL_N = bp.EL_N
E_NAME, E_VOL, E_SEG, E_BAR = bp.EL_NAME, bp.EL_VOL, bp.EL_SEG, bp.EL_BAR


class Engine:
    FIELDS = ("vol", "show", "st", "act", "tick", "blink", "fl", "scan")

    def __init__(self, **kw):
        self.volume = 0                  # the amp's volume (RAM): the slot's draw at a settle syncs the counter to it
        self.vol = self.show = 0
        self.st = self.act = self.tick = self.blink = self.fl = self.scan = 0
        self.lv = [0] * EL_N
        self.tg = [0] * EL_N
        self.muted = False
        self.mov = 0
        self.paints = []
        for k, v in kw.items():
            setattr(self, k, v)

    def copy(self):
        m = Engine(**{k: getattr(self, k) for k in self.FIELDS})
        m.lv, m.tg, m.muted, m.volume = list(self.lv), list(self.tg), self.muted, self.volume
        return m

    def state(self):
        return tuple(getattr(self, k) for k in self.FIELDS) + (tuple(self.lv), tuple(self.tg))

    # the entry points
    def enter_vol(self):
        if self.st in (1, 2):
            return
        self.scan = bp.BAR_N if self.st == 3 else 0
        self.st, self.act = 1, 1

    def exit(self):
        self.st, self.act = 3, 1

    def stop(self, vol):
        self.st = self.act = self.blink = self.fl = self.scan = 0
        self.lv = [0] * EL_N
        self.tg = [0] * EL_N
        self.vol = self.show = vol

    def draw_volume(self, vol):
        self.vol = vol
        if self.st == 0:
            self.show = vol

    # one tick
    def step(self):
        self.paints = []
        if not self.act:
            return
        self.tick = (self.tick + 1) & 0xFF
        if self.tick % bp.COUNT_EVERY == 0 and self.show != self.vol:
            self.show += 1 if self.vol > self.show else -1
        intent = self.st in (1, 2)
        self.blink = (self.blink + 1) % bp.BLINK_PERIOD if self.muted else 0
        if self.st == 1:
            self.scan = min(bp.BAR_N, self.scan + bp.SCAN_STEP)
        painted = self.statics(intent)
        self.retarget(intent)
        if painted:
            self.mov = 1
            return
        self.move()
        self.settle()

    def statics(self, intent):
        if intent:
            if not self.fl & bp.FL_VOL:
                self.fl = (self.fl | bp.FL_VOL) & ~bp.FL_SLOT
                self.paints += ["slot_clear", "stat_clear", "marks"]
                for i in range(bp.BAR_N):
                    if self.lv[E_BAR + i] == 0:
                        self.lv[E_BAR + i] = bp.GHOST
                    self.paints.append(("bar", i))
                return True
            if not self.fl & bp.FL_DB and self.lv[E_NAME] == 0:
                self.fl |= bp.FL_DB
                self.paints.append("db")
                return True
            return False
        if self.fl & bp.FL_DB:
            self.fl &= ~bp.FL_DB
            self.paints.append("db_clear")
            return True
        if self.fl & bp.FL_VOL:
            self.fl &= ~bp.FL_VOL
            self.paints.append("marks_clear")
            return True
        return False

    def retarget(self, intent):
        cells_black = all(self.lv[i] == 0 for i in range(E_VOL, E_BAR)) and not self.fl & bp.FL_DB
        name_black = self.lv[E_NAME] == 0
        if not intent:
            self.tg[E_NAME] = 7 if cells_black else 0
            lit_black = all(self.lv[i] == 0 for i in range(E_SEG + 14, E_BAR))
            for i in range(E_VOL, EL_N):
                self.tg[i] = bp.GHOST if (E_SEG <= i < E_SEG + 14 and not lit_black) else 0
            return
        self.tg[E_NAME] = 0
        if not name_black:
            for i in range(E_VOL, E_BAR):
                self.tg[i] = 0
        else:
            self.tg[E_VOL] = 7
            tens, ones = divmod(self.show, 10)
            mt = bp.SEG_TAB[tens] if tens else 0
            mo = bp.SEG_TAB[ones]
            if self.muted and self.blink >= bp.BLINK_ON:
                mt = mo = 0
            for c in range(4):
                for s in range(7):
                    lit = c >= 2 and ((mt if c == 2 else mo) >> s) & 1
                    self.tg[E_SEG + 7 * c + s] = 7 if lit else bp.GHOST
        n = 0 if self.muted else bp.BAR_LIT[self.show]
        lim = min(n, self.scan)
        for i in range(bp.BAR_N):
            self.tg[E_BAR + i] = 7 if i < lim else bp.GHOST

    def move(self):
        self.mov = 0
        dirty = set()
        for i in range(EL_N):
            lv, tg = self.lv[i], self.tg[i]
            if lv == tg:
                continue
            self.mov = 1
            if lv < tg:
                ramp = i == E_NAME or (self.st == 1 and i < E_BAR)
                if ramp:
                    if self.tick % bp.RATE_RISE:
                        continue
                    lv += 1
                else:
                    lv = tg
            else:
                rate = bp.RATE_GLOW if self.st == 2 else bp.RATE_FALL
                if self.tick % rate:
                    continue
                lv -= 1
            self.lv[i] = lv
            if i == E_NAME:
                self.paints.append(("name", lv))
            elif i == E_VOL:
                self.paints.append(("vol", lv))
            elif i < E_BAR:
                dirty.add((i - E_SEG) // 7)
            else:
                self.paints.append(("bar", i - E_BAR))
        self.paints += [("cell", c) for c in sorted(dirty)]

    def settle(self):
        if self.mov:
            return
        if self.st == 1 and self.scan == bp.BAR_N and self.fl & (bp.FL_DB | bp.FL_VOL) == bp.FL_DB | bp.FL_VOL:
            self.st = 2
        elif self.st == 3 and not self.fl & (bp.FL_DB | bp.FL_VOL):
            self.st = self.act = 0
            self.fl |= bp.FL_SLOT
            self.vol = self.show = self.volume          # pp_hvol with the engine idle
            self.paints += ["slot", "status"]


def xstate(e):
    """The Engine as the emulator's XDATA holds it."""
    x = e.xram
    m = Engine(vol=x[bp.PP_VOL], show=x[bp.PP_SHOW], st=x[bp.PP_ST], act=x[bp.PP_ACT], tick=x[bp.PP_TICK],
               blink=x[bp.PP_BLINK], fl=x[bp.PP_FL], scan=x[bp.PP_SCAN])
    m.lv = [x[bp.PP_LV + i] & 7 for i in range(EL_N)]
    m.tg = [(x[bp.PP_LV + i] >> 4) & 7 for i in range(EL_N)]
    m.muted = muted(e)
    m.volume = volume_of(e)
    return m


def settled_home():
    m = Engine(fl=bp.FL_SLOT)
    m.lv[E_NAME] = m.tg[E_NAME] = 7
    return m


def settled_vol(show, mute=False, blink=0):
    m = Engine(st=2, act=1, fl=bp.FL_DB | bp.FL_VOL, scan=bp.BAR_N, show=show, vol=show, blink=blink)
    m.muted = mute
    m.retarget(True)
    m.lv = list(m.tg)
    return m


# ---- the screen for an engine state ---------------------------------------------------------------
def fill(fb, x, y, w, h, c):
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            fb[yy][xx] = c


def status_ink_of(e, ph):
    """The status line's colour: 7/8 ph, or red when the loader's signal check found none on a digital
    input (analogue inputs 6 and 8 show "Analog input")."""
    return bp.status_ink(ph) if e.xram[bp.PP_SIG] & 1 or e.iram[0x47] in (6, 8) else bp.RED_LIT


def parts_for(e, m, mute=None, name=None):
    """{element: {(x, y): colour}} for the engine state m on the amp's RAM in e: the row's lamps
    (the MUTE lamp as the mute state `mute`, default e's), the slot and the status line when
    FL_SLOT, the name at its level (text `name`, default the buffer's), the cells, "VOL", "dB" when
    FL_DB, the bar, the marks when FL_VOL."""
    ir = e.iram
    ph = accent((ir[0x48], ir[0x49]))
    lad = bp.ladder(ph)
    if mute is None:
        mute = muted(e)
    parts = {}

    def part(key, draw):
        fb = [[None] * W for _ in range(H)]
        draw(fb)
        parts[key] = {(x, y): fb[y][x] for y in range(H) for x in range(W) if fb[y][x] is not None}

    def lamp(fb, text, x, end):
        fill(fb, x, bp.ROW_TY, end - x + 1, bp.PF_ROW.H, 0)
        if text:
            bp.PF_ROW.render(fb, text, x, bp.ROW_TY, ph, 0)
    part("inp", lambda fb: lamp(fb, bp.SHORT_NAMES.get(ir[0x47], ""), bp.INP_X, bp.INP_END))
    fmt = getattr(e, "lamp_fmt", None)
    if fmt is None:
        fmt = format_tag_string(ir[0x47], ir[0x3D], ir[0x75])
        fmt = (fmt or "")[:5].rstrip(" ") if fmt is not None else ""
    eq = getattr(e, "lamp_eq", None)
    if eq is None:
        eq = eq_tag_string(ir[0x39])[:5].rstrip(" ")
    part("fmt", lambda fb: lamp(fb, fmt, bp.FMT_X, bp.FMT_END))
    part("eq", lambda fb: lamp(fb, eq, bp.EQ_X, bp.EQ_END))
    part("mute", lambda fb: bp.PF_ROW.render(fb, "MUTE", bp.MUTE_RIGHT, bp.ROW_TY, bp.RED_LIT if mute else bp.RED_DARK, 0, align=1))

    def slot(fb):
        fill(fb, bp.SLOT_X0, bp.SLOT_Y0, bp.SLOT_X1 - bp.SLOT_X0 + 1, bp.SLOT_Y1 - bp.SLOT_Y0 + 1, 0)
        if m.fl & bp.FL_SLOT:
            ch = "M" if mute else ("S" if ir[0x2B] == 1 else "H")
            bp.PF_ICON.render(fb, ch, bp.ICON_X, bp.ICON_Y, bp.RED_LIT if mute else ph, 0)
            bp.PF_ROW.render(fb, str(volume_of(e)), bp.HVOL_X, bp.ROW_TY, ph, 0)
    part("slot", slot)

    def status(fb):
        if m.fl & bp.FL_SLOT:
            bp.PF_STATUS.render(fb, buffer_text(e, bp.SMALL_BUF), bp.STAT_CX, bp.STAT_Y, status_ink_of(e, ph), 0, align=2)
    part("status", status)
    text = buffer_text(e, bp.BIG_BUF) if name is None else name

    def name_draw(fb):
        if m.lv[E_NAME]:
            bp.PF_NAME.render(fb, text, bp.name_x(bp.PF_NAME.width(text)), bp.HNAME_Y, lad[m.lv[E_NAME]], 0)
    part("name", name_draw)
    # what is not lit paints nothing (the screen is black there, or holds what is lit over it)
    for c in range(4):
        levels = m.lv[E_SEG + 7 * c:E_SEG + 7 * c + 7]
        part(("cell", c), lambda fb, c=c, levels=levels: any(levels) and [fb[y].__setitem__(x, v) for (x, y), v in
                                                                         bp.cell_pixels(levels, ph, bp.CELL_XS[c]).items()])
    part("vol", lambda fb: m.lv[E_VOL] and bp.PF_ROW.render(fb, "VOL", bp.VOL_X, bp.VOL_Y, lad[m.lv[E_VOL]], 0))
    part("db", lambda fb: m.fl & bp.FL_DB and bp.PF_ROW.render(fb, "dB", bp.DB_X, bp.VOL_Y, lad[bp.GHOST], 0))
    part("bar", lambda fb: [fill(fb, bp.BAR_X0 + bp.BAR_PITCH * i, bp.BAR_Y, bp.BAR_W, bp.BAR_H, lad[m.lv[E_BAR + i]])
                            for i in range(bp.BAR_N) if m.lv[E_BAR + i]])

    def marks(fb):
        if m.fl & bp.FL_VOL:
            for t, x in bp.MARKS:
                bp.PF_ROW.render(fb, t, x, bp.MARK_Y, bp.marks_ink(ph), 0, align=2)
    part("marks", marks)
    return parts


def compose(parts, only=None):
    s = [[0] * H for _ in range(W)]
    for k, pix in parts.items():
        if only is None or k in only:
            for (x, y), c in pix.items():
                s[x][y] = c
    return s


def model_screen(e, m, **kw):
    return compose(parts_for(e, m, **kw))


def home_model(e, **kw):
    return model_screen(e, settled_home(), **kw)


def home_ok(e, **kw):
    return screen(e) == home_model(e, **kw)


def diff(s, m):
    for x in range(W):
        for y in range(H):
            if m[x][y] != s[x][y]:
                return "(first difference at %d,%d: %04X, model %04X)" % (x, y, s[x][y], m[x][y])
    return ""


def home_diff(e, **kw):
    return diff(screen(e), home_model(e, **kw))


def vol_model(e, show=None, mute=None, blink=None, **kw):
    m = settled_vol(e.xram[bp.PP_SHOW] if show is None else show, muted(e) if mute is None else mute,
                    e.xram[bp.PP_BLINK] if blink is None else blink)
    return model_screen(e, m, mute=mute, **kw)


def vol_settled(e):
    """On the volume page, nothing moving: the screen is vol_model's."""
    m = xstate(e)
    return m.st == 2 and m.lv == m.tg and screen(e) == vol_model(e)


def vol_diff(e, **kw):
    return diff(screen(e), vol_model(e, **kw))


def xscreen_ok(e, **kw):
    """The screen is what the XDATA state implies (any quiet moment of a transition)."""
    return screen(e) == model_screen(e, xstate(e), **kw)


def xscreen_diff(e, **kw):
    return diff(screen(e), model_screen(e, xstate(e), **kw))


# ---- states --------------------------------------------------------------------------------------
def home_state(e, inp=1, out=1, vol=32, hp=20, mute=False, eq=1, fmt=2, sub=2, status="96kHz", theme=None, sig=True):
    ir = e.iram
    ir[0x45], ir[0x4F] = 1, 1
    e.xram[bp.PP_SIG] = 1 if sig else 0
    ir[0x47], ir[0x2B], ir[0x31], ir[0x52], ir[0x39], ir[0x3D], ir[0x75] = inp, out, vol, hp, eq, fmt, sub
    ir[0x7E] = fmt
    ir[0x22] = (ir[0x22] & ~0x02) | (0x02 if mute else 0)
    if theme:
        ir[0x48], ir[0x49] = theme
    for k, ch in enumerate(status.encode() + b"\0"):
        e.xram[bp.SMALL_BUF + k] = ch
    e.call(LAB["pp_stop"])


def refresh_draw(e):
    """What home_refresh_periodic draws once its loader has run (pp_hold's stock path: home_refresh,
    then the status line at y 135 in the loader's tint)."""
    e.call(LAB["hh_stock"])


def home_draw(e):
    return ms_of(e, lambda: refresh_draw(e))


def home_at(inp=2, vol=32, theme=(0xFF, 0xFF), **kw):
    """A fresh emulator at a drawn home screen."""
    e = emu(theme)
    home_state(e, inp=inp, vol=vol, **kw)
    refresh_draw(e)
    return e


def vol_key(e, m, v):
    """What a volume key leaves: RAM 0x31 = v, then volpage_draw_volume (0x5936); the model follows."""
    e.iram[0x31] = v
    e.setR(7, v); e.call(0x5936)
    if m is not None:
        m.volume = v
        m.draw_volume(v)


def run_ticks(e, m, n, limit=STEP_LIMIT, label=""):
    """n ticks of pp_step and Engine.step in lockstep; after each: the XDATA state = the model's and the
    screen = the state's. Returns (bad, worst ms, the ticks' ms)."""
    bad, worst, times = [], 0.0, []
    for k in range(1, n + 1):
        t = ms_of(e, lambda: e.call(LAB["pp_step"]))
        times.append(t)
        worst = max(worst, t)
        m.step()
        got = xstate(e)
        if got.state() != m.state():
            bad.append((label, k, "state", [(f, getattr(got, f), getattr(m, f)) for f in Engine.FIELDS if getattr(got, f) != getattr(m, f)],
                        [(i, got.lv[i], m.lv[i], got.tg[i], m.tg[i]) for i in range(EL_N) if (got.lv[i], got.tg[i]) != (m.lv[i], m.tg[i])][:4]))
            break
        if not xscreen_ok(e):
            bad.append((label, k, "screen", xscreen_diff(e), m.paints[:4]))
            break
        if t > limit:
            bad.append((label, k, "time %.2f ms" % t))
    return bad, worst, times


# ---- image diff -------------------------------------------------------------------------------
def image_diff():
    print("Image diff vs fast-lcd")
    vp = bp.VERSION_PTR_ADDR
    want = set()
    for addr, orig, op, target in bp.HOOKS:
        new = bytes([op, LAB[target] >> 8, LAB[target] & 0xFF])
        check("hook 0x%04X -> %s" % (addr, target), NEW[addr:addr + 3] == new, NEW[addr:addr + 3].hex(" "))
        want |= {addr + k for k in range(3) if orig[k] != new[k]}
    for s in bp.VOL_ENTRY_SITES:
        new = bp.vol_entry_bytes(LAB["pp_enter_vol"])
        check("volume entry 0x%04X -> lcall pp_enter_vol ; sjmp 0x%04X" % (s, s + len(bp.VOL_ENTRY_ORIG)),
              NEW[s:s + 5] == new, NEW[s:s + 5].hex(" "))
        want |= {s + k for k in range(5) if bp.VOL_ENTRY_ORIG[k] != new[k]}
    for addr, orig, fn, note in bp.FIX_PATCHES:
        new = fn(LAB)
        check("patch 0x%04X: %s" % (addr, note), NEW[addr:addr + len(new)] == new, NEW[addr:addr + len(new)].hex(" "))
        want |= {addr + k for k in range(len(new)) if orig[k] != new[k]}
    for addr, orig, new, _ in BLOCKS:
        check("data block 0x%04X..0x%04X: %s in the stock big font's place (%d of %d bytes)"
              % (addr, addr + len(new) - 1, ", ".join(f.name for f in bp.HOLE_FONTS), len(new), bp.FONT_HOLE_END - bp.FONT_HOLE),
              NEW[addr:addr + len(new)] == new and addr == bp.FONT_HOLE and addr + len(new) <= bp.FONT_HOLE_END)
        want |= {addr + k for k in range(len(new)) if orig[k] != new[k]}
    check("the rest of the big font's place and the small font are stock",
          NEW[bp.FONT_HOLE + len(BLOCKS[0][2]):bp.FONT_HOLE_END] == BASE[bp.FONT_HOLE + len(BLOCKS[0][2]):bp.FONT_HOLE_END]
          and NEW[uikit.FONT_SMALL:bp.FONT_HOLE] == BASE[uikit.FONT_SMALL:bp.FONT_HOLE])
    changed = {i for i in range(len(BASE)) if BASE[i] != NEW[i]} - {vp + 1, vp + 3}
    check("inside the base image only the hooks, the included patches and the data block changed (plus version pointer)",
          changed == want, str(sorted("%04X" % i for i in changed ^ want)))
    ver = (NEW[vp + 1] << 8) | NEW[vp + 3]
    check("version pointer -> %r" % bp.VERSION_TEXT,
          NEW[ver:ver + len(bp.VERSION_TEXT) + 1] == bp.VERSION_TEXT.encode() + b"\0")
    check("gap up to 0x%04X left erased" % bp.CODE_ADDR, all(b == 0xFF for b in NEW[len(BASE):bp.CODE_ADDR]))
    check("image ends below 0xF400", len(NEW) <= 0xF400, "(%d bytes)" % len(NEW))
    check("new XDATA state inside 0x0100..0x01FF", 0x0100 <= bp.PP_N and bp.XDATA_END <= 0x0200)
    import re
    java = open(os.path.join(ROOT, "tools", "disasm", "SmslAo300Labels.java")).read()
    named = {n: int(a, 16) for a, n in re.findall(r'\{0x([0-9A-F]{4}), "(pp_\w+)"\}', java)}
    wrong = sorted(k for k in named if named[k] != LAB.get(k))
    check("SmslAo300Labels.java: the %d pp_ labels match this build" % len(named), named and not wrong, str(wrong))


# ---- fonts, the ladder, the painters --------------------------------------------------------------
def test_fonts():
    print("\nthe fonts and the cell map")
    adv_ok = all((adv % bp.GRID) == 0 for adv, _, _, _ in bp.PF_NAME.glyphs.values())
    check("pf_name: every cell (advance with the spacing baked in) a multiple of %d" % bp.GRID, adv_ok)
    x0 = bp.name_x(bp.PF_NAME.width("OPTICAL"))
    fb = [[0] * W for _ in range(H)]
    bp.PF_NAME.render(fb, "OPTICAL", x0, bp.HNAME_Y, 0xFFFF, 0)
    grid_ok = all(fb[y][x] == 0 for y in range(H) for x in range(W) if x % bp.GRID == 0 or y % bp.GRID == bp.GRID - 1)
    check("pf_name: a name at its x has no ink on the grid's columns (x = 0 mod %d) and rows (y = %d mod %d)"
          % (bp.GRID, bp.GRID - 1, bp.GRID), grid_ok and x0 % bp.GRID == 1 and ink_in.__name__ == "ink_in")
    check("name_x: every big text at least at x 1, centred within a grid step, inside the screen",
          all(1 <= bp.name_x(bp.PF_NAME.width(t)) and bp.name_x(bp.PF_NAME.width(t)) % 3 == 1 and
              abs(bp.name_x(bp.PF_NAME.width(t)) + bp.PF_NAME.width(t) // 2 - 160) <= 3 for t in bp.big_texts()
              if bp.PF_NAME.width(t) <= 318))
    segs = {s for col in bp.CELL_GRID for s, _ in col}
    cov = {}
    for col in bp.CELL_GRID:
        for s, lv in col:
            cov[s] = cov.get(s, 0) + (1 if lv == 3 else 0)
    check("cell map: 7 segments and background, each segment %d..%d full-coverage pixels, %d bytes run-length"
          % (min(cov[s] for s in range(7)), max(cov[s] for s in range(7)), len(bp.CELL_MAP)),
          segs == set(range(8)) and min(cov[s] for s in range(7)) > 60 and len(bp.CELL_MAP) < 1200)
    # the lit sets spell the digits: a segment lit in d is one of SEGS[d]
    check("seg_tab: the mock's SEGS for 0..9", bp.SEG_TAB == [0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F])
    check("bar_tab: round(50 v / 60) for 0..60, 0 and 50 at the ends", bp.BAR_LIT[0] == 0 and bp.BAR_LIT[60] == 50
          and all(abs(bp.BAR_LIT[v] - v * 50 / 60) <= 0.5 for v in range(61)))


def test_painters():
    print("\npp_ladder, pp_cell, pp_bar")
    for theme in ((0xFF, 0xFF), (0x07, 0xE0), (0xF8, 0x1F)):
        e = emu(theme)
        e.call(LAB["pp_ladder"])
        got = [(e.xram[bp.PP_LAD + 2 * k] << 8) | e.xram[bp.PP_LAD + 2 * k + 1] for k in range(8)]
        check("theme %02X%02X: the ladder = ladder() (%s)" % (theme + (" ".join("%04X" % c for c in got),)),
              got == bp.ladder(accent(theme)))
    rnd = random.Random(7)
    bad, worst = [], 0.0
    for n in range(24):
        theme = rnd.choice([(0xFF, 0xFF), (0x07, 0xE0), (0x33, 0xBF)])
        e = emu(theme)
        fill_screen(e, 0x1234)
        e.call(LAB["pp_ladder"])
        c = rnd.randrange(4)
        levels = [rnd.randrange(8) for _ in range(7)]
        for s in range(7):
            e.xram[bp.PP_LV + bp.EL_SEG + 7 * c + s] = (rnd.randrange(8) << 4) | levels[s]
        worst = max(worst, ms_of(e, lambda: call_a(e, "pp_cell", c)))
        want = bp.cell_pixels(levels, accent(theme), bp.CELL_XS[c])
        ok = all(px(e, x, y) == want.get((x, y), 0x1234) for x in range(W) for y in range(H))
        if not ok:
            bad.append((theme, c, levels))
    check("24 random cells (3 tints, random levels): pixels = cell_pixels, nothing outside the cell", not bad, str(bad[:2]))
    check("a cell in %.2f ms" % worst, worst < 2.0)
    e = emu()
    fill_screen(e, 0x1234)
    e.call(LAB["pp_ladder"])
    bad = []
    for i in (0, 1, 17, 49):
        e.setR(6, 0xAB); e.setR(7, 0xCD)
        call_a(e, "pp_bar", i)
        x = bp.BAR_X0 + bp.BAR_PITCH * i
        if not all(px(e, xx, yy) == 0xABCD for xx in range(x, x + bp.BAR_W) for yy in range(bp.BAR_Y, bp.BAR_Y + bp.BAR_H)):
            bad.append(i)
    n = sum(1 for x in range(W) for y in range(H) if px(e, x, y) == 0xABCD)
    check("pp_bar: cells 0, 1, 17, 49 at x %d + %d i, %d x %d, nothing else" % (bp.BAR_X0, bp.BAR_PITCH, bp.BAR_W, bp.BAR_H),
          not bad and n == 4 * bp.BAR_W * bp.BAR_H)


# ---- the home screen --------------------------------------------------------------------------------
def test_home():
    print("\nhome screen (home_refresh + the status line) against home_model")
    cases = [dict(inp=i) for i in range(1, 9)] + [dict(out=2, hp=7), dict(mute=True), dict(mute=True, out=2)]
    cases += [dict(eq=q) for q in (0, 2, 3, 4, 5, 6, 7, 8, 9)]
    cases += [dict(fmt=f, sub=u) for f in (0, 1, 3, 4, 5, 6) for u in (2, 3, 4, 5)]
    cases += [dict(vol=v) for v in (0, 5, 9, 10, 47, 60)]
    cases += [dict(status=t) for t in ("No signal", "Searching...", "2.8224MHz", "Analog input", "", "Digital input")]
    cases += [dict(status="No signal", sig=False), dict(inp=4, status="Searching...", sig=False),
              dict(inp=6, status="Analog input", sig=False), dict(inp=8, status="Analog input", sig=False)]
    bad, worst = [], 0
    for c in cases:
        for theme in ((0xFF, 0xFF), (0x07, 0xE0)):
            e = emu(theme)
            home_state(e, **c)
            worst = max(worst, home_draw(e))
            if not home_ok(e):
                bad.append((c, theme, home_diff(e)))
    check("%d states x 2 tints (inputs, outputs, mute, EQ, formats, volumes, status lines, no signal): = home_model"
          % len(cases), not bad, str(bad[:2]))
    check("a whole home in %.1f ms (the stock refresh: about 45)" % worst, worst < 25)
    e = emu(); home_state(e); home_draw(e)
    e.lcd.save_png(os.path.join(HERE, "build", "unit_home.png"))
    m = xstate(e)
    check("after the draw: the engine idle, the name at 7 = target, FL_SLOT, nothing else lit",
          m.st == 0 and m.act == 0 and m.lv[E_NAME] == 7 and m.tg[E_NAME] == 7 and m.fl == bp.FL_SLOT and
          all(v == 0 for v in m.lv[1:]) and m.show == m.vol == 32)
    bad = []
    for a_, b_ in ((dict(inp=2, vol=45, fmt=4, sub=3, status="No signal", mute=True),
                    dict(inp=1, vol=5, fmt=2, status="48kHz")),
                   (dict(inp=3, fmt=4, sub=4), dict(inp=4, status="Searching...")),
                   (dict(out=2, hp=60), dict(out=1, vol=1)),
                   (dict(inp=1, status="22.5792MHz"), dict(inp=6, status="Analog input")),
                   (dict(inp=6, status="Analog input"), dict(inp=5, status="")),
                   (dict(inp=3), dict(inp=4)), (dict(inp=8), dict(inp=2))):
        e = emu()
        home_state(e, **a_); home_draw(e)
        home_state(e, **b_); home_draw(e)
        if not home_ok(e):
            bad.append((a_, b_, home_diff(e)))
    check("home over a different home: = home_model of the second (the name's sides, the slots, the lamps)", not bad, str(bad[:2]))
    strings = sorted(set(firmware_strings() + sample_rate_strings()))
    bad = []
    for t in strings:
        for buf, y, entry, part in ((bp.SMALL_BUF, bp.STATUS_Y, 0x3A53, "status"), (bp.BIG_BUF, bp.NAME_Y, 0x298B, "name")):
            if buf == bp.BIG_BUF and (t != t.upper() or not set(t) <= set(bp.NAME_CHARS) or t in bp.wide_texts()):
                continue
            e = emu(); home_state(e)
            fill_screen(e, 0x1234)
            e.xram[bp.PP_FL] = bp.FL_SLOT
            for k, ch in enumerate(t.encode() + b"\0"):
                e.xram[buf + k] = ch
            e.setR(6, 0); e.setR(7, y)
            e.call(entry)
            pix = parts_for(e, settled_home())[part]
            if part == "name":                    # pp_name also draws the input and format lamps
                allp = parts_for(e, settled_home())
                pix.update(allp["inp"])
                pix.update(allp["fmt"])
                rows = range(bp.HNAME_Y, bp.HNAME_Y + bp.PF_NAME.H)
                rows2 = range(bp.ROW_TY, bp.ROW_TY + bp.PF_ROW.H)
                cols2 = set(range(bp.INP_X, bp.INP_END + 1)) | set(range(bp.FMT_X, bp.FMT_END + 1))
            else:
                rows = range(bp.STAT_Y, bp.STAT_Y + bp.PF_STATUS.H)
                rows2, cols2 = range(0), range(0)
            ok = all(px(e, x, yy) == pix.get((x, yy), 0) for x in range(W) for yy in rows) and \
                all(px(e, x, yy) == pix.get((x, yy), 0) for x in cols2 for yy in rows2) and \
                all(px(e, x, yy) == 0x1234 for x in range(W) for yy in range(H) if yy not in rows and not (yy in rows2 and x in cols2))
            if not ok:
                bad.append((t, part))
    check("%d firmware strings as the status line and the name (capitals): the element, the rest of its rows "
          "black, nothing else drawn" % len(strings), not bad, str(bad[:4]))
    bad = []
    for t in ("USB", "BT", "S-BASS", "MQA."):
        got = []
        for img in (BASE, NEW):
            e = emu(img=img); e.iram[0x45] = 1; e.iram[0x22] = 0x10
            if img == NEW:
                e.call(LAB["pp_stop"])
            for k, ch in enumerate(t.encode() + b"\0"):
                e.xram[bp.BIG_BUF + k] = ch
            e.setR(6, 0); e.setR(7, bp.NAME_Y)
            e.call(0x298B)
            got.append(e.iram[0x22] & 0x10)
        if got[0] != got[1]:
            bad.append(t)
    check("page-1 name: 0x22.4 left as big_text_render's scan leaves it", not bad, str(bad))


def status_tint(e):
    cols = {px(e, xx, yy) for xx in range(W) for yy in range(bp.STAT_Y, bp.STAT_Y + bp.PF_STATUS.H)}
    lit = bp.status_ink(accent((e.iram[0x48], e.iram[0x49])))
    return bp.RED_LIT if bp.RED_LIT in cols else lit if lit in cols else None


def test_status_tint():
    print("\nthe status line's tint: red only for the text the status loader's no-signal check decided")
    lit = bp.status_ink(bp.MINT)
    for inp, text, sig in ((2, "No signal", 0), (4, "Searching...", 0), (5, "Disconnected", 0), (2, "96kHz", 1)):
        e = emu()
        home_state(e, inp=inp, status=text, sig=bool(sig))
        refresh_draw(e)
        want = lit if sig else bp.RED_LIT
        check("the refresh's draw after the loader (0x4081), input %d %r, signal %d: %s, PP_SIG kept" %
              (inp, text, sig, "lit" if sig else "red"),
              status_tint(e) == want and e.xram[bp.PP_SIG] == sig and home_ok(e), home_diff(e))
    for inp, text in ((2, "Digital input"), (4, "initializing"), (4, "BT Reconnect"), (1, "Bass boost")):
        e = emu()
        home_state(e, inp=inp, status=text, sig=False)
        e.setR(6, 0); e.setR(7, bp.STATUS_Y)
        e.call(0x3A53)
        check("small_text_render at y 135 not from the loader, input %d %r after a no-signal check: lit, PP_SIG 1"
              % (inp, text), status_tint(e) == lit and e.xram[bp.PP_SIG] == 1)
        refresh_draw(e)
        check("    and stays lit when redrawn", status_tint(e) == lit and home_ok(e))


# ---- the volume hook ---------------------------------------------------------------------------------
def test_draw_volume():
    print("\npp_draw_volume (the 0x5936 hook)")
    e = home_at(vol=32)
    fill_screen(e, 0x1234)
    e.setR(7, 25); e.call(0x5936)
    lamp = parts_for(e, settled_home())["mute"]
    check("idle: PP_VOL and PP_SHOW 25, XDATA 5 = 2, the MUTE lamp (dark) and nothing else drawn",
          e.xram[bp.PP_VOL] == 25 and e.xram[bp.PP_SHOW] == 25 and e.xram[5] == 2 and
          all(px(e, x, y) == lamp.get((x, y), 0x1234) for x in range(W) for y in range(H)))
    e.iram[0x22] |= 2
    fill_screen(e, 0x1234)
    e.setR(7, 30); e.call(0x5936)
    lamp = parts_for(e, settled_home())["mute"]
    check("muted: the lamp red", all(px(e, x, y) == lamp.get((x, y), 0x1234) for x in range(W) for y in range(H)))
    e.iram[0x22] &= ~2
    e.iram[0x2B] = 2; e.iram[0x52] = 33; e.setR(7, 10); e.call(0x5936)
    check("headphone output takes RAM 0x52 (33), as stock", e.xram[bp.PP_VOL] == 33)
    e.iram[0x2B] = 1; e.setR(7, 75); e.call(0x5936)
    check("a value above 60 is recorded as 60", e.xram[bp.PP_VOL] == 60)
    e.xram[bp.PP_ST] = 2; e.xram[bp.PP_SHOW] = 40
    e.setR(7, 41); e.call(0x5936)
    check("with the engine running: only PP_VOL; the counter is left to the ticks",
          e.xram[bp.PP_VOL] == 41 and e.xram[bp.PP_SHOW] == 40)
    for theme in ((0xFF, 0xFF), (0x07, 0xE0)):
        e = home_at(theme=theme)
        e.setR(7, 25); e.call(0x5936)
        check("theme %02X%02X untouched" % theme, (e.iram[0x48], e.iram[0x49]) == theme)


# ---- the engine ------------------------------------------------------------------------------------
def test_engine():
    print("\nthe engine: pp_step tick by tick against Engine")
    # entry from home
    e = home_at(inp=2, vol=32)
    before = screen(e)
    e.call(LAB["pp_enter_vol"])
    m = xstate(e)
    check("pp_enter_vol from home: ST 1, ACT 1, scan 0, the status buffer cleared, nothing drawn",
          m.st == 1 and m.act == 1 and m.scan == 0 and e.xram[bp.SMALL_BUF] == 0 and screen(e) == before)
    vol_key(e, m, 33)
    bad, worst, times = run_ticks(e, m, 40, label="entry")
    settled_at = next((k for k in range(len(times)) if xstate(e).st == 2), None)
    print("    entry tick times (ms): " + " ".join("%.1f" % t for t in times[:32]))
    check("entry: 40 ticks as Engine (the statics, the name's fall, the scan, the cells' rise), the screen as the "
          "state every tick", not bad, str(bad[:2]))
    m2 = xstate(e)
    check("entry: settled on the volume page (ST 2, every level at its target, scan %d, dB and marks), the counter at 33"
          % bp.BAR_N, m2.st == 2 and m2.lv == m2.tg and m2.scan == bp.BAR_N and m2.fl & 6 == 6 and m2.show == 33)
    check("entry: the page = vol_model (33)", vol_settled(e), vol_diff(e))
    check("entry: worst tick %.2f ms (at most %g)" % (worst, STEP_LIMIT), worst <= STEP_LIMIT)
    STEP_MS["entry"] = worst
    e.lcd.save_png(os.path.join(HERE, "build", "unit_volume.png"))
    # counting with afterglow: 33 -> 40, then 40 -> 7 (both digits change)
    for target, n in ((40, 44), (7, 100)):
        vol_key(e, m, target)
        bad, w, times = run_ticks(e, m, n, label="count %d" % target)
        worst = max(worst, w)
        glow = [k for k, t in enumerate(times) if t > 0.5]
        check("counting to %d: %d ticks as Engine (the digits step every %d ticks, segments that go out fade %d levels "
              "every %d ticks); settled = vol_model" % (target, n, bp.COUNT_EVERY, 7 - bp.GHOST, bp.RATE_GLOW),
              not bad and vol_settled(e), str(bad[:2]) or vol_diff(e))
    STEP_MS["count"] = worst
    check("counting: worst tick %.2f ms" % worst, worst <= STEP_LIMIT)
    # the blink while muted
    e.iram[0x22] |= 2
    m.muted = True
    vol_key(e, m, 7)                 # (a key: the lamp)
    bad, w, times = run_ticks(e, m, 2 * bp.BLINK_PERIOD + 10, label="blink")
    phases = []
    check("muted on the page: %d ticks as Engine: the digits out for %d ticks of %d (afterglow each time), no bar "
          "cell lit" % (2 * bp.BLINK_PERIOD + 10, bp.BLINK_PERIOD - bp.BLINK_ON, bp.BLINK_PERIOD),
          not bad and all(v == bp.GHOST for v in xstate(e).lv[E_BAR:]), str(bad[:2]))
    e.lcd.save_png(os.path.join(HERE, "build", "unit_muted.png"))
    e.iram[0x22] &= ~2
    m.muted = False
    vol_key(e, m, 7)                 # (a volume key unmutes first: the lamp)
    run_ticks(e, m, 40, label="unmute")
    # the exit
    e.iram[0x59] = 1; e.iram[0x45] = 1
    e.call(LAB["pp_clear"])
    m.exit()
    m2 = xstate(e)
    check("pp_clear with page 1 over the page: ST 3, the buffers cleared, the name reloaded (\"OPTICAL\") and measured, "
          "no stock clear", m2.st == 3 and buffer_text(e, bp.BIG_BUF) == "OPTICAL" and e.xram[bp.SMALL_BUF] == 0 and
          (e.xram[bp.PP_NX] << 8 | e.xram[bp.PP_NX + 1]) == bp.name_x(bp.PF_NAME.width("OPTICAL")) and
          not all(v == 0 for v in e.lcd.gram))
    bad, w, times = run_ticks(e, m, 44, label="exit")
    print("    exit tick times (ms): " + " ".join("%.1f" % t for t in times[:36]))
    check("exit: 44 ticks as Engine (dB and the marks go, the lit cells, the bar and VOL fall, then the ghost cells, "
          "then the name rises, then the slot and the status line)", not bad, str(bad[:2]))
    m2 = xstate(e)
    check("exit: settled at home: ST 0, ACT 0, home = home_model", m2.st == 0 and m2.act == 0 and home_ok(e), home_diff(e))
    check("exit: worst tick %.2f ms" % w, w <= STEP_LIMIT)
    STEP_MS["exit"] = w
    # reversal: an entry during the exit, at several points
    for at in (2, 8, 16, 22, 30):
        e = home_at(inp=3, vol=20)
        e.call(LAB["pp_enter_vol"]); m = xstate(e); vol_key(e, m, 21)
        bad, w, _ = run_ticks(e, m, 36, label="rev-setup")
        e.iram[0x59] = 1; e.call(LAB["pp_clear"]); m.exit()
        bad2, w2, _ = run_ticks(e, m, at, label="rev-exit")
        e.call(LAB["pp_enter_vol"]); m.enter_vol(); vol_key(e, m, 22)
        bad3, w3, _ = run_ticks(e, m, 60, label="rev-entry")
        check("exit reversed %2d ticks in: the entry from there as Engine (scan %d), settled = vol_model (22)"
              % (at, bp.BAR_N if at else 0), not (bad or bad2 or bad3) and vol_settled(e), str((bad + bad2 + bad3)[:2]))
        STEP_MS["rev_%d" % at] = max(w, w2, w3)
    for at in (1, 6, 15, 20, 26):
        e = home_at(inp=1, vol=50)
        e.call(LAB["pp_enter_vol"]); m = xstate(e); vol_key(e, m, 51)
        bad, w, _ = run_ticks(e, m, at, label="rev2-entry")
        e.iram[0x59] = 1; e.call(LAB["pp_clear"]); m.exit()
        bad2, w2, _ = run_ticks(e, m, 60, label="rev2-exit")
        check("entry reversed %2d ticks in: the exit from there as Engine, settled = home_model" % at,
              not (bad or bad2) and home_ok(e), str((bad + bad2)[:2]) or home_diff(e))
    # cancel: a stock clear mid-transition
    e = home_at(inp=2, vol=32)
    e.call(LAB["pp_enter_vol"]); m = xstate(e)
    run_ticks(e, m, 10)
    e.call(0x5D42)
    m2 = xstate(e)
    check("ui_clear_screen (pp_cancel) mid-entry: the engine stopped and empty, the screen black, the buffers cleared",
          m2.st == 0 and m2.act == 0 and all(v == 0 for v in m2.lv + m2.tg) and m2.fl == 0 and
          all(v == 0 for col in screen(e) for v in col) and m2.show == m2.vol == 32)
    e.call(LAB["pp_step"])
    check("pp_step when idle: nothing", all(v == 0 for col in screen(e) for v in col) and xstate(e).state() == m2.state())


# ---- entry, exit and hold-back logic --------------------------------------------------------------
def test_enter_vol():
    print("\nentry, exit, cancel and hold-back logic")
    for s in bp.VOL_ENTRY_SITES:
        e = emu()
        e.iram[0x47] = 1
        seen = []
        e.hooks[LAB["pp_enter_vol"]] = lambda em: seen.append(em.cycles)
        e.hooks[0x3A53] = lambda em: seen.append("caption")
        e.pc = s
        e.push(0x00); e.push(0x00)
        e.run(s + len(bp.VOL_ENTRY_ORIG), 2_000_000)
        check("site 0x%04X: pp_enter_vol called, stock caption skipped" % s,
              len(seen) == 1 and seen[0] != "caption" and e.pc == s + len(bp.VOL_ENTRY_ORIG))
    for st, want in ((1, 1), (2, 2)):
        e = home_at(); e.xram[bp.PP_ST] = st; e.xram[bp.PP_SCAN] = 17
        e.call(LAB["pp_enter_vol"])
        check("pp_enter_vol with ST %d: nothing changes (ST %d, scan 17)" % (st, want),
              e.xram[bp.PP_ST] == want and e.xram[bp.PP_SCAN] == 17)
    e = home_at(); e.xram[bp.PP_ST] = 3; e.xram[bp.PP_ACT] = 1
    e.call(LAB["pp_enter_vol"])
    check("pp_enter_vol during an exit: ST 1, the scan over the whole bar (%d)" % bp.BAR_N,
          e.xram[bp.PP_ST] == 1 and e.xram[bp.PP_SCAN] == bp.BAR_N)
    # pp_clear
    for page, st, want in ((2, 0, "enter"), (2, 3, "enter"), (1, 0, "stock"), (1, 3, "stock"), (1, 1, "exit"), (1, 2, "exit"),
                           (3, 2, "stock"), (13, 0, "stock")):
        e = home_at()
        fill_screen(e, 0x1234)
        e.xram[bp.PP_ST] = st; e.xram[bp.PP_ACT] = 1 if st else 0
        e.iram[0x59] = page
        e.call(LAB["pp_clear"])
        black = all(v == 0 for col in screen(e) for v in col)
        got = "stock" if black else ("enter" if e.xram[bp.PP_ST] == 1 else "exit" if e.xram[bp.PP_ST] == 3 else "?")
        check("pp_clear page %2d, ST %d: %s" % (page, st, want), got == want,
              "(got %s, ST %d)" % (got, e.xram[bp.PP_ST]))
        if want == "stock":
            check("    the stock clear stops the engine (ST 0, ACT 0)", e.xram[bp.PP_ST] == 0 and e.xram[bp.PP_ACT] == 0)
    # pp_hold
    for st, held in ((0, False), (1, True), (2, False), (3, True)):
        e = home_at()
        fill_screen(e, 0x1234)
        e.xram[bp.PP_ST] = st; e.xram[bp.PP_SBUF] = 0
        e.call(LAB["pp_hold"])
        drew = any(v != 0x1234 for v in e.lcd.gram)
        check("pp_hold with ST %d: %s" % (st, "held back (nothing drawn, PP_SBUF 1)" if held else "home_refresh and the status line"),
              drew != held and (e.xram[bp.PP_SBUF] == 1) == held)
    # pp_flag_path
    for st, fill_ in ((0, True), (1, False), (2, True), (3, False)):
        e = home_at()
        fill_screen(e, 0x1234)
        e.xram[bp.PP_ST] = st
        e.iram[0x21] |= 0x0A; e.iram[0x20] |= 0x40
        e.hooks[0x4016] = lambda em: em.ret()
        e.call(LAB["pp_flag_path"])
        filled = px(e, 100, 100) == 0
        check("pp_flag_path with ST %d: flags cleared, page 1, the black-out %s" % (st, "as stock" if fill_ else "skipped"),
              filled == fill_ and e.iram[0x21] & 0x0A == 0 and e.iram[0x20] & 0x40 == 0 and e.iram[0x45] == 1)
    # the guards: a page-1 draw during an exit ends it with the whole home
    for name, fn in (("pp_name_guard (home_draw_input_name)", lambda e: e.call(0x4A85)),
                     ("the big text (pp_name)", lambda e: (e.setR(6, 0), e.setR(7, bp.NAME_Y), e.call(0x298B))),
                     ("the status line (pp_status)", lambda e: (e.setR(6, 0), e.setR(7, bp.STATUS_Y), e.call(0x3A53)))):
        e = home_at(inp=2, vol=32)
        e.call(LAB["pp_enter_vol"]); m = xstate(e); run_ticks(e, m, 36)
        e.iram[0x59] = 1; e.call(LAB["pp_clear"]); m.exit(); run_ticks(e, m, 8)
        fn(e)
        m2 = xstate(e)
        check("%s during an exit: the exit ended (ST 0), a whole home = home_model" % name,
              m2.st == 0 and m2.act == 0 and home_ok(e), home_diff(e))
    e = home_at(inp=2, vol=32)
    e.call(LAB["pp_enter_vol"]); m = xstate(e); run_ticks(e, m, 36)
    e.iram[0x45] = 2
    before = xstate(e).state()
    e.setR(6, 0); e.setR(7, 50); e.call(0x3A53)
    check("a small text at another y on page 2: stock, the engine untouched", xstate(e).state() == before and e.xram[bp.PP_ST] == 2)


# ---- the mute key ---------------------------------------------------------------------------------
KEY_FILTER = 0x3DBD                      # read_key (IR): the key in R7 from here to its ret


def key_filter(img, page, code):
    """read_key's IR tail for key `code` on `page`: the key it returns."""
    e = ut.emu(img)
    e.iram[0x45] = page
    e.setR(7, code)
    e.call(KEY_FILTER)
    return e.R(7)


def mute_key_run(img, page, mute, setup=None):
    e = setup if setup is not None else emu(img=img)
    if setup is None:
        home_state(e, inp=2, vol=25) if img == NEW else None
    e.iram[0x45] = page
    e.iram[0x22] = (e.iram[0x22] & ~2) | (2 if mute else 0)
    calls = []
    e.hooks[0x5A62] = lambda em: calls.append(em.R(7))
    e.call(0x1047)
    return e, calls


def test_mute_key():
    print("\nthe mute key: pp_mute_key (the 0x1047 hook) and read_key's page-2 filter (pp_key_p2, the 0x3DD1 hook)")
    for mute in (False, True):
        b, cb = mute_key_run(BASE, 1, mute)
        e, ce = mute_key_run(NEW, 1, mute)
        same = (muted(e), ce, e.sfr[0xA0], e.iram[0x43], e.iram[0x44]) == (muted(b), cb, b.sfr[0xA0], b.iram[0x43], b.iram[0x44])
        check("home, %s: the toggle as stock (0x22.1 %d, mute_state_set %s, P2 0x%02X)" %
              ("muted" if mute else "playing", muted(e), ce, e.sfr[0xA0]), same and muted(e) != mute and ce == ([] if mute else [0]))
        check("home, %s: then page 2 through pp_enter_vol (ST 1, nothing drawn but the lamp), both timers 200 "
              "(stock: page 1, refresh in 10)" % ("muted" if mute else "playing"),
              e.iram[0x45] == 2 and e.xram[bp.PP_ST] == 1 and
              (e.iram[0x3F], e.iram[0x40], e.iram[0x27], e.iram[0x28]) == (0, 200, 0, 200) and b.iram[0x45] == 1 and
              (b.iram[0x27], b.iram[0x28]) == (0, 10))
    for mute in (False, True):
        pg = home_at(inp=2, vol=25)
        pg.iram[0x22] = (pg.iram[0x22] & ~2) | (2 if mute else 0)
        pg.call(LAB["pp_enter_vol"]); m = xstate(pg); vol_key(pg, m, 25); run_ticks(pg, m, 40)
        e, ce = mute_key_run(NEW, 2, mute, setup=pg)
        check("the page open, %s: toggled (mute_state_set %s), page 2 kept, ST 2, timers 200" %
              ("muted" if mute else "playing", ce),
              muted(e) != mute and ce == ([] if mute else [0]) and e.iram[0x45] == 2 and e.xram[bp.PP_ST] == 2 and
              (e.iram[0x3F], e.iram[0x40]) == (0, 200))
    e = home_at(inp=2, vol=25)
    e.call(LAB["pp_enter_vol"]); m = xstate(e); run_ticks(e, m, 40)
    e.iram[0x59] = 1; e.call(LAB["pp_clear"]); m.exit(); run_ticks(e, m, 12)
    e, ce = mute_key_run(NEW, 1, False, setup=e)
    check("during the exit (page 1): toggled, page 2, the exit turned round (ST 1)",
          muted(e) and e.iram[0x45] == 2 and e.xram[bp.PP_ST] == 1)
    diff_ = {}
    for page in (1, 2, 3, 7, 13):
        for code in range(256):
            a, b = key_filter(BASE, page, code), key_filter(NEW, page, code)
            if a != b:
                diff_[(page, code)] = (a, b)
    check("read_key, IR, 256 key codes on pages 1, 2, 3, 7, 13: as fast-lcd except the mute key 0x1C on page 2 "
          "(0x15 \"home\" there, kept here)", diff_ == {(2, 0x1C): (0x15, 0x1C)}, str(sorted(diff_.items())[:4]))


# ---- the align hooks -------------------------------------------------------------------------------
def text_render(img, page, entry, buf, text, y):
    e = emu(img=img)
    if img == NEW:
        e.call(LAB["pp_stop"])
    e.iram[0x45] = page
    for k, ch in enumerate(text.encode() + b"\0"):
        e.xram[buf + k] = ch
    e.setR(6, 0); e.setR(7, y)
    e.call(entry)
    return e


def test_align():
    print("\nbig text (hook 0x2A25): always the theme's name painter; small text (hook 0x3A82): ours at the"
          " status y on page 1, else stock")
    name = text_render(NEW, 1, 0x298B, 0x35, "USB", bp.NAME_Y)
    x0 = bp.name_x(bp.PF_NAME.width("USB"))
    check("big text at the name y on page 1: ink from x %d (centred, 1 mod 3)" % x0,
          ink_in(name, x0, bp.HNAME_Y, 60, bp.PF_NAME.H) and not ink_in(name, 0, bp.HNAME_Y, x0, bp.PF_NAME.H))
    for page, y in ((1, 40), (3, 40), (3, bp.NAME_Y)):
        n = text_render(NEW, page, 0x298B, 0x35, "USB", y)
        check("big text on page %d at y %d: drawn by pp_name, not the stock glyphs (trapped)" % (page, y),
              n.lcd.gram == name.lcd.gram)
    for page, y in ((1, 100), (3, 100), (3, bp.STATUS_Y)):
        n, b = text_render(NEW, page, 0x3A53, 0x50, "No signal", y), text_render(BASE, page, 0x3A53, 0x50, "No signal", y)
        check("small text on page %d at y %d: identical to stock (centred, stock glyphs)" % (page, y), n.lcd.gram == b.lcd.gram)


def test_volpage():
    print("\npp_volpage (page 2 renderer, jump-table entry 0x2143)")
    e = home_at(inp=2, vol=25)
    e.iram[0x22] |= 0x08
    e.iram[0x32] = e.iram[0x46] = 1
    e.call(LAB["pp_volpage"])
    check("from home: the entry started (ST 1), PP_VOL 25, 0x22.3 / 0x32 / 0x46 cleared as every page",
          e.xram[bp.PP_ST] == 1 and e.xram[bp.PP_VOL] == 25 and not e.iram[0x22] & 0x08 and e.iram[0x32] == 0 and e.iram[0x46] == 0)
    m = xstate(e)
    bad, w, _ = run_ticks(e, m, 40)
    check("then the entry as Engine, settled = vol_model (25)", not bad and vol_settled(e), str(bad[:2]) or vol_diff(e))
    e.iram[0x31] = 26
    e.call(LAB["pp_volpage"])
    check("on the open page: the volume recorded (26), ST 2 kept", e.xram[bp.PP_VOL] == 26 and e.xram[bp.PP_ST] == 2)


# ---- whole firmware ----------------------------------------------------------------------------
NEC_HDMI = 0x14
NEC_MENU_OPEN = 0x04
NEC_USB, NEC_OPTICAL, NEC_BT = 0x10, 0x11, 0x13
UNMUTE_CALL = 0x33FB
DAC_RECONFIG = 0x46A0
CHUNK = 0.01
TOUR = [
    ("power_on", NEC_POWER, 8.0, "home"),
    ("vol_up", NEC_VOL_UP, 0.8, "vol"),
    ("vol_up2", NEC_VOL_UP, 0.5, "vol"),
    ("back_home", None, 2.5, "home"),
    ("source", NEC_SOURCE, 11.0, "home"),
    ("menu", NEC_MENU_OPEN, 1.5, "same"),
    ("menu_down", NEC_DOWN, 1.0, "same"),
    ("menu_timeout", None, 9.5, "home"),
    ("hdmi", NEC_HDMI, 3.0, "home"),
    ("vol_down", NEC_VOL_DOWN, 0.8, "vol"),
    ("vol_timeout", None, 2.5, "home"),
    ("standby", NEC_POWER, 3.0, "same"),
]
VOL_ENTRY_STEPS = ("vol_up", "vol_down")
EXIT_STEPS = ("back_home", "vol_timeout")


def state(amp):
    return (amp.page, amp.powered) + tuple(amp.e.iram[a] for a in (0x31, 0x52, 0x47, 0x2B))


def draw_time(activity, quiet=10):
    for i in range(len(activity)):
        if not any(activity[i:i + quiet]):
            return i * CHUNK
    return len(activity) * CHUNK


def countdown(e):
    return (e.iram[0x43] << 8) | e.iram[0x44]


class Watch:
    """Logs every engine tick (start clock, ST before, ST after, Timer0 tick, ms from pp_step's entry
    to uk_tasks' return) while PP_ACT, and uk_fill calls."""

    def __init__(self, amp):
        self.amp = amp
        self.ticks, self.fills, self._open = [], [], None
        self.on_tick = None
        e = amp.e
        e.hooks[LAB["pp_step"]] = self._start
        e.hooks[LAB["uk_fill"]] = lambda em: self.fills.append(
            (em.cycles, (em.R(2) << 8) | em.R(3), em.R(1), (em.R(6) << 8) | em.R(7)))

    def _start(self, em):
        if em.xram[bp.PP_ACT]:
            self._open = (em.cycles, em.xram[bp.PP_ST])
            em.hooks[STEP_END] = self._end
        else:
            self._open = None

    def _end(self, em):
        em.hooks.pop(STEP_END, None)
        if self._open:
            c0, st0 = self._open
            self._open = None
            self.ticks.append((c0, st0, em.xram[bp.PP_ST], self.amp.ticks, (em.cycles - c0) * 1000 / CLOCK_HZ))
            if self.on_tick:
                self.on_tick(self.ticks[-1])

    def mark(self):
        return len(self.ticks), len(self.amp.events), len(self.fills)

    def since(self, mark):
        return self.ticks[mark[0]:]

    def worst(self):
        return max((t[4] for t in self.ticks), default=0.0)


def transition_checks(label, w, mark, kind):
    """The ticks since mark: an entry (ST 1 ticks, then ST 2) or an exit (ST 3 ticks, then ST 0)."""
    st = w.since(mark)
    want = 1 if kind == "entry" else 3
    run = [t for t in st if t[1] == want]
    done = [t for t in st if t[1] == want and t[2] == (2 if kind == "entry" else 0)]
    check("%s%s: %d ticks, then settled (%s)" % (label, kind, len(run), "the volume page" if kind == "entry" else "home"),
          20 <= len(run) <= 45 and len(done) == 1, "(%d ticks, %d settles)" % (len(run), len(done)))
    return run


def vol_entry_checks(step, new, w, mark):
    st = transition_checks("%-12s " % step, w, mark, "entry")
    vol_writes = [c for c, nm, d in new.events[mark[1]:] if nm == "njw1194_write" and "R7=10" in d]
    first = st[0][0] if st else None
    check("%-12s NJW1194 volume write before the first tick" % step,
          bool(vol_writes) and first is not None and vol_writes[0] < first,
          "(write %.1f ms before)" % ((first - vol_writes[0]) * 1000 / CLOCK_HZ) if vol_writes and first else "")
    fl = [f for f in w.fills[mark[2]:]]
    check("%-12s nothing drawn between the press and the first tick (the MUTE lamp apart)" % step,
          bool(st) and all(f[0] >= st[0][0] for f in fl))


BACKLIGHT = ("pin", "P0.6 backlight")


def audio_transitions(amp):
    out, last = [], None
    for c, st in amp.state_changes:
        st = tuple(kv for kv in st if kv[0] != BACKLIGHT)
        if st != last:
            out.append((c / CLOCK_HZ, st))
            last = st
    return out


def audio_checks(label, ref, new, quiet=False):
    tr_ref, tr_new = audio_transitions(ref), audio_transitions(new)
    cut = min(ref.t, new.t) - 0.10
    sr, sn = [s for _, s in tr_ref], [s for _, s in tr_new]
    n_ref = len([1 for t, _ in tr_ref if t <= cut])
    n_new = len([1 for t, _ in tr_new if t <= cut])
    k = min(len(sr), len(sn))
    same_order = sr[:k] == sn[:k] and n_ref <= len(sn) and n_new <= len(sr)
    check("%ssame sequence of audio states, in the same order" % label, same_order, "(%d vs %d states)" % (len(tr_ref), len(tr_new)))
    if same_order:
        tr_ref, tr_new = tr_ref[:k], tr_new[:k]
        late = [(tn - tr, tr) for (tr, _), (tn, _) in zip(tr_ref, tr_new) if tn - tr > 0.10]
        check("%sno audio state more than 0.10 s later than the reference" % label, not late,
              "" if not late else "(%d, first %+.2f s at %.2f s)" % (len(late), late[0][0], late[0][1]))
        if not quiet:
            for tr, d in [(tr, tn - tr) for (tr, _), (tn, _) in zip(tr_ref, tr_new) if abs(tn - tr) > 0.05]:
                print("    %saudio state at %7.2f s moves %+.2f s" % (label, tr, d))
    bl = [[d for _, nm, d in amp.events if nm == BACKLIGHT[1]] for amp in (ref, new)]
    check("%sbacklight switches the same way" % label, bl[0] == bl[1])


def tour():
    print("\nWhole firmware, lockstep with the reference")
    amps = [Amp(REF), Amp(NEW)]
    for amp in amps:
        amp.set_pin(0xC0, 5, 0)
        amp.boot()
    ref, new = amps
    w = Watch(new)
    sp0 = [a.e.sfr[0x81] for a in amps]
    for a, s in zip(amps, sp0):
        for i in range(s + 1, 0x100):
            a.e.iram[i] = 0xA5
    for step, cmd, secs, kind in TOUR:
        w0 = time.time()
        mark = w.mark()
        for amp in amps:
            if cmd is not None:
                amp.press(cmd)
        act, home_at_ = [[], []], [None, None]
        c_start = new.e.cycles
        exit_end = []

        def at_tick(rec, exit_end=exit_end):
            if rec[1] == 3 and rec[2] == 0:
                exit_end.append((new.e.cycles, screen(new.e)))
        w.on_tick = at_tick
        refreshes = []
        new.e.hooks[uikit.HOME_REFRESH] = lambda em: refreshes.append(em.cycles)
        mid = []
        for n in range(int(round(secs / CHUNK))):
            for k, amp in enumerate(amps):
                p0, n0 = amp.lcd.pixels, len(amp.lcd.log)
                amp.wait(CHUNK)
                act[k].append(amp.lcd.pixels != p0 or len(amp.lcd.log) != n0)
                if home_at_[k] is None and amp.page == 1:
                    home_at_[k] = n * CHUNK
            if step in VOL_ENTRY_STEPS and n == 12:
                mid.append(xscreen_ok(new.e) or xscreen_diff(new.e))
                new.lcd.save_png(os.path.join(HERE, "build", "tour_%s_mid.png" % step))
        print("    %-12s %5.1f s emulated x2 in %5.1f s, drawing %4.0f / %4.0f ms" %
              (step, secs, time.time() - w0, draw_time(act[0]) * 1000, draw_time(act[1]) * 1000), flush=True)
        check("%-12s same page, power, volumes, input, output" % step, state(ref) == state(new), "%s vs %s" % (state(ref), state(new)))
        if kind == "home":
            check("%-12s home screen = home_model for the amp's state" % step, home_ok(new.e), home_diff(new.e))
        elif kind == "vol":
            check("%-12s volume page settled = vol_model for the amp's state" % step, new.page == 2 and vol_settled(new.e), vol_diff(new.e))
        else:
            check("%-12s screen identical to the reference" % step, new.lcd.gram == ref.lcd.gram)
        if step in ("menu", "menu_down"):
            check("%-12s really in the menu (page >= 3)" % step, new.page >= 3, "(page %d)" % new.page)
        if step in VOL_ENTRY_STEPS:
            vol_entry_checks(step, new, w, mark)
            check("%-12s mid-entry (0.12 s): the screen = the engine's state" % step, mid == [True], str(mid))
        if step == "vol_up2":
            check("%-12s a second key on the page: no new entry (ST stays 2)" % step, all(t[1] == 2 for t in w.since(mark)))
        if step in EXIT_STEPS:
            st = transition_checks("%-12s " % step, w, mark, "exit")
            if st and exit_end:
                t_end = exit_end[0][0]
                during = [c for c in refreshes if st[0][0] <= c <= t_end]
                after = [c for c in refreshes if c > t_end]
                check("%-12s no stock home refresh during the exit; it resumes %.2f s after it" %
                      (step, (after[0] - t_end) / CLOCK_HZ if after else -1),
                      not during and bool(after) and (after[0] - t_end) / CLOCK_HZ <= 0.6)
                check("%-12s the screen the exit leaves = what the stock refresh draws over it" % step,
                      exit_end[0][1] == screen(new.e))
            both = None not in home_at_
            check("%-12s home (page 1) within 0.05 s of the reference" % step, both and abs(home_at_[1] - home_at_[0]) <= 0.05, str(home_at_))
            if both and exit_end:
                done = (exit_end[0][0] - c_start) / CLOCK_HZ - home_at_[1]
                check("%-12s the home screen whole %.2f s after the switch to page 1" % (step, done), 0.2 <= done <= 0.5)
        if step in ("source", "menu", "hdmi", "standby", "menu_timeout", "power_on"):
            check("%-12s no transition" % step, not w.since(mark))
        new.lcd.save_png(os.path.join(HERE, "build", "tour_%s.png" % step))
    print("\n  Audio state, after every write that changes it")
    audio_checks("", ref, new)

    def semantic_args(name, regs):
        r = [0] * 8
        for kv in regs.split():
            r[int(kv[1])] = int(kv[3:], 16)
        return STATE_KEY[name](r)
    for name in sorted(set(ref.calls) | set(new.calls)):
        a = {semantic_args(name, regs) for regs in ref.calls.get(name, set())}
        b = {semantic_args(name, regs) for regs in new.calls.get(name, set())}
        check("%-15s same argument sets (%d distinct)" % (name, len(a)), a == b)
    peak = []
    for a, s in zip(amps, sp0):
        peak.append(max((i for i in range(s + 1, 0x100) if a.e.iram[i] != 0xA5), default=s))
    print("    stack: main-loop SP 0x%02X; deepest idata used 0x%02X on the reference, 0x%02X here" % (sp0[1], peak[0], peak[1]))
    check("stack: deepest idata used in the tour at most 0xB3 (canary)", peak[1] <= 0xB3, "(0x%02X)" % peak[1])
    STEP_MS["tour"] = w.worst()
    print("    worst engine tick in the tour: %.2f ms" % w.worst())


def headphone_unplugged(amp):
    amp.e.iram[0x2B] = 2
    amp.set_pin(0xA0, 6, 0)


SCENARIOS = [
    ("bt", "Bluetooth, no stream: 0x583F holds the countdown at 40..50", [(NEC_POWER, None, 9.0), (NEC_BT, None, 4.0)], "held", 1.0, 2),
    ("optical", "Optical without signal: Timer0 holds the countdown at 100", [(NEC_POWER, None, 9.0), (NEC_OPTICAL, None, 4.0)], "held", 1.0, 2),
    ("headphone", "headphone output, P2.6 low: Timer0 holds the countdown at 300", [(NEC_POWER, None, 9.0), (None, headphone_unplugged, 1.0)], "held", 1.0, 2),
    ("power_on", "USB, Vol+ during the countdown after power-on", [(NEC_POWER, None, 7.4)], "runs", 1.0, 2),
    ("hdmi_switch", "Vol+ 0.5 s after switching to HDMI", [(NEC_POWER, None, 9.0), (NEC_HDMI, None, 0.5)], "runs", 1.0, 2),
    ("switch_now", "Vol+ 0.05 s after switching to USB from HDMI", [(NEC_POWER, None, 9.0), (NEC_HDMI, None, 3.0), (NEC_USB, None, 0.05)], "runs", 1.0, 2),
    ("unmute_due", "USB, Vol+ when the unmute is due within the entry", [(NEC_POWER, None, 8.15)], "runs", 1.0, 2),
    ("splash", "Vol+ during the power-on logo, dispatched just before post_power_on", [(NEC_POWER, None, 2.5)], "runs", 4.0, 1),
]


def screen_ok(base, new):
    if base.powered and new.powered:
        if new.page == 1 and base.page == 1:
            return home_ok(new.e)
        if new.page == 2 and base.page == 2:
            return vol_settled(new.e)
    return new.lcd.gram == base.lcd.gram


def input_scenarios():
    print("\nVolume key after each input settles, whole firmware, against the reference")
    for name, what, setup, cd_kind, settle, page in SCENARIOS:
        w0 = time.time()
        print("  %s: %s" % (name, what))
        amps = [Amp(REF), Amp(NEW)]
        ref, new = amps
        w = Watch(new)
        unmutes = [[], []]
        for k, amp in enumerate(amps):
            amp.e.hooks[UNMUTE_CALL] = lambda em, k=k: unmutes[k].append(em.cycles / CLOCK_HZ)
            amp.set_pin(0xC0, 5, 0)
            amp.boot()
            for cmd, fn, secs in setup:
                if cmd is not None:
                    amp.press(cmd)
                if fn is not None:
                    fn(amp)
                amp.wait(secs)
        label = "%-11s " % name
        before = [len(u) for u in unmutes]
        mark = w.mark()
        t_press = new.t
        cd_press = countdown(new.e)
        for amp in amps:
            amp.press(NEC_VOL_UP)
            amp.wait(settle)
        if name == "splash":
            st = w.since(mark)
            check("%sentry started, then cancelled by post_power_on's clear (%d ticks)" % (label, len(st)),
                  new.e.xram[bp.PP_ST] == 0 and len(st) < 30)
        else:
            vol_entry_checks(name, new, w, mark)
            print("    %s unmute countdown at the press: %d" % (label, cd_press))
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new), "%s vs %s" % (state(ref), state(new)))
        check("%spage %d, screen as expected (volume: settled vol_model; home: home_model)" % (label, page),
              new.page == page and screen_ok(ref, new))
        new.lcd.save_png(os.path.join(HERE, "build", "inputs_%s.png" % name))
        for amp in amps:
            amp.wait(2.5)
        if name != "splash":
            transition_checks(label, w, (mark[0] + len([t for t in w.since(mark) if t[1] == 1]) + 0,) + mark[1:], "exit")
            check("%sback home after the exit: home_model" % label, new.page == 1 and screen_ok(ref, new))
        if cd_kind == "runs":
            for amp in amps:
                amp.wait(3.0)
        after = [u[b:] for u, b in zip(unmutes, before)]
        if cd_kind == "held":
            check("%scountdown held: no unmute in either image, still running at the end" % label,
                  after == [[], []] and countdown(ref.e) > 0 and countdown(new.e) > 0, "(%s, %d / %d)" % (after, countdown(ref.e), countdown(new.e)))
        else:
            ok = len(after[0]) == 1 and len(after[1]) == 1
            shift = after[1][0] - after[0][0] if ok else None
            check("%sunmute %s after the press, no later than the reference + 0.10 s" %
                  (label, "%.2f s" % (after[1][0] - t_press) if ok else "?"), ok and shift <= 0.10, "(%s)" % ("%+.3f s" % shift if ok else after))
        audio_checks(label, ref, new)
        STEP_MS["input_" + name] = w.worst()
        print("    %s: %.1f s, worst tick %.2f ms" % (name, time.time() - w0, w.worst()), flush=True)


def stock_home_now(amp):
    """The home screen the stock refresh would draw for amp's state right now."""
    e = ut.Emu8051(NEW)
    e.iram[:] = amp.e.iram
    e.sfr[:] = amp.e.sfr
    e.xram[:] = amp.e.xram
    for k, v in amp.e.pins.items():
        e.pins[k] = v
    e.call(LAB["pp_stop"])
    e.iram[0x45] = 1
    e.call(0x51EE)
    refresh_draw(e)
    return screen(e)


def set_flag_213(amp):
    amp.e.iram[0x21] |= 0x08


KEY_SCENARIOS = [
    ("vol_in_entry", [], "entry", 0.08, NEC_VOL_UP, 1.0, "vol", None),
    ("vol_in_exit", [], "exit", 0.10, NEC_VOL_UP, 1.0, "vol", None),
    ("voldown_in_exit", [], "exit", 0.03, NEC_VOL_DOWN, 1.0, "vol", None),
    ("menu_in_entry", [], "entry", 0.10, NEC_MENU_OPEN, 1.5, "home", None),
    ("menu_in_exit", [], "exit", 0.10, NEC_MENU_OPEN, 1.5, "same", None),
    ("source_in_entry", [], "entry", 0.10, NEC_SOURCE, 1.0, "home", None),
    ("source_in_exit", [], "exit", 0.10, NEC_SOURCE, 1.0, "source", None),
    ("source_late_exit", [], "exit", 0.25, NEC_SOURCE, 1.0, "source", None),
    ("vol_early_exit", [], "exit", 0.0, NEC_VOL_UP, 1.0, "vol", None),
    ("vol_late_entry", [], "entry", 0.25, NEC_VOL_UP, 1.0, "vol", None),
    ("power_in_entry", [], "entry", 0.10, NEC_POWER, 3.0, "same", None),
    ("power_in_exit", [], "exit", 0.12, NEC_POWER, 3.0, "same", None),
    ("select_in_entry", [], "entry", 0.10, NEC_HDMI, 1.0, "home", None),
    ("select_in_exit", [], "exit", 0.10, NEC_HDMI, 1.0, "source", None),
    ("bt_key_in_exit", [(NEC_BT, 4.0)], "exit", 0.08, 0x0E, 1.5, "home", None),
    ("source_flag_in_exit", [], "exit", 0.05, NEC_SOURCE, 1.0, "source", set_flag_213),
]
EARLY = 0.15


def key_scenarios():
    print("\nKeys during a transition, whole firmware, against the reference")
    for name, pre, when, into, cmd, settle, expect, inject in KEY_SCENARIOS:
        w0 = time.time()
        amps = [Amp(REF), Amp(NEW)]
        ref, new = amps
        w = Watch(new)
        for amp in amps:
            amp.set_pin(0xC0, 5, 0)
            amp.boot()
            amp.press(NEC_POWER)
            amp.wait(9.5)
            for c, secs in pre:
                amp.press(c)
                amp.wait(secs)
            amp.press(NEC_VOL_UP)
        label = "%-19s " % name
        if when == "exit":
            for amp in amps:
                amp.wait(1.9)
            for _ in range(40):
                if new.e.xram[bp.PP_ST] == 3:
                    break
                for amp in amps:
                    amp.wait(0.005)
            check("%sexit running before the key" % label, new.e.xram[bp.PP_ST] == 3)
        for amp in amps:
            amp.wait(into)
        st_at = new.e.xram[bp.PP_ST]
        mark = w.mark()
        for amp in amps:
            if inject:
                inject(amp)
            amp.press(cmd)
        early = None
        if when == "exit" and expect in ("home", "source"):
            for amp in amps:
                amp.wait(EARLY)
            early = screen(new.e) == stock_home_now(new) and new.page == 1
            new.lcd.save_png(os.path.join(HERE, "build", "keys_%s_early.png" % name))
        for amp in amps:
            amp.wait(settle - (EARLY if early is not None else 0))
        st = w.since(mark)
        print("  %s key at %s ST %d; %d engine ticks after it" % (name, when, st_at, len(st)))
        check("%sa transition was running at the key" % label, st_at == (1 if when == "entry" else 3))
        if early is not None:
            check("%s%.2f s after the key: a whole home screen (= the stock refresh for that state)" % (label, EARLY), early)
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new), "%s vs %s" % (state(ref), state(new)))
        if expect == "vol":
            check("%svolume page settled = vol_model (latest value)" % label, new.page == 2 and vol_settled(new.e), vol_diff(new.e))
            if name.endswith("in_exit"):
                check("%sturned round: entry ticks after the key" % label, any(t[1] == 1 for t in st))
        elif expect == "home":
            check("%shome = home_model" % label, new.page == 1 and screen_ok(ref, new))
        elif expect == "source":
            check("%sinput switched on page 1: a whole home screen (= the stock refresh for that state)" % label,
                  new.page == 1 and screen(new.e) == stock_home_now(new))
        else:
            check("%sscreen identical to the reference" % label, new.lcd.gram == ref.lcd.gram)
        check("%sno transition left running" % label, new.e.xram[bp.PP_ST] in (0, 2))
        new.lcd.save_png(os.path.join(HERE, "build", "keys_%s.png" % name))
        if expect == "source":
            for amp in amps:
                amp.wait(2.5)
            check("%s2.5 s later: home = home_model" % label, new.page == 1 and home_ok(new.e))
        if expect == "vol":
            for amp in amps:
                amp.wait(2.6)
            check("%sthen back home = home_model" % label, new.page == 1 and screen_ok(ref, new))
        audio_checks(label, ref, new, quiet=True)
        STEP_MS["key_" + name] = w.worst()
        print("    %s: %.1f s" % (name, time.time() - w0), flush=True)


def flag_exit_scenarios():
    print("\nSource, then Vol+ while the refresh flags are still set, then the exit")
    for gap in (0.2, 1.0, 2.0):
        name = "source_vol_%.1f" % gap
        label = "%-19s " % name
        amps = [Amp(REF), Amp(NEW)]
        ref, new = amps
        w = Watch(new)
        ends = []
        w.on_tick = lambda rec: rec[1] == 3 and rec[2] == 0 and ends.append(new.e.cycles)
        for amp in amps:
            amp.set_pin(0xC0, 5, 0)
            amp.boot()
            amp.press(NEC_POWER)
            amp.wait(9.5)
            amp.press(NEC_SOURCE)
            amp.wait(gap)
            flags = (amp.e.iram[0x20] >> 6 & 1, amp.e.iram[0x21] >> 1 & 1, amp.e.iram[0x21] >> 3 & 1)
            amp.press(NEC_VOL_UP)
        mark = w.mark()
        for _ in range(400):
            if ends:
                break
            for amp in amps:
                amp.wait(0.01)
        for amp in amps:
            amp.wait(0.02)
        st = w.since(mark)
        print("  %s: flags 0x20.6/0x21.1/0x21.3 at the Vol+ %s; %d ticks" % (name, flags, len(st)))
        check("%sentry and exit ran" % label, any(t[1] == 1 for t in st) and any(t[1] == 3 for t in st) and bool(ends))
        check("%stwo ticks after the exit: a whole home screen (= the stock refresh for that state)" % label,
              new.page == 1 and screen(new.e) == stock_home_now(new))
        new.lcd.save_png(os.path.join(HERE, "build", "keys_%s_end.png" % name))
        for amp in amps:
            amp.wait(2.0)
        check("%slater: home = home_model" % label, new.page == 1 and screen_ok(ref, new))
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new))
        audio_checks(label, ref, new, quiet=True)


def power_on(wait=9.5, vol=25):
    amps = [Amp(REF), Amp(NEW)]
    for amp in amps:
        amp.unmutes = []
        amp.e.hooks[UNMUTE_CALL] = lambda em, amp=amp: amp.unmutes.append(em.cycles / CLOCK_HZ)
        amp.set_pin(0xC0, 5, 0)
        amp.boot()
        amp.press(NEC_POWER)
        amp.wait(wait)
        amp.e.iram[0x31] = vol
    return amps


def press_both(amps, cmd, secs):
    for amp in amps:
        amp.press(cmd)
    for amp in amps:
        amp.wait(secs)


def audio_state(amp):
    return {k: v for k, v in amp.state.items() if k != BACKLIGHT}


def mute_scenarios():
    """The mute key, whole firmware: the reference goes home on it (and on the volume page only goes
    home, without toggling); this image toggles the same way and shows the volume page."""
    print("\nThe mute key (NEC 0x%02X), whole firmware, against the reference" % NEC_MUTE)
    label = "mute_home    "
    ref, new = amps = power_on()
    w = Watch(new)
    press_both(amps, NEC_MUTE, 1.0)
    check("%sfrom home: both muted, the same audio state; here page 2, the muted volume page settled (the digits "
          "blinking, no bar cell lit, the lamp red)" % label,
          muted(ref.e) and muted(new.e) and audio_state(ref) == audio_state(new) and new.page == 2 and
          xstate(new.e).st == 2 and xscreen_ok(new.e) and all(v == bp.GHOST for v in xstate(new.e).lv[E_BAR:]),
          xscreen_diff(new.e))
    new.lcd.save_png(os.path.join(HERE, "build", "mute_home.png"))
    for amp in amps:
        amp.wait(2.6)
    check("%sthen the exit, home = home_model (the icon and the lamp red)" % label,
          new.page == 1 and xstate(new.e).st == 0 and home_ok(new.e), home_diff(new.e))
    press_both(amps, NEC_MUTE, 1.0)
    check("%sunmute: both playing again, the same audio state, the page shown settled = vol_model" % label,
          not muted(ref.e) and not muted(new.e) and audio_state(ref) == audio_state(new) and new.page == 2 and vol_settled(new.e),
          vol_diff(new.e))
    for amp in amps:
        amp.wait(2.6)
    check("%sback home = home_model" % label, new.page == 1 and home_ok(new.e), home_diff(new.e))
    audio_checks(label, ref, new, quiet=True)
    # on the open page: the reference only goes home; here it toggles (compared with the reference muted from home)
    label = "mute_on_page "
    ref, new = amps = power_on()
    press_both(amps, NEC_VOL_UP, 0.6)
    ref.wait(2.6)                                    # the reference's page times out before its key
    press_both(amps, NEC_MUTE, 1.0)
    check("%sthe key on the open page: muted here as the reference from home, the same audio state, page 2 kept, "
          "the muted page settled" % label,
          muted(ref.e) and muted(new.e) and audio_state(ref) == audio_state(new) and new.page == 2 and
          xstate(new.e).st == 2 and xscreen_ok(new.e), xscreen_diff(new.e))
    press_both(amps, NEC_VOL_UP, 1.0)
    check("%sa volume key while muted: unmuted first as stock, the same audio state, the page settled = vol_model"
          % label, not muted(new.e) and not muted(ref.e) and audio_state(ref) == audio_state(new) and vol_settled(new.e),
          vol_diff(new.e))
    STEP_MS["mute"] = w.worst()


def tint_scenarios():
    print("\nStatus tint across an input change (whole firmware)")
    LOCK = (0xC0, 2, 0)
    cases = (("usb_nosig_source_lock", [], NEC_SOURCE, [LOCK], "Digital input", (None, False)),
             ("usb_nosig_source_nolock", [], NEC_SOURCE, [], "Digital input", ("No signal", True)),
             ("usb_nosig_select_bt", [], NEC_BT, [], "initializing", ("Searching...", True)),
             ("usb_nosig_select_aux", [], 0x15, [], "Analog input", ("Analog input", False)),
             ("bt_searching_source", [(NEC_BT, 4.0)], NEC_SOURCE, [], "Digital input", ("Disconnected", True)),
             ("bt_searching_bt_key", [(NEC_BT, 4.0)], 0x0E, [], "BT Reconnect", ("Searching...", True)))
    lit = bp.status_ink(bp.MINT)
    for name, setup, cmd, pins, placeholder, (text, lost) in cases:
        amp = Amp(NEW)
        amp.boot()
        amp.press(NEC_POWER)
        amp.wait(9.5)
        for c, t in setup:
            amp.press(c)
            amp.wait(t)
        e = amp.e
        check("%-24s before the key: %r red (no signal)" % (name, buffer_text(e, bp.SMALL_BUF)),
              status_tint(e) == bp.RED_LIT and home_ok(e), home_diff(e))
        for p in pins:
            amp.set_pin(*p)
        amp.press(cmd)
        amp.wait(0.3)
        check("%-24s 0.3 s after the key: %r lit" % (name, placeholder),
              buffer_text(e, bp.SMALL_BUF) == placeholder and status_tint(e) == lit and e.xram[bp.PP_SIG] == 1,
              "(%r, %s)" % (buffer_text(e, bp.SMALL_BUF), status_tint(e) and "%04X" % status_tint(e)))
        amp.wait(4.2)
        got = buffer_text(e, bp.SMALL_BUF)
        check("%-24s once the loader has run: %r %s" % (name, got, "red" if lost else "lit"),
              (text is None or got == text) and status_tint(e) == (bp.RED_LIT if lost else lit) and home_ok(e), home_diff(e))


# ---- INT1 at a volume press ----------------------------------------------------------------------
INT1_T0 = 9.0


def int1_job(offset_ms):
    out = []
    for img in (REF, NEW):
        amp = Amp(img)
        hits = {"dac": [], "unmute": []}
        amp.e.hooks[DAC_RECONFIG] = lambda em: hits["dac"].append(em.cycles / CLOCK_HZ)
        amp.e.hooks[UNMUTE_CALL] = lambda em: hits["unmute"].append(em.cycles / CLOCK_HZ)
        amp.set_pin(0xC0, 5, 0)
        amp.boot()
        amp.press(NEC_POWER)
        amp.wait(INT1_T0 + offset_ms / 1000)
        t = amp.t
        amp.press(NEC_VOL_UP)
        e = amp.e
        e.iram[0x21] |= 0x10
        e.iram[0x43], e.iram[0x44] = 0, 30
        e.iram[0x4E] = 0xFF
        amp.wait(1.5)
        dac = [c for c in hits["dac"] if c >= t]
        un = [c for c in hits["unmute"] if c >= t]
        tr = audio_transitions(amp)
        out.append((t, dac[:1], un[:1], [(round(c, 4), s) for c, s in tr if c >= t - 0.001]))
    return offset_ms, out


def int1():
    print("\nINT1 receiver event at a Vol+ press (USB, settled), 100 offsets 1 ms apart, against the reference")
    t0 = time.time()
    with mp.get_context("fork").Pool() as pool:
        res = pool.map(int1_job, range(100))
    order_bad, late_bad, audio_bad, shifts, race, race_bad = [], [], [], [], [], []

    def key_first(a, d):
        v0 = dict(a[0][1]).get(("njw", 16)) if a else None
        kv = next((c for c, s in a if dict(s).get(("njw", 16)) != v0), None)
        return kv is not None and bool(d) and kv <= d[0]
    for off, ((tr, dr, ur, ar), (tn, dn, un, an)) in res:
        if not (dn and un and dn[0] < un[0]):
            order_bad.append(off)
        if not (ur and un and un[0] - ur[0] <= 0.10):
            late_bad.append(off)
        else:
            shifts.append(un[0] - ur[0])
        if key_first(ar, dr) != key_first(an, dn):
            race.append(off)
            if not (len(ar) == len(an) and ar and an and ar[-1][1] == an[-1][1] and dn and dr and (dn[0] - tn) - (dr[0] - tr) <= 0.10):
                race_bad.append(off)
        elif [s for _, s in ar] != [s for _, s in an] or any(cn - cr > 0.10 for (cr, _), (cn, _) in zip(ar, an)):
            audio_bad.append(off)
    check("DAC reconfiguration (0x46A0) before the unmute (0x33FB), every offset", not order_bad, str(order_bad[:8]))
    check("unmute no later than the reference + 0.10 s, every offset", not late_bad,
          "(shift %+.3f .. %+.3f s)" % (min(shifts), max(shifts)) if shifts else str(late_bad[:8]))
    print("    press/format-poll race resolved differently at offsets %s" % race)
    check("where the key/poll order differs (%d offsets): the same number of audio states, the same final state, "
          "the DAC reconfiguration no later than the reference + 0.10 s" % len(race), not race_bad, str(race_bad[:8]))
    check("audio states after the press: same order, none more than 0.10 s later, every other offset", not audio_bad, str(audio_bad[:8]))
    print("  %d runs x 2 images in %.0f s" % (len(res), time.time() - t0))


# ---- the IR sweep --------------------------------------------------------------------------------
SWEEP_STATES = ["standby", "home", "volume", "volume_hp", "menu"]
VOL_SETTLE = 0.6


def reach(img, st):
    a = Amp(img, log_audio=False)
    a.set_pin(0xC0, 5, 0)
    a.boot()
    if st != "standby":
        a.press(NEC_POWER); a.wait(8.0)
    if st == "volume":
        a.press(NEC_VOL_UP); a.wait(VOL_SETTLE)
    elif st == "volume_hp":
        a.e.iram[0x2B] = 2
        a.press(NEC_VOL_UP); a.wait(VOL_SETTLE)
    elif st == "menu":
        a.press(NEC_MENU_OPEN); a.wait(1.5)
    return a


def run(img, st, cmd):
    amp = reach(img, st)
    amp.press(cmd)
    amp.wait(0.6)
    return amp


def outcome(amp):
    e = amp.e
    return (amp.page, amp.powered) + tuple(e.iram[a] for a in (0x31, 0x52, 0x47, 0x2B, 0x39, 0x17)) + \
        (e.sfr[0xA0], e.sfr[0x80] & 0x46, e.sfr[0xC0] & 0x41)


MUTE_STATES = ("home", "volume", "volume_hp")


def mute_job(st):
    base = reach(REF, st)
    if base.page == 2:
        base.wait(2.6)
    base.press(NEC_MUTE)
    base.wait(0.6)
    new = run(NEW, st, NEC_MUTE)
    ob, on = outcome(base), outcome(new)
    m = xstate(new.e)
    ok = muted(base.e) and muted(new.e) and base.page == 1 and m.st == 2 and xscreen_ok(new.e)
    return st, NEC_MUTE, (2,) + ob[1:], on, ok, False


def job(args):
    st, cmd = args
    if cmd == NEC_MUTE and st in MUTE_STATES:
        return mute_job(st)
    base, new = run(REF, st, cmd), run(NEW, st, cmd)
    ob, on = outcome(base), outcome(new)
    ok = screen_ok(base, new)
    if not ok and base.powered and new.powered and base.page == new.page == 1:
        for amp in (base, new):
            amp.wait(3.0)
        ok = (new.page == 1 and home_ok(new.e)) or new.lcd.gram == base.lcd.gram
        return st, cmd, ob, on, ok, True
    return st, cmd, ob, on, ok, False


def sweep():
    print("\nIR sweep: 256 commands x %d states, against the reference" % len(SWEEP_STATES))
    t0 = time.time()
    pages = {st: (reach(NEW, st).page, reach(NEW, st).powered) for st in SWEEP_STATES}
    check("snapshots in the intended states", pages["standby"][1] is False and pages["home"] == (1, True)
          and pages["volume"][0] == 2 and pages["volume_hp"][0] == 2 and pages["menu"][0] >= 3, str(pages))
    a1, a2 = run(NEW, "volume", NEC_VOL_UP), run(NEW, "volume", NEC_VOL_UP)
    check("snapshot runs are repeatable", outcome(a1) == outcome(a2) and a1.lcd.gram == a2.lcd.gram)
    print("  reached all states in %.0f s" % (time.time() - t0), flush=True)
    jobs = [(st, cmd) for st in SWEEP_STATES for cmd in range(256)]
    with mp.get_context("fork").Pool() as pool:
        res = pool.map(job, jobs, chunksize=8)
    for st in SWEEP_STATES:
        diff_ = [c for s, c, a, b, ok, later in res if s == st and a != b]
        scr = [c for s, c, a, b, ok, later in res if s == st and not ok]
        later = [c for s, c, a, b, ok, lt in res if s == st and lt]
        if later:
            print("    %-10s home not finished 0.6 s after %s: checked once the periodic refresh has run" % (st, " ".join("%02X" % c for c in later)))
        check("%-10s 256 commands: same page, power, volumes, input, output, EQ, pins" % st, not diff_, str(["%02X" % c for c in diff_[:8]]))
        check("%-10s screens as expected (home: home_model; volume: settled vol_model; other: identical to the reference)" % st,
              not scr, str(["%02X" % c for c in scr[:8]]))
    print("  sweep in %.0f s" % (time.time() - t0))


# ---- every stock page, with the big-font trap on ----------------------------------------------
KEY_INJECT = 0x3DAF


def key_injector(amp):
    cell = [None]

    def inject(em):
        if cell[0] is not None:
            em.setR(7, cell[0])
            cell[0] = None
    amp.e.hooks[KEY_INJECT] = inject

    def press_key(code):
        cell[0] = code
        amp.press(0x00)
    return press_key


MENU_ITEMS = ["Input", "Output", "EQ", "Treble", "Bass", "Filter", "Color", "BT Clear", "Dimmer", "RESET"]
VALUE_PAGES = (7, 8)
LIST_PAGES = (4, 5, 6, 9, 10, 12)
VERSION_Y = 0x55


def stock_page_walk():
    print("\nEvery stock page with the big-font trap on, against the reference")
    amps = [Amp(REF), Amp(NEW)]
    for amp in amps:
        amp.set_pin(0xC0, 5, 0)
        amp.boot()
    ref, new = amps
    keys = [key_injector(amp) for amp in amps]

    def both(cmd, secs):
        for amp in amps:
            if cmd is not None:
                amp.press(cmd)
            amp.wait(secs)

    def same(label):
        if new.page == 13:
            rows = set(range(VERSION_Y, VERSION_Y + 24))
            eq = all(px(new.e, x, y) == px(ref.e, x, y) for x in range(W) for y in range(H) if y not in rows)
            label += " (version line apart)"
        else:
            eq = new.lcd.gram == ref.lcd.gram
        check("%-28s page %2d: identical to the reference" % (label, new.page), eq and new.page == ref.page, "(pages %d / %d)" % (new.page, ref.page))

    both(NEC_POWER, 8.0)
    check("power on: home = home_model", home_ok(new.e), home_diff(new.e))
    both(NEC_MENU_OPEN, 1.5)
    same("menu")
    for item, name in enumerate(MENU_ITEMS):
        both(NEC_MENU_OPEN, 1.0)
        same("%s (enter)" % name)
        check("%-28s opened page %d" % (name, item + 4), new.page == item + 4, "(page %d)" % new.page)
        if new.page in VALUE_PAGES + LIST_PAGES:
            both(NEC_DOWN, 0.5)
            same("%s down" % name)
            both(NEC_UP, 0.5)
            same("%s up" % name)
        both(NEC_MENU, 1.0)
        same("%s (back)" % name)
        if item < len(MENU_ITEMS) - 1:
            both(NEC_DOWN, 0.5)
            same("down to %s" % MENU_ITEMS[item + 1])
    both(None, 9.5)
    check("menu timeout: home = home_model", home_ok(new.e), home_diff(new.e))
    for code, what in ((0x12, "output toggle"), (0x59, "EQ show")):
        for k in keys:
            k(code)
        both(None, 0.5)
        check("%-28s page 1, big text drawn by the theme (trap silent)" % ("key 0x%02X %s" % (code, what)), new.page == 1, "(page %d)" % new.page)
        both(None, 3.0)
        check("%-28s home = home_model after the refresh" % ("key 0x%02X %s" % (code, what)), home_ok(new.e), home_diff(new.e))
    both(NEC_POWER, 3.0)
    same("standby")
    both(NEC_POWER, 8.0)
    check("power on again: home = home_model", home_ok(new.e), home_diff(new.e))


def report_steps():
    if STEP_MS:
        k, v = max(STEP_MS.items(), key=lambda kv: kv[1])
        print("\nWorst engine tick measured: %.2f ms (%s)" % (v, k))


GROUPS = {
    "unit": [image_diff, test_fonts, test_painters, test_home, test_status_tint, test_draw_volume, test_engine,
             test_enter_vol, test_mute_key, test_align, test_volpage],
    "tour": [tour, input_scenarios, key_scenarios, flag_exit_scenarios, mute_scenarios, tint_scenarios, stock_page_walk],
    "int1": [int1],
    "sweep": [sweep],
}


def main():
    for g in sys.argv[1:] or ["unit", "tour", "int1", "sweep"]:
        for fn in GROUPS[g]:
            fn()
    report_steps()
    print("\nALL PASS" if not fails else "\nFAILURES: %s" % fails)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
