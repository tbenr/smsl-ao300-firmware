#!/usr/bin/env python3
"""Emulator tests for House Numerals hn10.1 (see README.md).

  python3 emu_test.py unit    image diff, then every routine at its hook: the home screen against
                              home_model, the volume page against vol_model, a wipe step by step,
                              entry/exit/reversal/cancel logic, the number roll against roll_box,
                              the line's spring against spring_model (and it against the mock's
                              float integrator)
  python3 emu_test.py tour    whole firmware from reset, lockstep with fast-lcd: the tour, a volume
                              key per input, keys during the wipes, keys on the open page (the
                              roll's frames, the spring, knob-speed repeats, a roll cut by
                              Menu / Source / Power), the stack check
  python3 emu_test.py int1    INT1 receiver event at a Vol+ press, 100 offsets, against fast-lcd
  python3 emu_test.py sweep   all 256 IR commands in five states, against fast-lcd
  python3 emu_test.py         all four
"""
import math
import multiprocessing as mp
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools", "emu"))
sys.path.insert(0, HERE)
import uitest as ut                                             # noqa: E402
from ao300 import Amp, CLOCK_HZ, NEC_POWER, NEC_DOWN, NEC_SOURCE, \
    NEC_VOL_UP, NEC_VOL_DOWN, STATE_KEY                          # noqa: E402
import build_patch as bp                                         # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tools", "patch"))
import pfont                                                     # noqa: E402

BASE = open(bp.BASE_IMAGE, "rb").read()
NEW = open(bp.OUT_IMAGE, "rb").read()
LAB = bp.assemble()[1]
W, H = 320, 170
EASE = bp.EASE
N = bp.STEPS                             # steps per wipe
SBUF_STEP = 11                           # the exit step before which the stock refresh loads the status line
STEP_END = 0x5B2D                        # main_tasks_on, after the lcall uk_tasks (0x5B2A)
fails = []


def check(name, ok, detail=""):
    print("  %-72s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def emu(theme=(0xFF, 0xFF), img=NEW):
    return ut.emu(img, theme)


px, screen, fill_screen, ink_in, stray = ut.px, ut.screen, ut.fill_screen, ut.ink_in, ut.stray

def image_diff():
    print("Image diff vs fast-lcd")
    vp = bp.VERSION_PTR_ADDR
    want = set()
    for addr, orig, op, target in bp.HOOKS:
        new = bytes([op, LAB[target] >> 8, LAB[target] & 0xFF])
        check("hook 0x%04X -> %s" % (addr, target), NEW[addr:addr + 3] == new, NEW[addr:addr + 3].hex(" "))
        want |= {addr + k for k in range(3) if orig[k] != new[k]}
    for s in bp.VOL_ENTRY_SITES:
        new = bp.vol_entry_bytes(LAB["hn_enter_vol"])
        check("volume entry 0x%04X -> lcall hn_enter_vol ; sjmp 0x%04X" % (s, s + len(bp.VOL_ENTRY_ORIG)),
              NEW[s:s + 5] == new, NEW[s:s + 5].hex(" "))
        want |= {s + k for k in range(5) if bp.VOL_ENTRY_ORIG[k] != new[k]}
    for addr, orig, fn, note in bp.FIX_PATCHES:
        new = fn(LAB)
        check("patch 0x%04X: %s" % (addr, note), NEW[addr:addr + len(new)] == new, NEW[addr:addr + len(new)].hex(" "))
        want |= {addr + k for k in range(len(new)) if orig[k] != new[k]}
    changed = {i for i in range(len(BASE)) if BASE[i] != NEW[i]} - {vp + 1, vp + 3}
    check("inside the base image only the hooks and the included patches changed (plus version pointer)", changed == want,
          str(sorted("%04X" % i for i in changed ^ want)))
    ver = (NEW[vp + 1] << 8) | NEW[vp + 3]
    check("version pointer -> %r" % bp.VERSION_TEXT,
          NEW[ver:ver + len(bp.VERSION_TEXT) + 1] == bp.VERSION_TEXT.encode() + b"\0")
    check("gap up to 0x%04X left erased" % bp.CODE_ADDR, all(b == 0xFF for b in NEW[len(BASE):bp.CODE_ADDR]))
    check("image ends below 0xF400", len(NEW) <= 0xF400, "(%d bytes)" % len(NEW))
    check("new XDATA state inside 0x0100..0x01FF", 0x0100 <= bp.HN_N and bp.XDATA_END < 0x0200)
    import re
    java = open(os.path.join(ROOT, "tools", "disasm", "SmslAo300Labels.java")).read()
    named = {n: int(a, 16) for a, n in re.findall(r'\{0x([0-9A-F]{4}), "((?:h[nvhm]|uk|pf)_\w+)"\}', java)}
    lab = dict(LAB, hn_ease=LAB["ease"], hn_names=LAB["names"], hn_names8=LAB["names8"], hn_rolltab=LAB["ro_tab"],
               hn_spkt=LAB["sp_kt"])
    wrong = sorted(k for k in named if named[k] != lab.get(k))
    check("SmslAo300Labels.java: the %d hn_/hv_/hh_/hm_/uk_/pf_ labels match this build" % len(named), not wrong, str(wrong))


# ---- the painter ---------------------------------------------------------------------------
STR_AT = ut.STR_AT


def set_fp(e, *args, **kw):
    ut.set_fp(e, LAB, bp.KIT, *args, **kw)


def fp_end(e):
    return ut.fp_end(e, bp.KIT)


def paint(e, *args, **kw):
    return ut.paint(e, LAB, bp.KIT, *args, **kw)


def firmware_strings():
    return ut.firmware_strings(BASE)


def sample_rate_strings():
    return ut.sample_rate_strings(BASE)


# ---- the home screen: an independent model --------------------------------------------------
# What hn5's home screen must look like for a firmware state, drawn in Python with the same fonts
# (pfont's render is proven pixel-identical to uk_text in tools/patch/uikit_test.py) and the
# layout constants of build_patch.py. The tag strings come from the stock tag routines, run on the
# base image.
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
    """The string home_draw_format_tag (0x41CA) paints for input inp, format fmt (RAM 0x3D) and
    RAM 0x75, or None when it only clears the box."""
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
    return bp.ORANGE if theme == (0xFF, 0xFF) else (theme[0] << 8) | theme[1]


def buffer_text(e, addr, n=25):
    raw = bytes(e.xram[addr:addr + n])
    return raw.split(b"\0")[0].decode("latin-1")


def status_ink(e):
    """The status line's colour: grey, or the reddish mix when the status loader's signal check
    (0x5232 at 0x4016, kept in HN_SIG) found none on a digital input (analogue inputs 6 and 8 show
    "Analog input")."""
    return bp.DIM if e.xram[bp.HN_SIG] or e.iram[0x47] in (6, 8) else bp.DIM_LOST


def model_tag(fb, text, right, acc):
    """A tag as the mock strokes it: a 1-px box with corners of radius 2 (the corner pixel 1/4 ink,
    its two neighbours 3/4, the pixel inside the corner 1/4), the text TAG_PAD in from its edges."""
    t = text[:5].rstrip(" ")
    wd = bp.PF_TAG.width(t)
    w = wd + 2 * bp.TAG_PAD
    x = right - w
    q = pfont.ramp(acc, 0)                    # background, 1/4, 3/4, ink
    for xx in range(x + 2, x + w - 2):
        fb[bp.TAG_Y0][xx] = fb[bp.TAG_Y1][xx] = acc
    for yy in range(bp.TAG_Y0 + 2, bp.TAG_Y1 - 1):
        fb[yy][x] = fb[yy][x + w - 1] = acc
    for cx, cy in ((x, bp.TAG_Y0), (x + w - 1, bp.TAG_Y0), (x, bp.TAG_Y1), (x + w - 1, bp.TAG_Y1)):
        dx, dy = (1 if cx == x else -1), (1 if cy == bp.TAG_Y0 else -1)
        fb[cy][cx], fb[cy][cx + dx], fb[cy + dy][cx], fb[cy + dy][cx + dx] = q[1], q[2], q[2], q[1]
    for yy in range(bp.TAG_Y0 + 1, bp.TAG_Y1):          # the inside, black (the text cell draws its own)
        for xx in range(x + 1, x + w - 1):
            if fb[yy][xx] is None:
                fb[yy][xx] = 0
    bp.PF_TAG.render(fb, t, x + bp.TAG_PAD, bp.TAG_TY, acc, 0)


def home_parts(e):
    """{element: its pixels} for the state in emulator e: {(x, y): colour}, black included."""
    ir = e.iram
    theme = (ir[0x48], ir[0x49])
    acc = accent(theme)
    parts = {}

    def part(name, draw):
        fb = [[None] * W for _ in range(H)]
        draw(fb)
        parts[name] = {(x, y): fb[y][x] for y in range(H) for x in range(W) if fb[y][x] is not None}
    muted = bool(ir[0x22] & 0x02)
    ch = "M" if muted else ("S" if ir[0x2B] == 1 else "H")
    part(bp.HF_ICON, lambda fb: bp.PF_ICON.render(fb, ch, bp.ICON_X, bp.ICON_Y, bp.RED if muted else bp.WHITE, 0))
    v = ir[0x31] if ir[0x2B] == 1 else ir[0x52]
    part(bp.HF_VOL, lambda fb: bp.PF_HVOL.render(fb, str(v), bp.HVOL_X, bp.HVOL_Y, bp.WHITE, 0))
    part(bp.HF_EQ, lambda fb: model_tag(fb, eq_tag_string(ir[0x39]), bp.EQ_RIGHT, acc))
    fmt = format_tag_string(ir[0x47], ir[0x3D], ir[0x75])
    part(bp.HF_FMT, lambda fb: model_tag(fb, fmt, bp.FMT_RIGHT, acc) if fmt is not None else None)
    part(bp.HF_NAME, lambda fb: bp.PF_NAME.render(fb, buffer_text(e, bp.BIG_BUF), bp.HNAME_X, bp.HNAME_Y,
                                                  bp.WHITE, 0, spacing=bp.NAME_SP))
    part(bp.HF_STAT, lambda fb: bp.PF_STATUS.render(fb, buffer_text(e, bp.SMALL_BUF), bp.STAT_X, bp.STAT_Y,
                                                    status_ink(e), 0, spacing=bp.STAT_SP))
    part(bp.HF_BAR, lambda fb: [fb[y].__setitem__(x, acc) for y in range(bp.BAR_Y, bp.BAR_Y + bp.BAR_H)
                                for x in range(bp.BAR_X, bp.BAR_X + bp.BAR_W)])
    return parts


def home_model(e):
    """The whole home screen for e's state, as screen() lays it out ([x][y]): the elements on black."""
    s = [[0] * H for _ in range(W)]
    for pix in home_parts(e).values():
        for (x, y), c in pix.items():
            s[x][y] = c
    return s


def home_ok(e):
    return screen(e) == home_model(e)


def home_diff(e):
    m, s = home_model(e), screen(e)
    for x in range(W):
        for y in range(H):
            if m[x][y] != s[x][y]:
                return "(first difference at %d,%d: %04X, model %04X)" % (x, y, s[x][y], m[x][y])
    return ""


def home_state(e, inp=1, out=1, vol=32, hp=20, mute=False, eq=1, fmt=2, sub=2, status="96kHz", theme=None, sig=True):
    ir = e.iram
    ir[0x45], ir[0x4F] = 1, 1
    e.xram[bp.HN_SIG] = 1 if sig else 0
    ir[0x47], ir[0x2B], ir[0x31], ir[0x52], ir[0x39], ir[0x3D], ir[0x75] = inp, out, vol, hp, eq, fmt, sub
    ir[0x7E] = fmt
    ir[0x22] = (ir[0x22] & ~0x02) | (0x02 if mute else 0)
    if theme:
        ir[0x48], ir[0x49] = theme
    for k, ch in enumerate(status.encode() + b"\0"):
        e.xram[bp.SMALL_BUF + k] = ch


def refresh_draw(e):
    """What home_refresh_periodic draws once its loader has run: hn_hold's stock path (0x4081:
    home_refresh, then the status line at y 135, in the loader's tint)."""
    e.call(LAB["hh_stock"])


def home_draw(e):
    """refresh_draw, timed (ms)."""
    c0 = e.cycles
    refresh_draw(e)
    return (e.cycles - c0) * 1000 / CLOCK_HZ


def status_tint(e):
    """The ink the status line on screen was drawn in: bp.DIM, bp.DIM_LOST, or None (no ink pixel)."""
    cols = {px(e, xx, yy) for xx in range(bp.STAT_X, W) for yy in range(bp.STAT_Y, bp.STAT_Y + bp.PF_STATUS.H)}
    return bp.DIM_LOST if bp.DIM_LOST in cols else bp.DIM if bp.DIM in cols else None


def test_home():
    print("\nhome screen (home_refresh + the status line) against home_model")
    cases = [dict(inp=i) for i in range(1, 9)] + [dict(out=2, hp=7), dict(mute=True), dict(mute=True, out=2)]
    cases += [dict(eq=q) for q in (0, 2, 3, 4, 5, 6, 7, 8, 9)]
    cases += [dict(fmt=f, sub=u) for f in (0, 1, 3, 4, 5, 6) for u in (2, 3, 4, 5)]
    cases += [dict(vol=v) for v in (0, 5, 9, 10, 47, 60)]
    cases += [dict(status=t) for t in ("No signal", "Searching...", "2.8224MHz", "Analog input", "")]
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
    check("a whole home in %.1f ms (the stock refresh: about 45)" % worst, worst < 20)
    e = emu(); home_state(e); home_draw(e)
    e.lcd.save_png(os.path.join(HERE, "build", "unit_home.png"))
    # redraws over a different home leave nothing behind (the shorter texts clear the rest)
    bad = []
    for a_, b_ in ((dict(inp=2, vol=45, fmt=4, sub=3, status="No signal", mute=True),
                    dict(inp=1, vol=5, fmt=2, status="48kHz")),
                   (dict(inp=3, fmt=4, sub=4), dict(inp=4, status="Searching...")),
                   (dict(out=2, hp=60), dict(out=1, vol=1)),
                   (dict(inp=1, status="22.5792MHz"), dict(inp=6, status="Analog input")),
                   (dict(inp=6, status="Analog input"), dict(inp=5, status=""))):
        e = emu()
        home_state(e, **a_); home_draw(e)
        home_state(e, **b_); home_draw(e)
        if not home_ok(e):
            bad.append((a_, b_, home_diff(e)))
    check("home over a different home: = home_model of the second (texts, volume, tags, icon)", not bad, str(bad[:2]))
    # every string the firmware has, as the status line and (the ones in capitals) as the name
    strings = sorted(set(firmware_strings() + sample_rate_strings()))
    bad = []
    for t in strings:
        for buf, y, entry, part in ((bp.SMALL_BUF, bp.STATUS_Y, 0x3A53, bp.HF_STAT),
                                    (bp.BIG_BUF, bp.NAME_Y, 0x298B, bp.HF_NAME)):
            if buf == bp.BIG_BUF and t != t.upper():
                continue
            e = emu(); home_state(e)
            fill_screen(e, 0x1234)
            for k, ch in enumerate(t.encode() + b"\0"):
                e.xram[buf + k] = ch
            e.setR(6, 0); e.setR(7, y)
            e.call(entry)
            pix = home_parts(e)[part]
            ys = {yy for _, yy in pix} or {y}
            want = all(px(e, x, yy) == pix.get((x, yy), 0 if x >= (18 if part == bp.HF_STAT else 16) else 0x1234)
                       for x in range(W) for yy in range(min(ys), max(ys) + 1))
            if not want or stray_rows(e, min(ys), max(ys)):
                bad.append((t, part))
    check("%d firmware strings as the status line and the name (capitals): the element, the rest of its rows "
          "black, nothing else drawn" % len(strings), not bad, str(bad[:4]))
    # the takeover keeps big_text_render's own side effect on 0x22.4 (its narrow-character scan)
    bad = []
    for t in ("USB", "BT", "S-BASS", "MQA."):
        got = []
        for img in (BASE, NEW):
            e = emu(img=img); e.iram[0x45] = 1; e.iram[0x22] = 0x10
            for k, ch in enumerate(t.encode() + b"\0"):
                e.xram[bp.BIG_BUF + k] = ch
            e.setR(6, 0); e.setR(7, bp.NAME_Y)
            e.call(0x298B)
            got.append(e.iram[0x22] & 0x10)
        if got[0] != got[1]:
            bad.append(t)
    check("page-1 name: 0x22.4 left as big_text_render's scan leaves it", not bad, str(bad))
    # during a wipe the elements draw their text only (the band behind them is black already)
    got = []
    for mode in (0, 2):
        e = emu(); home_state(e)
        for buf, y, entry, long_, short in ((bp.BIG_BUF, bp.NAME_Y, 0x298B, "COAXIAL", "USB"),
                                            (bp.SMALL_BUF, bp.STATUS_Y, 0x3A53, "22.5792MHz", "48kHz")):
            for t, m in ((long_, 0), (short, mode)):
                e.xram[bp.HN_MODE] = m
                for k, ch in enumerate(t.encode() + b"\0"):
                    e.xram[buf + k] = ch
                e.setR(6, 0); e.setR(7, y)
                e.call(entry)
        nx = bp.HNAME_X + bp.PF_NAME.width("USB", bp.NAME_SP) + 2          # past the shorter texts
        sx = bp.STAT_X + bp.PF_STATUS.width("48kHz", bp.STAT_SP) + 2
        got.append(ink_in(e, nx, bp.HNAME_Y, W - nx, bp.PF_NAME.H) or ink_in(e, sx, bp.STAT_Y, W - sx, bp.PF_STATUS.H))
    check("a shorter name / status line clears the rest of the longer one, except during a wipe "
          "(the wipe's band is black)", got == [False, True], str(got))


def stray_rows(e, y0, y1):
    """Ink outside rows y0..y1 (the pattern 0x1234 counts as untouched)."""
    return any(px(e, x, y) not in (0, 0x1234) for x in range(W) for y in range(H) if not y0 <= y <= y1)


def test_status_tint():
    print("\nthe status line's tint: reddish only for the text the status loader's no-signal check decided")
    for inp, text, sig in ((2, "No signal", 0), (4, "Searching...", 0), (5, "Disconnected", 0), (2, "96kHz", 1)):
        e = emu()
        home_state(e, inp=inp, status=text, sig=bool(sig))
        refresh_draw(e)
        want = bp.DIM if sig else bp.DIM_LOST
        check("the refresh's draw after the loader (0x4081), input %d %r, signal %d: %s, HN_SIG kept" %
              (inp, text, sig, "grey" if sig else "reddish"),
              status_tint(e) == want and e.xram[bp.HN_SIG] == sig and home_ok(e), home_diff(e))
    # any other page-1 draw at y 135 (input_apply's placeholder 0x4C29, the BT key 0x10A1, eq_show 0x396A,
    # 0x532E) is not the loader's text: grey, whatever the last check found
    for inp, text in ((2, "Digital input"), (4, "initializing"), (4, "BT Reconnect"), (1, "Bass boost")):
        e = emu()
        home_state(e, inp=inp, status=text, sig=False)       # the previous input had no signal
        e.setR(6, 0); e.setR(7, bp.STATUS_Y)
        e.call(0x3A53)
        check("small_text_render at y 135 not from the loader, input %d %r after a no-signal check: grey, "
              "HN_SIG 1" % (inp, text), status_tint(e) == bp.DIM and e.xram[bp.HN_SIG] == 1)
        refresh_draw(e)                                        # a redraw without the loader keeps it grey
        check("    and stays grey when redrawn", status_tint(e) == bp.DIM and home_ok(e))


def test_name_ptr():
    print("\nhn_name_ptr")
    for inp, addr, text in bp.INPUT_NAMES[:6]:
        e = emu()
        e.iram[0x47] = inp
        e.call(LAB["hn_name_ptr"])
        check("input %d -> 0x%04X %s" % (inp, addr, text), e.C == 0 and ((e.R(2) << 8) | e.R(3)) == addr)
    for inp in (0, 7, 8, 0xFF):
        e = emu()
        e.iram[0x47] = inp
        e.call(LAB["hn_name_ptr"])
        check("input %d -> no name (C=1)" % inp, e.C == 1)


# ---- the volume page: an independent model ----------------------------------------------------
# What the volume page must look like for a firmware state, drawn in Python with the same fonts and
# the layout constants of build_patch.py: the name (inputs 1..6), the status line as loaded into
# XDATA 0x50 (tinted like the home's), the divider, "VOL", the number right-aligned, the position
# line, the dB caption from the mock's copy of the stock volume table, "max 60".
VOL_TABLE = [35, 36, 38, 40, 42, 44, 46, 48, 50, 52, 54, 56, 58, 60, 62, 64, 66, 68, 70, 72, 74, 76, 78, 80, 82,
             84, 87, 90, 93, 96, 99, 102, 105, 108, 111, 114, 117, 120, 123, 126, 129, 132, 135, 138, 141,
             144, 147, 150, 153, 156, 159, 162, 165, 168, 171, 174, 177, 180, 183, 186, 255]   # ui_themes.html


def db_caption(v):
    """The mock's fmtDb(v) + " dB" in the build's 8-cell form: "_" is the minus sign, "~" infinity."""
    if v <= 0:
        return "  _~ dB "
    half = VOL_TABLE[60 - v] - 35                       # half-dB steps below step 60
    whole, frac = divmod(half, 2)
    return (("" if half == 0 else "_") + str(whole)).rjust(3) + "." + ("5" if frac else "0") + " dB"


def fill(fb, x, y, w, h, c):
    for yy in range(y, y + h):
        for xx in range(x, x + w):
            fb[yy][xx] = c


def vol_parts(e, v=None, split=None):
    """{element: its pixels} of the volume page for e's state ({(x, y): colour}, black included);
    v: the volume shown (default: the active output's, as hn_draw_volume takes it); split: the line's
    split column (default: the volume's, the spring at rest)."""
    ir = e.iram
    acc = accent((ir[0x48], ir[0x49]))
    if v is None:
        v = ir[0x31] if ir[0x2B] == 1 else ir[0x52]
    v = min(v, 60)
    parts = {}

    def part(name, draw):
        fb = [[None] * W for _ in range(H)]
        draw(fb)
        parts[name] = {(x, y): fb[y][x] for y in range(H) for x in range(W) if fb[y][x] is not None}
    name = {inp: text for inp, _, text in bp.INPUT_NAMES[:6]}.get(ir[0x47])
    part(bp.VF_NAME, lambda fb: bp.PF_VNAME.render(fb, name, bp.VNAME_X, bp.VNAME_Y, bp.WHITE, 0, spacing=bp.VNAME_SP)
         if name else None)
    def status(fb):
        fill(fb, bp.VSTAT_X, bp.VSTAT_Y, bp.VSTAT_END - bp.VSTAT_X + 1, bp.PF_MONO.H, 0)   # the rest of a longer text
        bp.PF_MONO.render(fb, buffer_text(e, bp.SMALL_BUF), bp.VSTAT_X, bp.VSTAT_Y, status_ink(e), 0, spacing=bp.VSTAT_SP)
    part(bp.VF_STAT, status)
    part(bp.VF_DIV, lambda fb: fill(fb, bp.VDIV_X, bp.VDIV_Y, 1, bp.VDIV_H, bp.DIVIDER))
    part(bp.VF_VOL, lambda fb: bp.PF_MONO.render(fb, "VOL", bp.VLBL_X, bp.VLBL_Y, acc, 0, spacing=bp.VLBL_SP))

    part(bp.VF_NUM, lambda fb: roll_box(fb, str(v)))
    part(bp.VF_LINE, lambda fb: line_model(fb, bp.VLINE_X + int(round(bp.VLINE_W * v / 60)) if split is None else split,
                                           acc))
    part(bp.VF_CAP, lambda fb: bp.PF_MONO.render(fb, db_caption(v), bp.VCAP_X, bp.VCAP_Y, bp.DIM, 0))
    part(bp.VF_CAPR, lambda fb: bp.PF_MONO.render(fb, "max 60", bp.VCAPR_RIGHT, bp.VCAP_Y, bp.FAINT, 0, align=1))
    return parts


def line_model(fb, split, acc, x0=0):
    """The position line with the accent up to split - 1, the track colour from it; columns from x0."""
    for x in range(max(x0, bp.VLINE_X), bp.VLINE_X + bp.VLINE_W):
        for y in range(bp.VLINE_Y, bp.VLINE_Y + bp.VLINE_H):
            fb[y][x] = acc if x < split else bp.TRACK


# ---- the number roll: an independent model of each frame (the mock's drawVol, one number a frame)
ROLL_BOX = (bp.ROLL_X0, bp.ROLL_X1, bp.ROLL_Y0, bp.ROLL_Y1)


def grey565(g):
    return ((g * 31 + 127) // 255) << 11 | ((g * 63 + 127) // 255) << 5 | ((g * 31 + 127) // 255)


def roll_frame(n, up=True):
    """Frame n (1..14) of the mock's roll: (old?, cell row offset, ink). k = n / 14, e = 1 - (1 - k)^3;
    the mock draws the old number at alpha 1 - e, baseline - 20 dir e, the new one at alpha e,
    baseline + 20 dir (1 - e); a frame shows the one with the larger alpha, its offset rounded to
    rows (half up on the size, so a step down is the mirror image of a step up)."""
    k = n / 14
    e = 1 - (1 - k) ** 3
    d = 1 if up else -1
    if e < 0.5:
        return True, -d * int(math.floor(20 * e + 0.5)), grey565(int(math.floor(255 * (1 - e) + 0.5)))
    return False, d * int(math.floor(20 * (1 - e) + 0.5)), grey565(int(math.floor(255 * e + 0.5)))


def roll_box(fb, text, dy=0, ink=bp.WHITE):
    """The number's box as a frame leaves it: black, the number right-aligned to VNUM_RIGHT with its
    cell dy rows off, in ink, only the box's rows."""
    x0, x1, y0, y1 = ROLL_BOX
    fill(fb, x0, y0, x1 - x0 + 1, y1 - y0 + 1, 0)
    bp.PF_VNUM.render(fb, text, bp.VNUM_RIGHT, bp.VNUM_Y + dy, ink, 0, align=1, rows=(y0, y1))


# ---- the line's spring: a bit-exact model of the 8051 arithmetic, and the mock's float integrator
def wrap16(v):
    return (v + 0x8000) % 0x10000 - 0x8000


def sp_mulq(x, k):
    """hs_mulx: x * k / 65536 rounded half away from 0 (on the magnitude)."""
    return -((-x * k + 0x8000) >> 16) if x < 0 else (x * k + 0x8000) >> 16


def spring_model(p, v, target):
    """One tick of hn_spring: position p and velocity v in pixels * 64 (per tick), target in pixels.
    Returns (p, v)."""
    t6 = target << bp.SPRING_Q
    e = wrap16(p - t6)
    if e == 0 and v == 0:
        return p, v
    dp = wrap16(sp_mulq(v, bp.SPRING_K2) - sp_mulq(e, bp.SPRING_K1))
    vn = wrap16(sp_mulq(v, bp.SPRING_K4) - sp_mulq(e, bp.SPRING_K3))
    p, en = wrap16(p + dp), wrap16(e + dp)
    if abs(en) < bp.SPRING_SE and abs(vn) < bp.SPRING_SV:
        return t6, 0
    return p, vn


def spring_split(p):
    """The split column hs_split draws for position p."""
    return bp.VLINE_X + max(0, min(bp.VLINE_W, (p + 32) >> 6))


def fill_px(v):
    """The line's fill for volume v, pixels (the mock: round(288 * v / 60))."""
    return int(round(bp.VLINE_W * v / 60))


def mock_spring(x, v, target):
    """The mock's spring(s, target, 0.01, 200, 28), s in units of the line (0..1)."""
    n = math.ceil(0.01 / (1 / 240))
    h = 0.01 / n
    for _ in range(n):
        a = 200 * (target - x) - 28 * v
        v += a * h
        x += v * h
    return x, v


def compose(parts, only=None):
    """A screen ([x][y]) of the given parts (all of them by default) on black."""
    s = [[0] * H for _ in range(W)]
    for b, pix in parts.items():
        if only is None or b in only:
            for (x, y), c in pix.items():
                s[x][y] = c
    return s


def vol_model(e, v=None, only=None, split=None):
    return compose(vol_parts(e, v, split), only)


def vol_ok(e, v=None, only=None, split=None):
    return screen(e) == vol_model(e, v, only, split)


def vol_diff(e, v=None, only=None, split=None):
    m, s = vol_model(e, v, only, split), screen(e)
    for x in range(W):
        for y in range(H):
            if m[x][y] != s[x][y]:
                return "(first difference at %d,%d: %04X, model %04X)" % (x, y, s[x][y], m[x][y])
    return ""


def vol_boxes():
    """x0, x1, y0, y1 of each volume-page element as the wipe reveals it (VOL_ELEMENTS' columns)."""
    rows = {bp.VF_NAME: (bp.VNAME_Y, bp.PF_VNAME.H), bp.VF_STAT: (bp.VSTAT_Y, bp.PF_MONO.H),
            bp.VF_DIV: (bp.VDIV_Y, bp.VDIV_H), bp.VF_VOL: (bp.VLBL_Y, bp.PF_MONO.H),
            bp.VF_NUM: (bp.VNUM_Y, bp.PF_VNUM.H), bp.VF_LINE: (bp.VLINE_Y, bp.VLINE_H),
            bp.VF_CAP: (bp.VCAP_Y, bp.PF_MONO.H), bp.VF_CAPR: (bp.VCAP_Y, bp.PF_MONO.H)}
    rows[bp.VF_NUM] = (bp.ROLL_Y0, bp.ROLL_Y1 - bp.ROLL_Y0 + 1)          # the number's box
    return {b: (x0, x1, rows[b][0], rows[b][0] + rows[b][1] - 1) for b, _, x0, x1 in bp.VOL_ELEMENTS}


VOL_NAMES = {bp.VF_NAME: "name", bp.VF_STAT: "status", bp.VF_DIV: "divider", bp.VF_VOL: "VOL", bp.VF_NUM: "number",
             bp.VF_LINE: "line", bp.VF_CAP: "dB", bp.VF_CAPR: "max"}
DYNAMIC = {bp.VF_NUM, bp.VF_LINE, bp.VF_CAP}         # what hn_draw_volume redraws


def entry_screen(parts, before, x, last, acc, revealed=None):
    """The screen after an entry step with the edge at x: the old screen left of it, the 2-px accent
    edge, and right of it the elements the edge has passed (x0 >= x + 2; or `revealed`), the line
    in parts."""
    boxes = vol_boxes()
    s = [[0] * H for _ in range(W)]
    for b, pix in parts.items():
        if (b in revealed) if revealed is not None else (last or boxes[b][0] >= x + 2):
            for (xx, yy), c in pix.items():
                s[xx][yy] = c
        elif b == bp.VF_LINE:
            for (xx, yy), c in pix.items():
                if xx >= x + 2:
                    s[xx][yy] = c
    if not last:
        for xx in range(W):
            for yy in range(H):
                if xx < x:
                    s[xx][yy] = before[xx][yy]
                elif xx < x + 2:
                    s[xx][yy] = acc
    return s


def stock_status(e):
    """XDATA 0x50 as the stock loader (0x4016..0x407E, the base image with the included string
    patches: strings' "Disconnected") fills it for e's RAM state."""
    img = bytearray(BASE)
    for addr, orig, fn, _ in bp.FIX_PATCHES:
        img[addr:addr + len(orig)] = fn(LAB)
    b = ut.emu(bytes(img))
    b.iram[:] = e.iram[:]
    b.pins[0xC0] = e.pins.get(0xC0, (0, 0))    # P4: the signal pins
    b.hooks[0x4081] = lambda em: em.ret()
    b.call(0x4016)
    return buffer_text(b, bp.SMALL_BUF)


def test_draw_volume():
    print("\nhn_draw_volume (the 0x5936 hook): every step, three themes")
    for theme, acc in (((0xFF, 0xFF), bp.ORANGE), ((0xF8, 0x00), 0xF800), ((0x33, 0xBF), 0x33BF)):
        bad = []
        for v in range(61):
            e = emu(theme)
            e.iram[0x2B] = 1
            e.setR(7, v)
            e.call(0x5936)
            if not (vol_ok(e, v, DYNAMIC) and (e.iram[0x48], e.iram[0x49]) == theme):
                bad.append((v, vol_diff(e, v, DYNAMIC)))
        check("theme %02X%02X: steps 0-60: number, line and dB caption = vol_model, nothing else, theme untouched"
              % theme, not bad, str(bad[:2]))
    e = emu(); e.iram[0x2B] = 1; e.setR(7, 25); e.call(0x5936)
    check("XDATA 0x05 = 2 as stock; HN_VOL 25, HN_NUM \"25\", HV_DB \"_39.5 dB\"",
          e.xram[5] == 2 and e.xram[bp.HN_VOL] == 25 and bytes(e.xram[bp.HN_NUM:bp.HN_NUM + 3]) == b"25\0" and
          bytes(e.xram[bp.HV_DB:bp.HV_DB + 9]) == b"_39.5 dB\0")
    caps = {}
    for v in (0, 1, 9, 10, 35, 45, 59, 60):
        e = emu(); e.iram[0x2B] = 1; e.setR(7, v); e.call(0x5936)
        caps[v] = buffer_text(e, bp.HV_DB, 9) if v else "(str_dbinf)"
    check("dB captions: %s" % ", ".join("%d %r" % (v, t) for v, t in caps.items()),
          all(t == db_caption(v) for v, t in caps.items() if v) and caps[60] == "  0.0 dB" and caps[1] == "_75.5 dB")
    e = emu(); e.iram[0x2B] = 2; e.iram[0x52] = 33; e.setR(7, 10); e.call(0x5936)
    check("headphone output draws RAM 0x52 (33), as stock", vol_ok(e, 33, DYNAMIC))
    e = emu(); e.iram[0x2B] = 1; e.setR(7, 75); e.call(0x5936)
    check("a value above 60 is drawn as 60", vol_ok(e, 60, DYNAMIC))
    e = emu(); e.iram[0x2B] = 1
    e.setR(7, 45); e.call(0x5936)
    e.setR(7, 44); e.call(0x5936)
    check("redraw 45 -> 44 leaves nothing behind", vol_ok(e, 44, DYNAMIC), vol_diff(e, 44, DYNAMIC))
    e.setR(7, 4); e.call(0x5936)
    check("redraw 44 -> 4 clears the tens digit's columns (the number is right-aligned)", vol_ok(e, 4, DYNAMIC),
          vol_diff(e, 4, DYNAMIC))
    e.setR(7, 0); e.call(0x5936)
    check("redraw 4 -> 0: \"  _~ dB \" over \" _75.5 dB\"-wide text, nothing left of the line", vol_ok(e, 0, DYNAMIC),
          vol_diff(e, 0, DYNAMIC))
    e.setR(7, 60); e.call(0x5936)
    c0 = e.cycles; e.setR(7, 59); e.call(0x5936)
    ms = (e.cycles - c0) * 1000 / CLOCK_HZ
    check("a volume step with the page not on screen redraws at once in %.2f ms (stock: about 40)" % ms,
          vol_ok(e, 59, DYNAMIC) and ms < 8)
    # during a wipe: only recorded, unless the wipe has revealed the number / the caption (the line is
    # the spring's: hn_draw_volume only changes its target)
    boxes = vol_boxes()
    for vf in (0, bp.VF_NUM, bp.VF_LINE, bp.VF_CAP, bp.VF_NUM | bp.VF_LINE, bp.VF_ALL):
        e = emu(); e.iram[0x2B] = 1
        e.xram[bp.HN_MODE], e.xram[bp.HN_VF] = 1, vf
        e.setR(7, 37); e.call(0x5936)
        got = {b for b in DYNAMIC if ink_in(e, boxes[b][0], boxes[b][2], boxes[b][1] - boxes[b][0] + 1,
                                            boxes[b][3] - boxes[b][2] + 1)}
        want = {b for b in DYNAMIC if vf & b and b != bp.VF_LINE}
        check("wipe running, revealed %-10s: drawn %-16s HN_VOL 37, no roll" %
              (bin(vf), "+".join(VOL_NAMES[b] for b in sorted(want)) or "nothing"),
              got == want and e.xram[bp.HN_VOL] == 37 and e.xram[bp.HR_F] == 0, str(sorted(got)))


def volpage_render(inp=2, vol=25, theme=(0xFF, 0xFF), out=1, hp=0):
    e = emu(theme)
    e.iram[0x47], e.iram[0x2B], e.iram[0x31], e.iram[0x52] = inp, out, vol, hp
    e.call(LAB["hn_volpage"])
    return e


def test_volpage():
    print("\nhn_volpage (page 2 renderer, jump-table entry 0x2143)")
    e = emu()
    e.iram[0x47], e.iram[0x2B], e.iram[0x31] = 2, 1, 25
    e.iram[0x22] |= 0x08
    e.iram[0x32] = e.iram[0x46] = 1
    for k in range(25):
        e.xram[bp.SMALL_BUF + k] = 0x41            # a stale status line: the page loads its own
    c0 = e.cycles
    e.call(LAB["hn_volpage"])
    ms = (e.cycles - c0) * 1000 / CLOCK_HZ
    check("OPTICAL, 25: the whole page = vol_model (name, status, divider, VOL, number, line, captions)",
          vol_ok(e), vol_diff(e))
    check("status line loaded as the stock loader loads it (%r), HN_SLD clear again" % buffer_text(e, bp.SMALL_BUF),
          buffer_text(e, bp.SMALL_BUF) == stock_status(e) and e.xram[bp.HN_SLD] == 0)
    check("the whole page in %.1f ms" % ms, ms < 20)
    check("render flags cleared as by 0x22FA",
          not e.iram[0x22] & 0x08 and e.iram[0x32] == 0 and e.iram[0x46] == 0)
    check("theme colour untouched; the page is on screen (HN_VF all)",
          (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF) and e.xram[bp.HN_VF] == bp.VF_ALL)
    e.lcd.save_png(os.path.join(HERE, "build", "unit_volpage.png"))
    # every input, with and without a signal (P4.5 USB, P4.2 the others; BT and HDMI read the expander)
    bad, texts = [], {}
    for inp in range(1, 9):
        for sig in (0, 1):
            e = emu()
            e.iram[0x47], e.iram[0x2B], e.iram[0x31] = inp, 1, 40
            e.pins[0xC0] = (0x24, 0x24 ^ (0x20 if sig and inp == 1 else 0) ^ (0x04 if sig and inp != 1 else 0))
            e.call(LAB["hn_volpage"])
            texts[(inp, sig)] = (buffer_text(e, bp.SMALL_BUF), status_ink(e) == bp.DIM_LOST)
            if not vol_ok(e) or buffer_text(e, bp.SMALL_BUF) != stock_status(e):
                bad.append((inp, sig, vol_diff(e)))
    print("    status per input (signal pin off / on), reddish marked *: " +
          ", ".join("%d: %s%s / %s%s" % (i, texts[(i, 0)][0], "*" if texts[(i, 0)][1] else "",
                                          texts[(i, 1)][0], "*" if texts[(i, 1)][1] else "") for i in range(1, 9)))
    check("inputs 1-8 x signal pin: page = vol_model, status as the stock loader (inputs 7, 8: no name)",
          not bad, str(bad[:2]))
    check("without a signal the status is reddish on the digital inputs only (BT and HDMI read the expander, not a pin)",
          all(texts[(i, 0)][1] == (i not in (6, 8)) for i in range(1, 9)) and
          not any(texts[(i, 1)][1] for i in (1, 2, 3, 6, 7, 8)))
    for theme in ((0xF8, 0x00), (0x07, 0xE0)):
        e = volpage_render(3, 60, theme)
        check("tint %02X%02X, COAXIAL 60: = vol_model (VOL and the full line in the tint)" % theme, vol_ok(e), vol_diff(e))
    e = emu(); e.iram[0x47], e.iram[0x2B], e.iram[0x31] = 2, 1, 25
    e.xram[bp.HN_MODE] = 1
    e.call(LAB["hn_volpage"])
    check("during a wipe: nothing drawn, volume recorded", not any(e.lcd.gram) and e.xram[bp.HN_VOL] == 25)


# ---- a wipe, step by step ----------------------------------------------------------------------
LOST = ("No signal", "Searching...", "Disconnected")     # the loader's texts when 0x5232 finds no signal (strings: ARC)


def home_setup(e, inp=2, status="No signal"):
    e.iram[0x45] = 1
    e.iram[0x47], e.iram[0x2B], e.iram[0x31] = inp, 1, 25
    e.xram[bp.HN_SIG] = 0 if status in LOST else 1        # the loader's signal check, as hn_signal keeps it
    e.iram[0x3D], e.iram[0x75], e.iram[0x7E] = 2, 2, 2       # PCM
    e.iram[0x4F] = 1
    for k, ch in enumerate(status.encode() + b"\0"):
        e.xram[bp.SMALL_BUF + k] = ch


def home_reference(inp=2, status="No signal"):
    """The home screen as the refresh draws it (home_refresh + the status line), on black."""
    e = emu()
    home_setup(e, inp, status)
    refresh_draw(e)
    return e


def home_boxes(inp=2, status="No signal"):
    """x0, x1, y0, y1 of each home element, as hn5 draws it."""
    name = {1: "USB", 2: "OPTICAL", 3: "COAXIAL", 4: "BT", 5: "ARC", 6: "AUX"}[inp]
    nr = bp.HNAME_X + bp.PF_NAME.width(name, bp.NAME_SP) - 1
    sr = bp.STAT_X + bp.PF_STATUS.width(status, bp.STAT_SP) - 1
    return {bp.HF_ICON: (bp.ICON_X, bp.ICON_END, bp.ICON_Y, bp.ICON_Y + bp.PF_ICON.H - 1),
            bp.HF_VOL: (bp.HVOL_X, bp.HVOL_END, bp.HVOL_Y, bp.HVOL_Y + bp.PF_HVOL.H - 1),
            bp.HF_BAR: (bp.BAR_X, bp.BAR_X + bp.BAR_W - 1, bp.BAR_Y, bp.BAR_Y + bp.BAR_H - 1),
            bp.HF_NAME: (bp.HNAME_X, nr, bp.HNAME_Y, bp.HNAME_Y + bp.PF_NAME.H - 1),
            bp.HF_FMT: (bp.FMT_LEFT, bp.FMT_RIGHT - 1, bp.TAG_Y0, bp.TAG_Y1),
            bp.HF_EQ: (bp.EQ_X, bp.EQ_RIGHT - 1, bp.TAG_Y0, bp.TAG_Y1),
            bp.HF_STAT: (bp.STAT_X, sr, bp.STAT_Y, bp.STAT_Y + bp.PF_STATUS.H - 1)}


def run_steps(e, n):
    times = []
    for _ in range(n):
        c0 = e.cycles
        e.call(LAB["hn_step"])
        times.append((e.cycles - c0) * 1000 / CLOCK_HZ)
    return times


def test_step():
    print("\nhn_step: one wipe step per tick")
    def mock_ease(t):                         # ui_themes.html: const ease = t => ...
        return 4 * t * t * t if t < .5 else 1 - math.pow(-2 * t + 2, 3) / 2
    moves = [EASE[k] - EASE[k + 1] for k in range(N)]
    check("ease table: %d positions 318 -> 0 = round(318 (1 - ease(k / %d))), the mock's cubic, symmetric; "
          "moves %d..%d px (%d steps of 0 px, %d of 1 px)" % (N + 1, N, min(moves), max(moves), moves.count(0),
                                                             moves.count(1)),
          EASE == [round(318 * (1 - mock_ease(k / N))) for k in range(N + 1)] and EASE[0] == 318 and
          EASE[-1] == 0 and min(moves) >= 0 and all(EASE[k] + EASE[N - k] == 318 for k in range(N + 1)), str(EASE))
    # entry: the old page is a pattern; after each step: pattern left of the edge, accent edge,
    # the volume page right of it with only the revealed elements (and the line in parts)
    ref = volpage_render()
    e = emu(); fill_screen(e, 0x1234)
    e.iram[0x47], e.iram[0x2B], e.iram[0x31], e.iram[0x4F] = 2, 1, 25, 1
    e.call(LAB["hn_enter_vol"])
    check("hn_enter_vol: nothing drawn, mode 1, step 0, x 318, HN_VF 0",
          all(v == 0x1234 for v in e.lcd.gram) and e.xram[bp.HN_MODE] == 1 and e.xram[bp.HN_STEP] == 0 and
          (e.xram[bp.HN_X] << 8 | e.xram[bp.HN_X + 1]) == 318 and e.xram[bp.HN_VF] == 0)
    e.setR(7, 25); e.call(0x5936)
    check("0x5936 during the entry: nothing drawn, volume recorded",
          all(v == 0x1234 for v in e.lcd.gram) and e.xram[bp.HN_VOL] == 25)
    bad, order, worst = [], [], 0
    refs = screen(ref)
    boxes = vol_boxes()
    before = screen(e)
    sp, sv = 0, 0                             # the spring, from 0 (hn_enter_vol resets it)
    rev = set()
    times = []
    for k in range(1, N + 1):
        times.append(run_steps(e, 1)[0])
        worst = max(worst, times[-1])
        sp, sv = spring_model(sp, sv, fill_px(25))
        parts = vol_parts(ref, split=spring_split(sp))     # the line right of the edge: the spring's
        if (sp, sv) != spring_state(e):
            bad.append((k, "spring", spring_state(e), (sp, sv)))
        x = EASE[k]
        got_x = e.xram[bp.HN_X] << 8 | e.xram[bp.HN_X + 1]
        if k == N or x != EASE[k - 1]:        # a step that does not move the edge reveals nothing
            rev = {b for b, (bx, bx1, by, by1) in boxes.items() if bx >= x + 2 or k == N}
            drawn = set().union(*order) if order else set()
            if k < N and {bp.VF_NAME, bp.VF_STAT} <= rev - drawn:
                rev.discard(bp.VF_STAT)       # not in the name's step: the status line waits one
        vf = e.xram[bp.HN_VF]
        if vf != sum(rev):
            bad.append((k, "flags %s" % bin(vf)))
        new = [b for b in rev if not any(b in o for o in order)]
        order.append(set(new))
        # before the edge first moves nothing is drawn: it appears with the first step that moves it
        want = before if x == EASE[0] and k < N else entry_screen(parts, before, x, k == N, bp.ORANGE, rev)
        s = screen(e)
        if s != want:
            bad.append((k,) + next((xx, yy, hex(s[xx][yy]), hex(want[xx][yy])) for xx in range(W) for yy in range(H)
                                   if s[xx][yy] != want[xx][yy]))
        if got_x != x:
            bad.append((k, "x", got_x))
    print("    entry reveal: " + ", ".join("%s at step %d (x %d)" % ("+".join(VOL_NAMES[b] for b in sorted(o)), k + 1, EASE[k + 1])
                                           for k, o in enumerate(order) if o))
    print("    entry step times (ms): " + " ".join("%.1f" % t for t in times))
    check("entry: each step x = ease[k]; nothing until the edge first moves, then old page left of the edge, "
          "2-px accent edge, black band, elements once the edge is left of them, the line right of the edge as "
          "spring_model; steps that do not move draw nothing", not bad, str(bad[:3]))
    check("entry: at its end the page = vol_model with the line at the spring's split (%d); mode 0, HN_VF all"
          % spring_split(sp), vol_ok(e, split=spring_split(sp)) and e.xram[bp.HN_MODE] == 0 and
          e.xram[bp.HN_VF] == bp.VF_ALL, vol_diff(e, split=spring_split(sp)))
    check("entry: worst step %.2f ms, the spring's fill included (at most %g)" % (worst, STEP_LIMIT), worst <= STEP_LIMIT)
    STEP_MS["entry"] = worst
    n, ok, tw = settle(e, 25, sp, sv)
    check("entry: the spring settles %d ticks later, as spring_model tick by tick; then the page = hn_volpage's "
          "render (worst tick %.2f ms)" % (n, tw), ok and screen(e) == refs)
    e.call(LAB["hn_step"])
    check("hn_step when idle: nothing", screen(e) == refs and e.xram[bp.HN_STEP] == N)

    # exit: from the volume page to the home screen the stock refresh draws
    for inp, status in ((2, "No signal"), (1, "2.8224MHz"), (4, "Searching...")):
        href = home_reference(inp, status)
        hs = screen(href)
        boxes = home_boxes(inp, status)
        vref = volpage_render(inp)
        vs = screen(vref)
        e = volpage_render(inp)
        home_setup(e, inp, status)
        e.iram[0x59] = 1
        e.call(LAB["hn_clear"])
        started = e.xram[bp.HN_MODE] == 2 and all(e.xram[bp.SMALL_BUF + k] == 0 for k in range(25))
        check("input %d: hn_clear with page 1 and the volume page on screen: exit starts, draws nothing, "
              "text buffers cleared" % inp, started and e.lcd.gram == vref.lcd.gram)
        bad, worst, order = [], 0, []
        sp, sv = spring_state(e)               # on the volume's fill; the exit pulls it to 0
        rev = set()
        for k in range(1, N + 1):
            if k == SBUF_STEP:                # the stock refresh loads the status line 10 ticks in
                for j, ch in enumerate(status.encode() + b"\0"):
                    e.xram[bp.SMALL_BUF + j] = ch
                e.xram[bp.HN_SBUF] = 1
            worst = max(worst, run_steps(e, 1)[0])
            sp, sv = spring_model(sp, sv, 0)
            if k < N:
                vs = screen(vref)
                lm = [[None] * W for _ in range(H)]
                line_model(lm, spring_split(sp), bp.ORANGE)
                for yy in range(bp.VLINE_Y, bp.VLINE_Y + bp.VLINE_H):
                    for xx in range(bp.VLINE_X, bp.VLINE_X + bp.VLINE_W):
                        vs[xx][yy] = lm[yy][xx]
                if (sp, sv) != spring_state(e):
                    bad.append((k, "spring", spring_state(e), (sp, sv)))
            x = 318 - EASE[k]
            moved = x != 318 - EASE[0]        # the edge has moved (it shows from then on)
            if k == N or x != 318 - EASE[k - 1]:  # a step that does not move the edge reveals nothing
                rev = {b for b, (x0, x1, y0, y1) in boxes.items()
                       if k == N or (x1 < x and (b != bp.HF_STAT or k >= SBUF_STEP))}
                drawn = set().union(*order) if order else set()
                if k < N and {bp.HF_NAME, bp.HF_STAT} <= rev - drawn:
                    rev.discard(bp.HF_STAT)   # not in the name's step: the status line waits one
            if e.xram[bp.HN_HF] != sum(rev):
                bad.append((k, "flags", bin(e.xram[bp.HN_HF]), bin(sum(rev))))
            new = [b for b in rev if not any(b in o for o in order)]
            order.append(set(new))
            s = screen(e)
            for xx in range(W):
                for yy in range(H):
                    if k < N and (xx >= x + 2 or not moved):
                        want = vs[xx][yy]
                    elif k < N and xx >= x:
                        want = bp.ORANGE
                    else:
                        want = 0
                        for b, (x0, x1, y0, y1) in boxes.items():
                            if b in rev and x0 <= xx <= x1 and y0 <= yy <= y1:
                                want = hs[xx][yy]
                    if s[xx][yy] != want:
                        bad.append((k, xx, yy, hex(s[xx][yy]), hex(want)))
                        break
                if bad and bad[-1][0] == k:
                    break
        hn = {bp.HF_ICON: "icon", bp.HF_VOL: "volume", bp.HF_BAR: "bar", bp.HF_NAME: "name",
              bp.HF_FMT: "format", bp.HF_EQ: "EQ", bp.HF_STAT: "status"}
        print("    exit reveal (input %d, %r): " % (inp, status) +
              ", ".join("%s at step %d (x %d)" % ("+".join(hn[b] for b in sorted(o)), k + 1, 318 - EASE[k + 1])
                        for k, o in enumerate(order) if o))
        check("input %d exit: volume page right of the edge, edge, home elements once the edge is right of "
              "them (status once loaded)" % inp, not bad, str(bad[:3]))
        check("input %d exit: final screen = the home refresh = home_model; mode 0, HN_VF 0, HN_HF all; the spring "
              "at home (0, still, split %d)" % (inp, bp.VLINE_X),
              e.lcd.gram == href.lcd.gram and home_ok(href) and e.xram[bp.HN_MODE] == 0 and e.xram[bp.HN_VF] == 0 and
              e.xram[bp.HN_HF] == bp.HF_ALL and spring_state(e) == (0, 0) and split_of(e) == bp.VLINE_X)
        check("input %d exit: worst step %.2f ms (at most %g)" % (inp, worst, STEP_LIMIT), worst <= STEP_LIMIT)
        STEP_MS["exit_%d" % inp] = worst

    # reversals: entry turned round into an exit at the same x, and back
    href = home_reference()
    vref = volpage_render()
    bad, notes = [], []
    for turn in range(1, N):
        e = home_reference()
        e.iram[0x4F] = 1
        e.call(LAB["hn_enter_vol"])
        e.setR(7, 25); e.call(0x5936)
        run_steps(e, turn)
        x0 = e.xram[bp.HN_X] << 8 | e.xram[bp.HN_X + 1]
        e.iram[0x59] = 1
        e.call(LAB["hn_clear"])
        xs = []
        for j in range(turn):
            if j == 10:                       # the stock refresh reloads the status line 10 ticks in
                home_setup(e)
                e.xram[bp.HN_SBUF] = 1
            run_steps(e, 1)
            xs.append(e.xram[bp.HN_X] << 8 | e.xram[bp.HN_X + 1])
        ok = e.xram[bp.HN_MODE] == 0 and xs == [318 - EASE[k] for k in range(N - turn + 1, N + 1)]
        s, h = screen(e), screen(href)
        if e.xram[bp.HN_SBUF]:
            same, note = s == h, ""
        else:
            # the exit ended before the stock refresh loaded the status line (10 ticks in): all but the
            # status line is home already, and the refresh's first run then draws the whole home
            sx0, sx1, sy0, sy1 = home_boxes()[bp.HF_STAT]
            same = all(s[xx][yy] == h[xx][yy] for xx in range(W) for yy in range(H)
                       if not (sx0 <= xx <= sx1 and sy0 <= yy <= sy1))
            home_setup(e)
            refresh_draw(e)
            same, note = same and screen(e) == h, "refresh"
        if note:
            notes.append(turn)
        if not (ok and same):
            bad.append((turn, x0, xs[:3]))
    check("entry turned round after each step 1..%d (x 318 .. %d, the still and 1-px steps at both ends "
          "included): exit from there, as many steps, home as the stock refresh (after steps %s: once the "
          "refresh has drawn the status line, tick 10)" % (N - 1, EASE[N - 1], ",".join(map(str, notes))),
          not bad, str(bad[:3]))
    bad = []
    vref27 = screen(volpage_render(vol=27))
    for turn in range(1, N):
        e = volpage_render()
        home_setup(e)
        e.iram[0x59] = 1
        e.call(LAB["hn_clear"])
        run_steps(e, turn)
        x0 = e.xram[bp.HN_X] << 8 | e.xram[bp.HN_X + 1]
        e.iram[0x45] = 2
        e.call(LAB["hn_enter_vol"])
        e.iram[0x31] = 27
        e.setR(7, 27); e.call(0x5936)
        xs = []
        for _ in range(turn):
            run_steps(e, 1)
            xs.append(e.xram[bp.HN_X] << 8 | e.xram[bp.HN_X + 1])
        ok = e.xram[bp.HN_MODE] == 0 and xs == [EASE[k] for k in range(N - turn + 1, N + 1)]
        ok = ok and settle(e, 27)[1]
        if not (ok and screen(e) == vref27 and vol_ok(e) and buffer_text(e, bp.SMALL_BUF)):
            bad.append((turn, x0, xs[:3], vol_diff(e)))
    check("exit turned round by a volume key after each step 1..%d: entry from there, as many steps, page for 27 "
          "once the spring settles, status line loaded again" % (N - 1), not bad, str(bad[:3]))
    e = home_reference(); e.iram[0x4F] = 1
    e.call(LAB["hn_enter_vol"]); e.iram[0x59] = 1; e.call(LAB["hn_clear"])
    check("entry turned round before its first step: stops, screen untouched (the page never showed)",
          e.xram[bp.HN_MODE] == 0 and screen(e) == screen(href))


STEP_MS = {}
STEP_LIMIT = 8.0                          # ms: a step must stay well inside the 10 ms tick


def spring_state(e):
    """(position, velocity) of the line's spring in e (signed, pixels * 64)."""
    return tuple(wrap16(e.xram[a] << 8 | e.xram[a + 1]) for a in (bp.SP_P, bp.SP_V))


def split_of(e):
    return e.xram[bp.HN_SPL] << 8 | e.xram[bp.HN_SPL + 1]


def settle(e, vol, sp=None, sv=None, limit=120):
    """Idle ticks (hn_step with no wipe: the spring and the roll) until the spring is still on vol's
    fill. With sp, sv: each tick must match spring_model, and the line on screen its split. Returns
    (ticks, ok, worst tick in ms)."""
    ok, worst, acc = True, 0.0, accent((e.iram[0x48], e.iram[0x49]))
    for n in range(1, limit + 1):
        worst = max(worst, run_steps(e, 1)[0])
        if sp is not None:
            sp, sv = spring_model(sp, sv, fill_px(vol))
            lm = [[None] * W for _ in range(H)]
            line_model(lm, spring_split(sp), acc)
            ok = ok and spring_state(e) == (sp, sv) and split_of(e) == spring_split(sp) and all(
                px(e, xx, yy) == lm[yy][xx] for yy in range(bp.VLINE_Y, bp.VLINE_Y + bp.VLINE_H)
                for xx in range(bp.VLINE_X, bp.VLINE_X + bp.VLINE_W))
        if spring_state(e) == (fill_px(vol) << bp.SPRING_Q, 0) and e.xram[bp.HR_F] == 0:
            return n, ok and split_of(e) == bp.VLINE_SPLIT[vol], worst
    return limit, False, worst


def page_at(vol, inp=2, theme=(0xFF, 0xFF)):
    """The idle volume page for vol (hn_volpage), amp on."""
    e = volpage_render(inp, vol, theme)
    e.iram[0x4F] = 1
    return e


def key(e, vol):
    """A volume step to vol through the key handler's tail (0x5936)."""
    e.iram[0x31] = vol
    e.setR(7, vol)
    e.call(0x5936)


def box_diff(e, want, before):
    """The first pixel that is not `want` inside the roll box (a row-major fb) or not `before` (a
    screen) outside it; None when all match."""
    x0, x1, y0, y1 = ROLL_BOX
    for xx in range(W):
        for yy in range(H):
            inside = x0 <= xx <= x1 and y0 <= yy <= y1
            w = want[yy][xx] if inside else before[xx][yy]
            if px(e, xx, yy) != w:
                return (xx, yy, "%04X" % px(e, xx, yy), "%04X" % w, "box" if inside else "outside")
    return None


def roll_run(e, old, new, frames=14, up=None):
    """Frames of the roll from `old` to `new` text, one hn_roll call each: after each, the box must be
    roll_box of the frame's number and nothing outside it may change. Returns (bad, worst ms)."""
    up = (int(new) >= int(old)) if up is None else up
    bad, worst = [], 0.0
    for n in range(1, frames + 1):
        before = screen(e)
        c0 = e.cycles
        e.call(LAB["hn_roll"])
        worst = max(worst, (e.cycles - c0) * 1000 / CLOCK_HZ)
        is_old, dy, ink = roll_frame(n, up)
        fb = [[None] * W for _ in range(H)]
        roll_box(fb, old if is_old else new, dy, ink)
        d = box_diff(e, fb, before)
        if d or e.xram[bp.HR_F] != (0 if n == 14 else n + 1):
            bad.append((old, new, n, d, e.xram[bp.HR_F]))
    return bad, worst


def test_roll():
    print("\nthe number roll (hn_roll, one frame per tick) against roll_frame / roll_box")
    frames = [roll_frame(n) for n in range(1, 15)]
    print("    frames (old?, rows, ink) for a step up: " + ", ".join("%d:%s%+d/%04X" % (n, "o" if o else "n", dy, ink)
                                                                for n, (o, dy, ink) in enumerate(frames, 1)))
    check("the build's frame table = the mock's formula (14 frames, the last the new number in white at 0)",
          [(o, dy, ink) for o, dy, ink in bp.ROLL] == frames and frames[-1] == (False, 0, bp.WHITE))
    check("the roll box %d..%d x %d..%d: below VOL's cell (ends %d), above the line (%d), holds the number (rows %d..%d)"
          % (ROLL_BOX + (bp.VLBL_Y + bp.PF_MONO.H - 1, bp.VLINE_Y, bp.VNUM_Y, bp.VNUM_Y + bp.PF_VNUM.H - 1)),
          bp.VLBL_Y + bp.PF_MONO.H <= bp.ROLL_Y0 <= bp.VNUM_Y and bp.VNUM_Y + bp.PF_VNUM.H - 1 <= bp.ROLL_Y1 < bp.VLINE_Y
          and 38 <= bp.ROLL_Y0 and bp.ROLL_Y1 <= 119)
    worst = 0.0
    for a_, b_ in ((25, 26), (26, 25), (9, 10), (10, 9), (60, 59), (59, 60), (0, 1), (1, 0), (5, 47), (47, 5)):
        e = page_at(a_)
        before = screen(e)
        key(e, b_)
        ok = (e.xram[bp.HR_F], e.xram[bp.HR_DIR]) == (1, 0 if b_ > a_ else 1) and \
            bytes(e.xram[bp.HR_OLD:bp.HR_OLD + 3]).split(b"\0")[0] == str(a_).encode()
        want = compose(vol_parts(e, a_))
        cap = vol_parts(e, b_)[bp.VF_CAP]
        for (xx, yy), c in cap.items():
            want[xx][yy] = c
        check("%2d -> %2d on the idle page: the dB caption at once, the number and the line untouched, roll armed "
              "(HR_F 1, HR_DIR %d, HR_OLD %r)" % (a_, b_, 0 if b_ > a_ else 1, str(a_)), ok and screen(e) == want)
        bad, w = roll_run(e, str(a_), str(b_))
        worst = max(worst, w)
        check("%2d -> %2d: 14 frames, each the box = roll_box (one number, shifted, clipped, dimmed, on black), "
              "nothing outside it; the last = the static page" % (a_, b_),
              not bad and vol_ok(e, b_, split=bp.VLINE_SPLIT[a_]), str(bad[:2]))
        e.call(LAB["hn_roll"])
        check("%2d -> %2d: then idle, nothing drawn" % (a_, b_), screen(e) == vol_model(e, b_, split=bp.VLINE_SPLIT[a_]))
    check("worst roll frame %.2f ms (at most %g)" % (worst, STEP_LIMIT), worst <= STEP_LIMIT)
    STEP_MS["roll_frame"] = worst
    # a key during a roll restarts it from the previous target
    e = page_at(25)
    key(e, 26)
    roll_run(e, "25", "26", frames=5)
    key(e, 27)
    ok = e.xram[bp.HR_F] == 1 and bytes(e.xram[bp.HR_OLD:bp.HR_OLD + 3]).split(b"\0")[0] == b"26"
    bad, _ = roll_run(e, "26", "27")
    check("26 during 25 -> 26 (frame 5), then 27: restarts with HR_OLD \"26\", 14 frames 26 -> 27", ok and not bad,
          str(bad[:2]))
    e = page_at(10)
    key(e, 9)
    roll_run(e, "10", "9", frames=2)
    key(e, 10)
    bad, _ = roll_run(e, "9", "10")
    check("10 -> 9 turned back to 10 at frame 2: 9 -> 10 upwards, no leftovers of the wider number", not bad,
          str(bad[:2]))
    e = page_at(40)
    key(e, 40)
    check("the same value again: no roll, only the caption", e.xram[bp.HR_F] == 0 and vol_ok(e, 40))
    # stops
    for name, act in (("ui_clear_screen", lambda e: e.call(bp.UI_CLEAR_SCREEN)),
                      ("hn_volpage (idle render)", lambda e: e.call(LAB["hn_volpage"])),
                      ("the exit's start (hn_clear, page 1)", lambda e: (e.iram.__setitem__(0x59, 1), e.call(LAB["hn_clear"])))):
        e = page_at(33)
        key(e, 34)
        roll_run(e, "33", "34", frames=4)
        act(e)
        stopped = e.xram[bp.HR_F] == 0
        before = screen(e)
        e.call(LAB["hn_roll"])
        if name.startswith("hn_volpage"):
            final = vol_ok(e, 34)
        elif name.startswith("the exit"):
            fb = [[None] * W for _ in range(H)]
            roll_box(fb, "34")
            final = all(px(e, xx, yy) == fb[yy][xx] for xx in range(bp.ROLL_X0, bp.ROLL_X1 + 1)
                        for yy in range(bp.ROLL_Y0, bp.ROLL_Y1 + 1)) and e.xram[bp.HN_MODE] == 2
        else:
            final = e.xram[bp.HN_VF] == 0
        check("a roll stopped by %s at frame 4: HR_F 0, %s; hn_roll then draws nothing" % (
              name, {"u": "screen cleared", "h": "the final number at once", "t": "the final number drawn first"}[name[0]]),
              stopped and final and screen(e) == before)
    # no roll during a wipe; bogus frame numbers (XDATA after power-up) stop
    e = page_at(20)
    e.xram[bp.HN_MODE] = 1
    key(e, 21)
    check("a key during a wipe with the number revealed: the final number and the caption at once, the line "
          "left to the spring, no roll", e.xram[bp.HR_F] == 0 and vol_ok(e, 21, split=bp.VLINE_SPLIT[20]),
          vol_diff(e, 21, split=bp.VLINE_SPLIT[20]))
    for f, mode, vf in ((15, 0, bp.VF_ALL), (200, 0, bp.VF_ALL), (3, 1, bp.VF_ALL), (3, 0, 0x7F)):
        e = page_at(20)
        before = screen(e)
        e.xram[bp.HR_F], e.xram[bp.HN_MODE], e.xram[bp.HN_VF] = f, mode, vf
        e.call(LAB["hn_roll"])
        check("hn_roll with HR_F %d, HN_MODE %d, HN_VF 0x%02X: stops, draws nothing" % (f, mode, vf),
              e.xram[bp.HR_F] == 0 and screen(e) == before)


def test_spring():
    print("\nthe line's spring: spring_model (the 8051 arithmetic) against the mock's float integrator, then hn_spring")
    check("constants from k 200, c 28, dt 10 ms: K1..K4 = %d %d %d %d" % (bp.SPRING_K1, bp.SPRING_K2, bp.SPRING_K3,
                                                                       bp.SPRING_K4), True)
    # every volume pair: within 2 px of the mock at every tick, ends exactly on the target, overshoot <= 1 px
    dev, over, longest, bad = 0.0, 0, 0, []

    def run(sched, x0):
        """sched: [(ticks, volume)]; the model and the mock side by side from volume x0."""
        nonlocal dev, over, longest
        p, v = fill_px(x0) << bp.SPRING_Q, 0
        fx, fv = x0 / 60, 0.0
        t = 0
        for i, (ticks, vol) in enumerate(sched):
            last = i == len(sched) - 1
            n = 0
            while n < ticks or (last and (p, v) != (fill_px(vol) << bp.SPRING_Q, 0)):
                p, v = spring_model(p, v, fill_px(vol))
                fx, fv = mock_spring(fx, fv, vol / 60)
                d = spring_split(p) - bp.VLINE_X
                dev = max(dev, abs(d - bp.VLINE_W * fx))
                if len(sched) == 1:
                    over = max(over, (d - fill_px(vol)) * (1 if vol >= x0 else -1))
                n += 1
                t += 1
                if n > 400:
                    return False
            longest = max(longest, n) if len(sched) == 1 else longest
        return spring_split(p) == bp.VLINE_SPLIT[sched[-1][1]]
    for a_ in range(61):
        for b_ in range(61):
            if not run([(0, b_)], a_):
                bad.append((a_, b_))
    mid = 0
    for a_ in range(0, 61, 5):
        for b_ in range(0, 61, 6):
            for c_ in (0, 17, 60):
                for t in (2, 9, 25):
                    mid += 1
                    if not run([(t, b_), (0, c_)], a_):
                        bad.append((a_, b_, t, c_))
    check("all 61 x 61 volume pairs and %d mid-flight target changes: every tick within %.2f px of the mock's "
          "float spring (at most 2), ends exactly on the target and stops" % (mid, dev), not bad and dev <= 2,
          str(bad[:3]))
    check("never more than 1 px past the target (%d px); settles in at most %d ticks" % (over, longest), over <= 1)
    # the 8051 against the model: hs_t6 for every volume, hs_mulx on random values
    import random
    rnd = random.Random(9)
    bad = []
    for vol in range(61):
        e = emu()
        e.xram[bp.HN_VOL] = vol
        e.call(LAB["hn_sp_t6"])
        if (e.R(4) << 8 | e.R(5)) != fill_px(vol) << bp.SPRING_Q:
            bad.append(vol)
    check("sp_t6: 64 * round(4.8 v) for every volume", not bad, str(bad[:4]))
    bad = []
    e = emu()
    for x in [0, 1, -1, 18432, -18432, 32767, -32767, 33, -33] + [rnd.randrange(-32767, 32768) for _ in range(300)]:
        for k in (bp.SPRING_K1, bp.SPRING_K2, bp.SPRING_K3, bp.SPRING_K4, 0xFFFF, 0x8000, 1):
            e.xram[0x0200], e.xram[0x0201] = (x >> 8) & 0xFF, x & 0xFF
            e.setR(4, k >> 8); e.setR(5, k & 0xFF)
            e.sfr[0x83], e.sfr[0x82] = 0x02, 0x00
            e.call(LAB["hn_sp_mulx"])
            if wrap16(e.R(2) << 8 | e.R(3)) != sp_mulq(x, k):
                bad.append((x, k))
    check("sp_mulx: 309 x 7 products, = x * k / 65536 rounded half away from 0", not bad, str(bad[:3]))
    bad = []
    for p in list(range(-200, 200)) + [18400, 18431, 18432, 18464, 20000, 32000, -32000]:
        e = emu()
        e.setR(2, (p >> 8) & 0xFF); e.setR(3, p & 0xFF)
        e.call(LAB["hn_sp_split"])
        if (e.R(6) << 8 | e.R(7)) != spring_split(p):
            bad.append(p)
    check("sp_split: 16 + round(p / 64), clamped to the line, for 407 positions", not bad, str(bad[:4]))
    # hn_spring on the idle page, tick by tick against the model, the line on screen with it
    worst = 0.0
    for a_, b_, c_, t in ((0, 60, None, 0), (60, 0, None, 0), (30, 31, None, 0), (31, 30, None, 0), (0, 1, None, 0),
                          (60, 59, None, 0), (0, 60, 20, 10), (50, 5, 45, 6), (12, 13, 11, 3)):
        e = page_at(a_)
        key(e, b_)
        while e.xram[bp.HR_F]:
            e.call(LAB["hn_roll"])            # the roll aside: this is the spring's test
        sp, sv = spring_state(e)
        ok, n, vol = sp == fill_px(a_) << bp.SPRING_Q and sv == 0, 0, b_
        while n < 200:
            if c_ is not None and n == t:
                key(e, c_)
                vol = c_
                while e.xram[bp.HR_F]:
                    e.call(LAB["hn_roll"])
            c0 = e.cycles
            e.call(LAB["hn_spring"])
            worst = max(worst, (e.cycles - c0) * 1000 / CLOCK_HZ)
            sp, sv = spring_model(sp, sv, fill_px(vol))
            n += 1
            ok = ok and spring_state(e) == (sp, sv) and split_of(e) == spring_split(sp)
            lm = [[None] * W for _ in range(H)]
            line_model(lm, spring_split(sp), bp.ORANGE)
            ok = ok and all(px(e, xx, yy) == lm[yy][xx] for yy in range(bp.VLINE_Y, bp.VLINE_Y + bp.VLINE_H)
                            for xx in range(bp.VLINE_X, bp.VLINE_X + bp.VLINE_W))
            if (sp, sv) == (fill_px(vol) << bp.SPRING_Q, 0):
                break
        ok = ok and vol_ok(e, vol)
        check("hn_spring %2d -> %2d%s: %3d ticks, each = spring_model, the line on screen at its split; ends on the "
              "static page" % (a_, b_, "" if c_ is None else " (-> %d after %d)" % (c_, t), n), ok)
    check("worst spring tick %.2f ms" % worst, worst <= STEP_LIMIT)
    STEP_MS["spring_tick"] = worst
    # during a wipe only right of the edge
    for mode, x in ((1, 100), (2, 200)):
        e = page_at(10)
        fill_screen(e, 0x1234)
        e.xram[bp.HN_MODE], e.xram[bp.HN_X], e.xram[bp.HN_X + 1] = mode, x >> 8, x & 0xFF
        e.xram[bp.HN_VOL] = 60
        sp, sv = spring_state(e)
        ok = True
        for _ in range(12):
            e.call(LAB["hn_spring"])
            sp, sv = spring_model(sp, sv, 0 if mode == 2 else fill_px(60))
            ok = ok and spring_state(e) == (sp, sv)
        drawn = {(xx, yy) for xx in range(W) for yy in range(H) if px(e, xx, yy) != 0x1234}
        want = {(xx, yy) for yy in range(bp.VLINE_Y, bp.VLINE_Y + bp.VLINE_H)
                for xx in range(max(x + 2, min(spring_split(sp), bp.VLINE_SPLIT[10])),
                                max(spring_split(sp), bp.VLINE_SPLIT[10]))}
        check("during the %s (edge at %d): the spring (%s) redraws only its columns right of x + 2"
              % ("entry" if mode == 1 else "exit", x, "towards 60" if mode == 1 else "towards 0"),
              ok and drawn == want, "(%d drawn, %d expected)" % (len(drawn), len(want)))
    # home: the spring is reset at the exit's end and by every cancel; the entry starts it from 0
    e = page_at(40)
    e.call(bp.UI_CLEAR_SCREEN)
    check("ui_clear_screen: spring at 0, still, split %d" % bp.VLINE_X, spring_state(e) == (0, 0) and split_of(e) == bp.VLINE_X)
    e = page_at(40)
    for k_ in range(bp.SP_P, bp.SP_P + 4):
        e.xram[k_] = 0x5A
    e.xram[bp.HN_VF] = 0
    e.call(LAB["hn_enter_vol"])
    check("hn_enter_vol from home: spring from 0 (whatever XDATA held)", spring_state(e) == (0, 0) and
          split_of(e) == bp.VLINE_X)
    e = page_at(40)
    before = screen(e)
    e.call(LAB["hn_spring"])
    check("hn_spring at rest: nothing drawn, nothing changed", screen(e) == before and
          spring_state(e) == (fill_px(40) << bp.SPRING_Q, 0))


def test_enter_vol():
    print("\nentry, exit, cancel and hold-back logic")
    for s in bp.VOL_ENTRY_SITES:
        e = emu()
        e.iram[0x47] = 1
        seen = []
        e.hooks[LAB["hn_enter_vol"]] = lambda em: seen.append(em.cycles)
        e.hooks[0x3A53] = lambda em: seen.append("caption")
        e.pc = s
        e.push(0x00); e.push(0x00)                 # a return address the run never reaches
        e.run(s + len(bp.VOL_ENTRY_ORIG), 2_000_000)
        check("site 0x%04X: hn_enter_vol called, stock caption skipped" % s,
              len(seen) == 1 and seen[0] != "caption" and e.pc == s + len(bp.VOL_ENTRY_ORIG))

    def st(mode=0, vf=0, step=0, x=0):
        e = emu(); fill_screen(e, 0x1234)
        e.xram[bp.HN_MODE], e.xram[bp.HN_VF], e.xram[bp.HN_STEP] = mode, vf, step
        e.xram[bp.HN_X], e.xram[bp.HN_X + 1] = x >> 8, x & 0xFF
        for k in range(25):
            e.xram[bp.SMALL_BUF + k] = 0x41
        e.iram[0x47] = 1
        return e

    def xv(e):
        return e.xram[bp.HN_X] << 8 | e.xram[bp.HN_X + 1]
    clears = []
    for label, page in (("hn_enter_vol", 2), ("hn_clear", 2)):
        e = st(); e.iram[0x59] = page; e.call(LAB[label])
        check("%s, idle: entry from x 318, buffers cleared, nothing drawn" % label,
              e.xram[bp.HN_MODE] == 1 and xv(e) == 318 and e.xram[bp.SMALL_BUF] == 0 and
              all(v == 0x1234 for v in e.lcd.gram))
        e = st(1, 3, 7, EASE[7]); e.iram[0x59] = page; e.call(LAB[label])
        check("%s, entry running: unchanged" % label, (e.xram[bp.HN_MODE], e.xram[bp.HN_STEP], xv(e)) == (1, 7, EASE[7]))
        e = st(2, 0, 7, 318 - EASE[7]); e.iram[0x59] = page; e.call(LAB[label])
        check("%s, exit at step 7: entry at step %d, same x" % (label, N - 7),
              (e.xram[bp.HN_MODE], e.xram[bp.HN_STEP], xv(e)) == (1, N - 7, 318 - EASE[7]) and EASE[N - 7] == 318 - EASE[7])
        e = st(0, bp.VF_ALL); e.iram[0x59] = page; e.call(LAB[label])
        check("%s, page on screen: nothing" % label, e.xram[bp.HN_MODE] == 0 and e.xram[bp.SMALL_BUF] == 0x41)
    for mode, vf, want in ((0, bp.VF_ALL, "exit"), (1, 0, "turn"), (2, 0, "stock"), (0, 0, "stock"), (0, 3, "stock")):
        e = st(mode, vf, 7, EASE[7] if mode == 1 else 318 - EASE[7])
        e.iram[0x59] = 1
        seen = []
        e.hooks[0x51EE] = lambda em: seen.append("clear")
        e.call(LAB["hn_clear"])
        if want == "exit":
            ok = e.xram[bp.HN_MODE] == 2 and xv(e) == 0 and e.xram[bp.HN_STEP] == 0 and not seen
        elif want == "turn":
            ok = e.xram[bp.HN_MODE] == 2 and e.xram[bp.HN_STEP] == N - 7 and xv(e) == EASE[7] and not seen
        else:
            ok = e.xram[bp.HN_MODE] == 0 and e.xram[bp.HN_VF] == 0 and seen == ["clear"]
        check("hn_clear page 1, mode %d, HN_VF %2d: %s" % (mode, vf, {"exit": "exit from x 0, no clear",
              "turn": "entry turned round at its x", "stock": "cancel + stock clear"}[want]), ok)
    e = st(1, 5, 4, EASE[4]); e.iram[0x59] = 3
    seen = []
    e.hooks[0x51EE] = lambda em: seen.append("clear")
    e.call(LAB["hn_clear"])
    check("hn_clear page 3 during a wipe: cancel + stock clear", e.xram[bp.HN_MODE] == 0 and seen == ["clear"])
    for mode in (1, 2):
        e = st(mode, 7, 4, 100)
        e.xram[bp.HN_HF] = 9
        e.call(bp.UI_CLEAR_SCREEN)
        check("ui_clear_screen during a wipe (mode %d): cancelled (mode, HN_VF, HN_HF 0), screen black, "
              "buffers cleared" % mode, (e.xram[bp.HN_MODE], e.xram[bp.HN_VF], e.xram[bp.HN_HF]) == (0, 0, 0) and
              not any(e.lcd.gram[0x23:0x23 + 170]) and e.xram[bp.SMALL_BUF] == 0)
    # hn_hold: the periodic refresh's home_refresh call at 0x4081
    for mode in (0, 1, 2):
        e = st(mode)
        e.xram[bp.HN_SBUF] = 0
        seen = []
        e.hooks[bp.HOME_REFRESH] = lambda em: (seen.append("refresh"), em.ret())
        e.hooks[0x3A53] = lambda em: (seen.append("status"), em.ret())
        e.pc = 0x4081
        e.push(0xF0); e.push(0xFF)            # 0x3FE3's return address: the SENTINEL
        e.run(0xFFF0, 2_000_000)
        if mode == 0:
            ok = seen == ["refresh", "status"]
        else:
            ok = seen == [] and e.xram[bp.HN_SBUF] == 1
        check("0x4081, mode %d: %s" % (mode, "home_refresh and the status line as stock" if mode == 0 else
                                       "held back, returns, HN_SBUF set"), ok, str(seen))
    # hn_signal: the status loader's signal check keeps its result in HN_SIG, C as the check left it
    for sig in (0, 1):
        e = st(); e.iram[0x47] = 2
        e.pins[0xC0] = (0x04, 0 if sig else 0x04)         # optical: P4.2 low = lock
        e.xram[bp.HN_SIG] = 1 - sig
        e.call(LAB["hn_signal"])
        check("hn_signal (0x4016), optical, P4.2 %d: C = %d, HN_SIG %d" % (1 - sig, sig, sig),
              e.C == sig and e.xram[bp.HN_SIG] == sig)
    # hn_stat_load: the loader runs to 0x4081, where hn_hold returns instead of drawing
    for inp, text in ((2, "No signal"), (6, "Analog input")):
        e = st(); e.iram[0x47] = inp
        e.pins[0xC0] = (0x04, 0x04)
        seen = []
        e.hooks[bp.HOME_REFRESH] = lambda em: (seen.append("refresh"), em.ret())
        e.hooks[0x3A53] = lambda em: (seen.append("status"), em.ret())
        e.call(LAB["hn_stat_load"])
        check("hn_stat_load, input %d: XDATA 0x50 = %r, HN_SIG 0, nothing drawn, HN_SLD clear" % (inp, text),
              buffer_text(e, bp.SMALL_BUF) == text and e.xram[bp.HN_SIG] == 0 and seen == [] and
              e.xram[bp.HN_SLD] == 0 and all(v == 0x1234 for v in e.lcd.gram), str(seen))
    # hn_name_guard: home_draw_input_name during an exit: the whole home first (black, home_refresh, which
    # draws the name too, the status line), then the stock name draw
    for mode in (0, 1, 2):
        e = st(mode)
        e.iram[0x45] = 1
        seen = []
        e.hooks[0x51EE] = lambda em: seen.append("clear")
        e.hooks[0x298B] = lambda em: seen.append("name")
        e.hooks[bp.HOME_REFRESH] = lambda em: seen.append("home_refresh")
        e.hooks[0x3A53] = lambda em: seen.append("status")
        e.call(0x4A85)
        want = ["clear", "home_refresh", "name", "status", "name"] if mode == 2 else ["name"]
        check("home_draw_input_name, mode %d: %s" % (mode, "wipe stopped, the whole home, then the name"
                                                     if mode == 2 else "the name as stock"),
              seen == want and e.xram[bp.HN_MODE] == (0 if mode == 2 else mode) and
              e.xram[bp.SMALL_BUF] == 0x41, str(seen))
    # hn_flag_path: home_refresh_periodic's flag path during a wipe skips the 0x412F fill
    for mode in (0, 2):
        e = st(mode)
        e.iram[0x45], e.iram[0x21], e.iram[0x20] = 1, 0x0A, 0x40
        seen = []
        e.hooks[0x412F] = lambda em: (seen.append("fill"), em.ret())
        e.hooks[0x4016] = lambda em: (seen.append("status"), em.ret())
        e.pc = 0x3FF8
        e.push(0xF0); e.push(0xFF)
        e.run(0xFFF0, 2_000_000)
        check("flag path 0x3FF8, mode %d: flags cleared, page 1, %s" % (mode, "fill skipped" if mode else "fill as stock"),
              seen == (["status"] if mode else ["fill", "status"]) and not e.iram[0x21] & 0x0A and
              not e.iram[0x20] & 0x40 and e.iram[0x45] == 1, str(seen))
    # uk_tasks: a step only after a tick, and only with the amp on; the re-mute request as main_tick_tasks
    for tick, power, mode, want in ((0, 1, 1, False), (1, 1, 1, True), (1, 0, 1, False), (1, 2, 1, False), (1, 1, 0, False)):
        e = st(mode, 0, 3, EASE[3])
        e.iram[0x4F] = power
        e.iram[0x20] = 0x80 if tick else 0
        e.iram[0x45] = 5                      # a page without a renderer: main_tick_tasks draws nothing
        seen = []
        e.hooks[0x3335] = lambda em: seen.append(em.xram[bp.HN_STEP])
        e.call(LAB["uk_tasks"])
        check("uk_tasks: tick %d, 0x4F %d, mode %d -> %s" % (tick, power, mode,
              "the tick (0x3335), then one step" if want else "the tick only" if tick else "nothing"),
              seen == ([3] if tick else []) and e.xram[bp.HN_STEP] == (4 if want else 3))
    bad = []
    for tick in (0, 1):
        for remute in (0, 1):
            got = []
            for img, entry in ((BASE, 0x3325), (NEW, LAB["uk_tasks"])):
                e = emu(img=img)
                e.iram[0x4F], e.iram[0x45] = 0, 5
                e.iram[0x20] = 0x80 if tick else 0
                e.iram[0x21], e.iram[0x22] = (0x10 if remute else 0) | 0x01, 0x10 | 0x01
                calls = []
                e.hooks[0x58D3] = lambda em, calls=calls: calls.append("volume_apply")
                e.hooks[0x3335] = lambda em, calls=calls: calls.append("tick")
                e.call(entry)
                got.append((calls, e.iram[0x20], e.iram[0x21], e.iram[0x22]))
            if got[0] != got[1]:
                bad.append((tick, remute, got))
    check("uk_tasks against main_tick_tasks: re-mute request 0x21.4 (volume_apply) and the tick in the same order, "
          "same flags", not bad, str(bad[:2]))
    # the race hn8 had: a tick that comes while the re-mute request runs is stepped, not consumed without a step
    e = st(1, 0, 3, EASE[3])
    e.iram[0x4F], e.iram[0x45], e.iram[0x20], e.iram[0x21] = 1, 5, 0, 0x10
    e.hooks[0x58D3] = lambda em: em.iram.__setitem__(0x20, em.iram[0x20] | 0x80)
    e.call(LAB["uk_tasks"])
    check("uk_tasks: a tick set during the re-mute request's volume_apply: handled with its step",
          e.xram[bp.HN_STEP] == 4 and not e.iram[0x20] & 0x80)
    e = st(7, 0, 3, 50)
    e.call(LAB["hn_step"])
    check("hn_step with a mode that is not one (XDATA after power-up): stops, draws nothing",
          e.xram[bp.HN_MODE] == 0 and all(v == 0x1234 for v in e.lcd.gram))


def test_home_tail():
    print("\nhn_home_tail (home_refresh's tail, 0x5C99)")
    for theme in ((0xFF, 0xFF), (0x07, 0xE0)):
        e = emu(theme); home_state(e, vol=37)
        e.setR(7, 37)
        e.call(LAB["hn_home_tail"])
        parts = home_parts(e)
        want = dict(parts[bp.HF_VOL]); want.update(parts[bp.HF_BAR])
        ok = all(px(e, x, y) == want.get((x, y), 0) for x in range(W) for y in range(H))
        check("theme %02X%02X: the volume (hm_volume), accent bar %dx%d at %d,%d, nothing else" % (theme + (bp.BAR_W, bp.BAR_H, bp.BAR_X, bp.BAR_Y)),
              ok)
        check("theme %02X%02X: theme colour untouched" % theme, (e.iram[0x48], e.iram[0x49]) == theme)


def text_render(img, page, entry, buf, text, y):
    e = emu(img=img)
    e.iram[0x45] = page
    for k, ch in enumerate(text.encode() + b"\0"):
        e.xram[buf + k] = ch
    e.setR(6, 0); e.setR(7, y)
    e.call(entry)
    return e


def test_align():
    print("\npage-1 text (hooks 0x2A25 big, 0x3A82 small): ours at the name / status y, else x 16")
    cases = (("big", 0x298B, 0x35, "USB", 40, 32, 30), ("small", 0x3A53, 0x50, "No signal", 100, 24, 14))
    for kind, entry, buf, text, y, h, cw in cases:
        n1, b1 = text_render(NEW, 1, entry, buf, text, y), text_render(BASE, 1, entry, buf, text, y)
        n3, b3 = text_render(NEW, 3, entry, buf, text, y), text_render(BASE, 3, entry, buf, text, y)
        tw = len(text) * cw
        shift = (W - tw) // 2 - 16
        moved = all(px(n1, x, yy) == px(b1, x + shift, yy) for x in range(16, 16 + tw) for yy in range(y, y + h))
        check("%s at another y on page 1: moved to x 16, stock glyphs" % kind, moved and ink_in(n1, 16, y, tw, h))
        check("%s at another y on page 1: margins left and right cleared" % kind,
              not ink_in(n1, 0, y, 16, h) and not ink_in(n1, 16 + tw, y, W - 16 - tw, h))
        check("%s on page 3 (menus): unchanged, centred" % kind, n3.lcd.gram == b3.lcd.gram)
    for kind, entry, buf, text, y in (("big", 0x298B, 0x35, "COAXIAL", bp.NAME_Y),
                                      ("small", 0x3A53, 0x50, "No signal", bp.STATUS_Y)):
        n3, b3 = text_render(NEW, 3, entry, buf, text, y), text_render(BASE, 3, entry, buf, text, y)
        check("%s at the home y %d on page 3: unchanged" % (kind, y), n3.lcd.gram == b3.lcd.gram)
    wide = "ABCDEFGHIJKLMNOPQRSTU"                    # 21 x 14 = 294 px: stays centred
    check("small text wider than 288 px stays centred on page 1",
          text_render(NEW, 1, 0x3A53, 0x50, wide, 100).lcd.gram ==
          text_render(BASE, 1, 0x3A53, 0x50, wide, 100).lcd.gram)


# ---- whole firmware ----------------------------------------------------------------------------
NEC_HDMI = 0x14                          # direct-select input 5
NEC_MENU_OPEN = 0x04                     # opens the menu from home (key_menu_nav @ 0x10FC, key code 0x0F
                                          # via the IR table); NEC_MENU (0x03, key code 0x5D) reaches
                                          # key_menu @ 0x144E, which is a no-op unless page is already >= 3
NEC_USB, NEC_OPTICAL, NEC_BT = 0x10, 0x11, 0x13   # direct-select inputs 1, 2, 4 (NEC_HDMI: 5)
UNMUTE_CALL = 0x33FB                     # mute_timer_expired: mov R7,#1 ; lcall mute_state_set
DAC_RECONFIG = 0x46A0                    # format_poll: the format differs from 0x4E -> DAC setup
CHUNK = 0.01                             # lockstep granularity, one Timer0 tick
TOUR = [                                 # (step, NEC command or None, seconds, screen check)
    ("power_on", NEC_POWER, 8.0, "home"),
    ("vol_up", NEC_VOL_UP, 0.8, "vol"),     # the entry, then the line's spring settles
    ("vol_up2", NEC_VOL_UP, 0.5, "vol"),
    ("back_home", None, 2.5, "home"),
    ("source", NEC_SOURCE, 11.0, "home"),   # OPTICAL has no signal: ~10 s detect timeout
    ("menu", NEC_MENU_OPEN, 1.5, "same"),   # opens the menu (page -> 3), screen identical to fast-lcd
    ("menu_down", NEC_DOWN, 1.0, "same"),   # navigates the cursor down inside the menu (RAM 0x17)
    ("menu_timeout", None, 9.5, "home"),    # ~9 s of inactivity in the menu returns home
    ("hdmi", NEC_HDMI, 3.0, "home"),
    ("vol_down", NEC_VOL_DOWN, 0.8, "vol"),
    ("vol_timeout", None, 2.5, "home"),
    ("standby", NEC_POWER, 3.0, "same"),
]
VOL_ENTRY_STEPS = ("vol_up", "vol_down")  # Vol keys pressed on the home page: they open page 2
EXIT_STEPS = ("back_home", "vol_timeout")


def state(amp):
    return (amp.page, amp.powered) + tuple(amp.e.iram[a] for a in (0x31, 0x52, 0x47, 0x2B))


def accent_of(amp):
    hi, lo = amp.e.iram[0x48], amp.e.iram[0x49]
    return bp.ORANGE if (hi, lo) == (0xFF, 0xFF) else (hi << 8) | lo


def volpage_reference(amp):
    """The volume page for this amp's state: vol_model on its RAM and status buffer."""
    return vol_model(amp.e)


def home_checks(step, new, ref):
    check("%-12s home screen = home_model for the amp's state" % step, home_ok(new.e), home_diff(new.e))


def draw_time(activity, quiet=10):
    for i in range(len(activity)):
        if not any(activity[i:i + quiet]):
            return i * CHUNK
    return len(activity) * CHUNK


def countdown(e):
    """The unmute countdown, RAM 0x43:0x44 (main-loop ticks of 10 ms)."""
    return (e.iram[0x43] << 8) | e.iram[0x44]


class Watch:
    """Logs every wipe step (start clock, mode, step, x after, duration), every tick that animates
    (a wipe step, a roll frame or a moving spring: start clock, mode, roll frame, Timer0 tick, split
    after, duration: from hn_step's entry to uk_tasks' return) and uk_fill calls."""

    def __init__(self, amp):
        self.amp = amp
        self.steps, self.ticks, self.fills, self._open = [], [], [], None
        self.on_step = None                  # fn(step record) after each step
        self.on_tick = None                  # fn(tick record) after each animated tick
        e = amp.e
        e.hooks[LAB["hn_step"]] = self._start
        e.hooks[LAB["uk_fill"]] = lambda em: self.fills.append(
            (em.cycles, (em.R(2) << 8) | em.R(3), em.R(1), (em.R(6) << 8) | em.R(7)))

    def _start(self, em):
        mode, rf = em.xram[bp.HN_MODE], em.xram[bp.HR_F]
        anim = mode or rf or em.xram[bp.SP_V] or em.xram[bp.SP_V + 1] or \
            (mode == 0 and em.xram[bp.HN_VF] == bp.VF_ALL and spring_state(em)[0] != fill_px(min(em.xram[bp.HN_VOL], 60)) << bp.SPRING_Q)
        self._open = (em.cycles, mode, rf) if anim else None
        if anim:                             # STEP_END runs on every main pass: hook it only now
            em.hooks[STEP_END] = self._end

    def _end(self, em):
        em.hooks.pop(STEP_END, None)
        if self._open:
            c0, mode, rf = self._open
            ms = (em.cycles - c0) * 1000 / CLOCK_HZ
            self._open = None
            self.ticks.append((c0, mode, rf, self.amp.ticks, split_of(em), ms))
            if self.on_tick:
                self.on_tick(self.ticks[-1])
            if mode:
                x = em.xram[bp.HN_X] << 8 | em.xram[bp.HN_X + 1]
                self.steps.append((c0, mode, em.xram[bp.HN_STEP], x, ms))
                if self.on_step:
                    self.on_step(self.steps[-1])

    def mark(self):
        return len(self.steps), len(self.amp.events), len(self.fills)

    def since(self, mark):
        return self.steps[mark[0]:]

    def worst(self):
        """The longest animated tick (wipe step, roll frame, spring), from hn_step's entry to the end."""
        return max((t[5] for t in self.ticks), default=0.0)


def wipe_checks(label, w, mark, mode, n=N):
    """The steps since mark: n of them, all in this mode, x from the ease table."""
    st = [s for s in w.since(mark)]
    xs = [s[3] for s in st]
    want = [EASE[k] if mode == 1 else 318 - EASE[k] for k in range(N + 1 - n, N + 1)]
    check("%s%s: %d steps, x as the ease table" % (label, "entry" if mode == 1 else "exit", n),
          [s[1] for s in st] == [mode] * n and xs == want, "(%d steps, x %s)" % (len(st), xs[:3]))
    return st


def vol_entry_checks(step, new, w, mark):
    """A volume-key entry from home: N steps, and the NJW1194 volume write before the first."""
    st = wipe_checks("%-12s " % step, w, mark, 1)
    vol_writes = [c for c, nm, d in new.events[mark[1]:] if nm == "njw1194_write" and "R7=10" in d]
    first = st[0][0] if st else None
    check("%-12s NJW1194 volume write before the first step" % step,
          bool(vol_writes) and first is not None and vol_writes[0] < first,
          "(write %.1f ms before)" % ((first - vol_writes[0]) * 1000 / CLOCK_HZ) if vol_writes and first else "")
    fl = [f for f in w.fills[mark[2]:]]
    check("%-12s nothing drawn between the press and the first step" % step,
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
    """Every audio state fast-lcd went through, in the same order, none more than 0.10 s later.
    A run ends at the same clock in both images, so a state fast-lcd reaches in the last 0.10 s may
    still be to come here: the states up to 0.10 s before the end must match one for one, and the
    rest must continue the same sequence as far as each image got."""
    tr_ref, tr_new = audio_transitions(ref), audio_transitions(new)
    cut = min(ref.t, new.t) - 0.10
    sr, sn = [s for _, s in tr_ref], [s for _, s in tr_new]
    n_ref = len([1 for t, _ in tr_ref if t <= cut])
    n_new = len([1 for t, _ in tr_new if t <= cut])
    k = min(len(sr), len(sn))
    same_order = sr[:k] == sn[:k] and n_ref <= len(sn) and n_new <= len(sr)
    check("%ssame sequence of audio states, in the same order" % label, same_order,
          "(%d vs %d states)" % (len(tr_ref), len(tr_new)))
    if same_order:
        tr_ref, tr_new = tr_ref[:k], tr_new[:k]
        late = [(tn - tr, tr) for (tr, _), (tn, _) in zip(tr_ref, tr_new) if tn - tr > 0.10]
        check("%sno audio state more than 0.10 s later than fast-lcd" % label, not late,
              "" if not late else "(%d, first %+.2f s at %.2f s)" % (len(late), late[0][0], late[0][1]))
        moved = [(tr, tn - tr) for (tr, _), (tn, _) in zip(tr_ref, tr_new) if abs(tn - tr) > 0.05]
        for tr, d in moved:
            if not quiet:
                print("    %saudio state at %7.2f s moves %+.2f s" % (label, tr, d))
    bl = [[d for _, nm, d in amp.events if nm == BACKLIGHT[1]] for amp in (ref, new)]
    check("%sbacklight switches the same way" % label, bl[0] == bl[1])


def mid_entry_ok(new, before, k):
    """The screen right after entry step k: the old screen left of the edge, the edge, and right of
    it the volume page with the elements the edge has passed (the line in parts). Returns the first
    wrong pixel, or None."""
    x = EASE[k]
    # the line right of the edge at the split on screen (HN_SPL: the unit tests hold it to spring_model)
    want = entry_screen(vol_parts(new.e, split=split_of(new.e)), before, x, k == N, accent_of(new))
    s = screen(new.e)
    for xx in range(W):
        for yy in range(H):
            if s[xx][yy] != want[xx][yy]:
                return (xx, yy, hex(s[xx][yy]), hex(want[xx][yy]))
    return None


def tour():
    print("\nWhole firmware, lockstep with fast-lcd")
    amps = [Amp(BASE), Amp(NEW)]
    for amp in amps:
        amp.set_pin(0xC0, 5, 0)                         # USB audio present
        amp.boot()
    ref, new = amps
    w = Watch(new)
    # stack: seed the idata above SP with a canary, in both images
    sp0 = [a.e.sfr[0x81] for a in amps]
    for a, s in zip(amps, sp0):
        for i in range(s + 1, 0x100):
            a.e.iram[i] = 0xA5
    for step, cmd, secs, kind in TOUR:
        w0 = time.time()
        mark = w.mark()
        before = screen(new.e)
        for amp in amps:
            if cmd is not None:
                amp.press(cmd)
        act, home_at = [[], []], [None, None]
        c_start = new.e.cycles
        mid = []

        exit_end = []

        def at_step(rec, before=before, mid=mid, step=step):
            if rec[1] == 1 and rec[2] == 10 and not mid:
                mid.append(mid_entry_ok(new, before, 10) or True)
                new.lcd.save_png(os.path.join(HERE, "build", "tour_%s_mid.png" % step))
            if rec[1] == 2 and rec[2] == N:
                exit_end.append((new.e.cycles, screen(new.e)))
        w.on_step = at_step
        refreshes = []
        new.e.hooks[bp.HOME_REFRESH] = lambda em: refreshes.append(em.cycles)
        for n in range(int(round(secs / CHUNK))):
            for k, amp in enumerate(amps):
                p0, n0 = amp.lcd.pixels, len(amp.lcd.log)
                amp.wait(CHUNK)
                act[k].append(amp.lcd.pixels != p0 or len(amp.lcd.log) != n0)
                if home_at[k] is None and amp.page == 1:
                    home_at[k] = n * CHUNK
        print("    %-12s %5.1f s emulated x2 in %5.1f s, drawing %4.0f / %4.0f ms" %
              (step, secs, time.time() - w0, draw_time(act[0]) * 1000, draw_time(act[1]) * 1000), flush=True)
        check("%-12s same page, power, volumes, input, output" % step, state(ref) == state(new),
              "%s vs %s" % (state(ref), state(new)))
        if kind == "home":
            home_checks(step, new, ref)
        elif kind == "vol":
            check("%-12s volume page = vol_model for the amp's state" % step,
                  new.page == 2 and screen(new.e) == volpage_reference(new), vol_diff(new.e))
        else:
            check("%-12s screen identical to fast-lcd" % step, new.lcd.gram == ref.lcd.gram)
        if step in ("menu", "menu_down"):
            check("%-12s really in the menu (page >= 3)" % step, new.page >= 3, "(page %d)" % new.page)
        if step in VOL_ENTRY_STEPS:
            vol_entry_checks(step, new, w, mark)
            check("%-12s mid-wipe (step 10): old page left of the edge, volume page right of it" % step,
                  mid == [True], str(mid))
        if step == "vol_up2":
            check("%-12s a second key on the page: no wipe" % step, not w.since(mark))
        if step in EXIT_STEPS:
            st = wipe_checks("%-12s " % step, w, mark, 2)
            if st and exit_end:
                t_end = exit_end[0][0]
                during = [c for c in refreshes if st[0][0] <= c <= t_end]
                after = [c for c in refreshes if c > t_end]
                check("%-12s no stock home refresh during the exit; it resumes %.2f s after it" %
                      (step, (after[0] - t_end) / CLOCK_HZ if after else -1),
                      not during and bool(after) and (after[0] - t_end) / CLOCK_HZ <= 0.6)
                check("%-12s the screen the exit leaves = what the stock refresh draws over it" % step,
                      exit_end[0][1] == screen(new.e))
            both = None not in home_at
            check("%-12s home (page 1) within 0.05 s of fast-lcd" % step,
                  both and abs(home_at[1] - home_at[0]) <= 0.05, str(home_at))
            if both and exit_end:
                # the page switches as on fast-lcd; the home is whole when the exit ends, N ticks later
                # (fast-lcd draws its home at its first refresh, 10 ticks after the switch)
                done = (exit_end[0][0] - c_start) / CLOCK_HZ - home_at[1]
                check("%-12s the home screen whole %.2f s after the switch to page 1 (the %d-tick exit)"
                      % (step, done, N), N * 0.01 - 0.01 <= done <= N * 0.01 + 0.03)
        if step in ("source", "menu", "hdmi", "standby", "menu_timeout", "power_on"):
            check("%-12s no wipe" % step, not w.since(mark))
        new.lcd.save_png(os.path.join(HERE, "build", "tour_%s.png" % step))

    print("\n  Audio state, after every write that changes it")
    audio_checks("", ref, new)

    def semantic_args(name, regs):
        """The part of a writer's logged R3/R4/R5/R7 that reaches the chip, per
        ao300.STATE_KEY's own field selection: R3/R4 double as scratch/loop-counter
        registers at some call sites and can differ, by one incidental value, from a
        harmless timing shift without changing what the chip is told."""
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
        top = max((i for i in range(s + 1, 0x100) if a.e.iram[i] != 0xA5), default=s)
        peak.append(top)
    print("    stack: main-loop SP 0x%02X; deepest idata used 0x%02X on fast-lcd, 0x%02X here" %
          (sp0[1], peak[0], peak[1]))
    # stock's own peak: the delay leaves (0x0006, 0x0016) at SP 0xA0 with timer3_isr on top,
    # which pushes 4 bytes more than the Timer0 ISR (0xAF while Amp ran Timer0 only)
    check("stack: deepest idata used in the tour at most 0xB3 (canary)", peak[1] <= 0xB3, "(0x%02X)" % peak[1])
    STEP_MS["tour"] = w.worst()
    print("    worst wipe step in the tour: %.2f ms" % w.worst())


def headphone_unplugged(amp):
    amp.e.iram[0x2B] = 2                 # headphone output
    amp.set_pin(0xA0, 6, 0)              # P2.6 low: Timer0 holds the countdown at 300 (0x3EE9)


# (name, what it shows, setup [(NEC command, callable or None, then wait s)], countdown, seconds from the
# Vol+ press to the screen check, page then). Countdown "held": re-armed by the firmware, never expires
# (no unmute in either image); "runs": counts down to an unmute during the scenario. In "splash"
# post_power_on runs right after the key (its clear cancels the wipe) and returns home, in both images.
SCENARIOS = [
    ("bt", "Bluetooth, no stream: 0x583F holds the countdown at 40..50",
     [(NEC_POWER, None, 9.0), (NEC_BT, None, 4.0)], "held", 1.0, 2),
    ("optical", "Optical without signal: Timer0 holds the countdown at 100",
     [(NEC_POWER, None, 9.0), (NEC_OPTICAL, None, 4.0)], "held", 1.0, 2),
    ("headphone", "headphone output, P2.6 low: Timer0 holds the countdown at 300",
     [(NEC_POWER, None, 9.0), (None, headphone_unplugged, 1.0)], "held", 1.0, 2),
    ("power_on", "USB, Vol+ during the countdown after power-on",
     [(NEC_POWER, None, 7.4)], "runs", 1.0, 2),
    ("hdmi_switch", "Vol+ 0.5 s after switching to HDMI",
     [(NEC_POWER, None, 9.0), (NEC_HDMI, None, 0.5)], "runs", 1.0, 2),
    ("switch_now", "Vol+ 0.05 s after switching to USB from HDMI",
     [(NEC_POWER, None, 9.0), (NEC_HDMI, None, 3.0), (NEC_USB, None, 0.05)], "runs", 1.0, 2),
    ("unmute_due", "USB, Vol+ when the unmute is due within the wipe",
     [(NEC_POWER, None, 8.15)], "runs", 1.0, 2),
    ("splash", "Vol+ during the power-on logo, dispatched just before post_power_on",
     [(NEC_POWER, None, 2.5)], "runs", 4.0, 1),      # the key waits for the logo (~2.5 s)
]


def screen_ok(base, new):
    """Whether new's screen is what we expect, given where both amps ended up: home_model for
    new's state (both page 1, both powered), vol_model (both page 2, both powered),
    or bit-identical to base otherwise."""
    if base.powered and new.powered:
        if new.page == 1 and base.page == 1:
            return home_ok(new.e)
        if new.page == 2 and base.page == 2:
            return screen(new.e) == volpage_reference(new)
    return new.lcd.gram == base.lcd.gram


def input_scenarios():
    print("\nVolume key after each input settles, whole firmware, against fast-lcd")
    for name, what, setup, cd_kind, settle, page in SCENARIOS:
        w0 = time.time()
        print("  %s: %s" % (name, what))
        amps = [Amp(BASE), Amp(NEW)]
        ref, new = amps
        w = Watch(new)
        unmutes = [[], []]
        for k, amp in enumerate(amps):
            amp.e.hooks[UNMUTE_CALL] = lambda em, k=k: unmutes[k].append(em.cycles / CLOCK_HZ)
            amp.set_pin(0xC0, 5, 0)                     # USB audio present
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
            check("%swipe started, then cancelled by post_power_on's clear (%d steps)" % (label, len(st)),
                  new.e.xram[bp.HN_MODE] == 0 and len(st) < N)
        else:
            vol_entry_checks(name, new, w, mark)
            print("    %s unmute countdown at the press: %d" % (label, cd_press))
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new),
              "%s vs %s" % (state(ref), state(new)))
        check("%spage %d, screen as expected (volume: vol_model; home: home_model)" %
              (label, page), new.page == page and screen_ok(ref, new))
        new.lcd.save_png(os.path.join(HERE, "build", "inputs_%s.png" % name))
        for amp in amps:
            amp.wait(2.5)
        if name != "splash":
            wipe_checks(label, w, (mark[0] + N,) + mark[1:], 2)
            check("%sback home after the exit: home_model" % label,
                  new.page == 1 and screen_ok(ref, new))
        if cd_kind == "runs":
            for amp in amps:
                amp.wait(3.0)                           # the splash case unmutes 5.85 s after the press
        after = [u[b:] for u, b in zip(unmutes, before)]
        if cd_kind == "held":
            check("%scountdown held: no unmute in either image, still running at the end" % label,
                  after == [[], []] and countdown(ref.e) > 0 and countdown(new.e) > 0,
                  "(%s, %d / %d)" % (after, countdown(ref.e), countdown(new.e)))
        else:
            ok = len(after[0]) == 1 and len(after[1]) == 1
            shift = after[1][0] - after[0][0] if ok else None
            check("%sunmute %s after the press, no later than fast-lcd + 0.10 s" %
                  (label, "%.2f s" % (after[1][0] - t_press) if ok else "?"),
                  ok and shift <= 0.10, "(%s)" % ("%+.3f s" % shift if ok else after))
        audio_checks(label, ref, new)
        STEP_MS["input_" + name] = w.worst()
        print("    %s: %.1f s, worst step %.2f ms" % (name, time.time() - w0, w.worst()), flush=True)


def stock_home_now(amp):
    """The home screen the stock refresh would draw for amp's state right now (lcd_clear_black,
    home_refresh, the status line from XDATA 0x50), drawn in a copy of its RAM and XDATA."""
    e = ut.Emu8051(NEW)
    e.iram[:] = amp.e.iram
    e.sfr[:] = amp.e.sfr
    e.xram[:] = amp.e.xram
    for k, v in amp.e.pins.items():
        e.pins[k] = v
    e.xram[bp.HN_MODE] = 0
    e.iram[0x45] = 1
    e.call(0x51EE)
    refresh_draw(e)
    return screen(e)


def set_flag_213(amp):
    amp.e.iram[0x21] |= 0x08             # 0x21.3, as key_59 (0x0F8D) leaves it


# keys during a wipe: (name, keys before the Vol+ [(NEC, seconds)], when: "entry" / "exit", seconds into
# that wipe, key, then wait, expectation, callable run on both amps just before the key)
KEY_SCENARIOS = [
    ("vol_in_entry", [], "entry", 0.08, NEC_VOL_UP, 1.0, "vol", None),
    ("vol_in_exit", [], "exit", 0.10, NEC_VOL_UP, 1.0, "vol", None),
    ("voldown_in_exit", [], "exit", 0.03, NEC_VOL_DOWN, 1.0, "vol", None),
    ("menu_in_entry", [], "entry", 0.10, NEC_MENU_OPEN, 1.5, "home", None),   # page 2: read_key makes it "home"
    ("menu_in_exit", [], "exit", 0.10, NEC_MENU_OPEN, 1.5, "same", None),
    ("source_in_entry", [], "entry", 0.10, NEC_SOURCE, 1.0, "home", None),
    ("source_in_exit", [], "exit", 0.10, NEC_SOURCE, 1.0, "source", None),
    ("source_late_exit", [], "exit", 0.28, NEC_SOURCE, 1.0, "source", None),   # the exit's slow tail
    ("vol_early_exit", [], "exit", 0.0, NEC_VOL_UP, 1.0, "vol", None),     # before the edge first moves
    ("vol_late_entry", [], "entry", 0.30, NEC_VOL_UP, 1.0, "vol", None),   # the entry's still tail
    ("power_in_entry", [], "entry", 0.10, NEC_POWER, 3.0, "same", None),
    ("power_in_exit", [], "exit", 0.12, NEC_POWER, 3.0, "same", None),
    ("select_in_entry", [], "entry", 0.10, NEC_HDMI, 1.0, "home", None),      # the same
    ("select_in_exit", [], "exit", 0.10, NEC_HDMI, 1.0, "source", None),
    # review repros: key_bt_function (IR 0x0E) calls home_refresh itself (0x108E), EQ and format tags
    # first, then the name; Source with 0x21.3 set takes 0x0FA7 (EQ tag, icon, volume, then the name)
    ("bt_key_in_exit", [(NEC_BT, 4.0)], "exit", 0.08, 0x0E, 1.5, "home", None),
    ("source_flag_in_exit", [], "exit", 0.05, NEC_SOURCE, 1.0, "source", set_flag_213),
]
EARLY = 0.15                              # seconds after a key on page 1 during an exit: home complete


def key_scenarios():
    print("\nKeys during a wipe, whole firmware, against fast-lcd")
    for name, pre, when, into, cmd, settle, expect, inject in KEY_SCENARIOS:
        w0 = time.time()
        amps = [Amp(BASE), Amp(NEW)]
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
            # wait for the exit to start (the page timer is 2 s after the key)
            for amp in amps:
                amp.wait(1.9)
            for _ in range(40):
                if new.e.xram[bp.HN_MODE] == 2:
                    break
                for amp in amps:
                    amp.wait(0.005)
            check("%sexit running before the key" % label, new.e.xram[bp.HN_MODE] == 2)
        for amp in amps:
            amp.wait(into)
        x_at = new.e.xram[bp.HN_X] << 8 | new.e.xram[bp.HN_X + 1]
        mode_at, step_at = new.e.xram[bp.HN_MODE], new.e.xram[bp.HN_STEP]
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
        print("  %s key at %s step %d (x %d); %d steps after it" % (name, when, step_at, x_at, len(st)))
        check("%sa wipe was running at the key" % label, mode_at == (1 if when == "entry" else 2))
        if early is not None:
            check("%s%.2f s after the key: a whole home screen (= the stock refresh for that state)" %
                  (label, EARLY), early)
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new),
              "%s vs %s" % (state(ref), state(new)))
        if expect == "vol":
            check("%svolume page = vol_model (latest value)" % label,
                  new.page == 2 and screen(new.e) == volpage_reference(new), vol_diff(new.e))
            if name.endswith("in_exit"):
                xs = [s[3] for s in st if s[1] == 1]
                check("%sturned round: entry steps from x %d leftwards (the ease table's tail), first at %d"
                      % (label, x_at, xs[0] if xs else -1),
                      bool(xs) and xs[0] <= x_at and xs == [EASE[k] for k in range(N + 1 - len(xs), N + 1)])
        elif expect == "home":
            check("%shome = home_model" % label, new.page == 1 and screen_ok(ref, new))
        elif expect == "source":
            # input switched during the exit: hn_name_guard ends the exit with the whole home screen.
            # fast-lcd, back home a moment ago, may not have drawn its home yet, and Source postpones its
            # refresh by 2 s: it shows the name and status only until then. Both end on the same screen.
            check("%sinput switched on page 1: a whole home screen (= the stock refresh for that state)" % label,
                  new.page == 1 and screen(new.e) == stock_home_now(new))
        else:
            check("%sscreen identical to fast-lcd" % label, new.lcd.gram == ref.lcd.gram)
        check("%sno wipe left running" % label, new.e.xram[bp.HN_MODE] == 0)
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
    """Review repro: Source leaves home_refresh_periodic's flags set (0x20.6) for about 3 s; a Vol+ in
    that time, and the exit's render makes the flag path run 10 ticks into the exit."""
    print("\nSource, then Vol+ while the refresh flags are still set, then the exit")
    for gap in (0.2, 1.0, 2.0):
        name = "source_vol_%.1f" % gap
        label = "%-19s " % name
        amps = [Amp(BASE), Amp(NEW)]
        ref, new = amps
        w = Watch(new)
        ends = []
        w.on_step = lambda rec: rec[1] == 2 and rec[2] == N and ends.append(new.e.cycles)
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
        # run to the end of the exit, then two ticks
        for _ in range(400):
            if ends:
                break
            for amp in amps:
                amp.wait(0.01)
        for amp in amps:
            amp.wait(0.02)
        st = w.since(mark)
        print("  %s: flags 0x20.6/0x21.1/0x21.3 at the Vol+ %s; %d steps" % (name, flags, len(st)))
        check("%sentry and exit ran (%d steps)" % (label, 2 * N), [s[1] for s in st] == [1] * N + [2] * N)
        check("%stwo ticks after the exit: a whole home screen (= the stock refresh for that state)" % label,
              new.page == 1 and screen(new.e) == stock_home_now(new))
        new.lcd.save_png(os.path.join(HERE, "build", "keys_%s_end.png" % name))
        for amp in amps:
            amp.wait(2.0)
        check("%slater: home = home_model" % label, new.page == 1 and screen_ok(ref, new))
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new))
        audio_checks(label, ref, new, quiet=True)


def open_page(settle=1.0, vol=None):
    """Both images powered on (USB), then Vol+ from home and `settle` s: the volume page, at rest
    (vol: the speaker volume set in RAM 0x31 before the key, which then applies vol + 1)."""
    amps = [Amp(BASE), Amp(NEW)]
    for amp in amps:
        amp.set_pin(0xC0, 5, 0)
        amp.boot()
        amp.press(NEC_POWER)
        amp.wait(9.5)
        if vol is not None:
            amp.e.iram[0x31] = vol
        amp.press(NEC_VOL_UP)
        amp.wait(settle)
    return amps


def roll_scenarios():
    """Keys on the open volume page, whole firmware, against fast-lcd: the roll's 14 frames on
    consecutive ticks, each box = roll_box, the line moving with the spring, the page at rest = the
    static page; knob-speed repeats; a roll cut by Menu, Source, Power."""
    print("\nKeys on the open volume page: the number roll and the line's spring, whole firmware")
    ref, new = amps = open_page(vol=8)                 # the page at 9: then 10, 9, 8, 9 (one and two digits)
    w = Watch(new)
    check("page open and at rest before the keys", new.page == 2 and screen(new.e) == volpage_reference(new))
    for cmd, name in ((NEC_VOL_UP, "vol+"), (NEC_VOL_DOWN, "vol-"), (NEC_VOL_DOWN, "vol-2"), (NEC_VOL_UP, "vol+2")):
        label = "%-8s " % name
        old = str(new.e.iram[0x31])
        v_old = new.e.iram[0x31]
        mark = len(w.ticks)
        boxes = []

        def at_tick(rec, boxes=boxes):
            if rec[2]:
                boxes.append((rec, [[px(new.e, xx, yy) for yy in range(bp.ROLL_Y0, bp.ROLL_Y1 + 1)]
                                    for xx in range(bp.ROLL_X0, bp.ROLL_X1 + 1)]))
        w.on_tick = at_tick
        for amp in amps:
            amp.press(cmd)
        for amp in amps:
            amp.wait(0.8)
        w.on_tick = None
        vol = new.e.iram[0x31]
        up = vol > v_old
        tk = w.ticks[mark:]
        frames = [t[2] for t in boxes and [b[0] for b in boxes]]
        t0s = [b[0][3] for b in boxes]
        check("%s%s -> %d: 14 frames on consecutive ticks (Timer0 %s)" % (label, old, vol, t0s[:1] + t0s[-1:]),
              frames == list(range(1, 15)) and t0s == list(range(t0s[0], t0s[0] + 14)) if t0s else False, str(frames))
        bad = []
        for n, (rec, got) in enumerate(boxes, 1):
            is_old, dy, ink = roll_frame(n, up)
            fb = [[None] * W for _ in range(H)]
            roll_box(fb, old if is_old else str(vol), dy, ink)
            if any(got[xx - bp.ROLL_X0][yy - bp.ROLL_Y0] != fb[yy][xx] for xx in range(bp.ROLL_X0, bp.ROLL_X1 + 1)
                   for yy in range(bp.ROLL_Y0, bp.ROLL_Y1 + 1)):
                bad.append(n)
        check("%seach frame's box = roll_box (%s)" % (label, "up" if up else "down"), not bad, str(bad))
        splits = [t[4] for t in tk]
        check("%sthe line moves with the spring: split %d -> %d over %d ticks, monotonic, ends on the volume's" %
              (label, splits[0] if splits else -1, splits[-1] if splits else -1, len(splits)),
              bool(splits) and splits[-1] == bp.VLINE_SPLIT[vol] and
              all((b - a) * (1 if up else -1) >= 0 for a, b in zip(splits, splits[1:])))
        worst = max((t[5] for t in tk), default=0)
        check("%sworst tick %.2f ms (roll frame + spring fill; at most %g)" % (label, worst, STEP_LIMIT), worst <= STEP_LIMIT)
        STEP_MS["page_" + name] = worst
        check("%sthen at rest: the static page (vol_model), same state as fast-lcd" % label,
              screen(new.e) == volpage_reference(new) and state(ref) == state(new), vol_diff(new.e))
    # knob-speed repeats: a key every 60 ms
    for cmd, name in ((NEC_VOL_UP, "knob+"), (NEC_VOL_DOWN, "knob-")):
        label = "%-8s " % name
        mark = len(w.ticks)
        rolls = []
        w.on_tick = lambda rec: rec[2] == 1 and rolls.append(rec)
        for _ in range(6):
            for amp in amps:
                amp.press(cmd)
            for amp in amps:
                amp.wait(0.06)
        for amp in amps:
            amp.wait(0.9)
        w.on_tick = None
        tk = w.ticks[mark:]
        check("%s6 keys 60 ms apart: %d rolls started, page at rest = the static page for %d, same state as fast-lcd"
              % (label, len(rolls), new.e.iram[0x31]), len(rolls) == 6 and screen(new.e) == volpage_reference(new)
              and state(ref) == state(new), vol_diff(new.e))
        worst = max((t[5] for t in tk), default=0)
        check("%sworst tick %.2f ms" % (label, worst), worst <= STEP_LIMIT)
        STEP_MS["page_" + name] = worst
    audio_checks("page keys ", ref, new, quiet=True)
    # a roll cut by another key
    for cmd, name, expect in ((NEC_MENU_OPEN, "menu", "home"), (NEC_SOURCE, "source", "home"), (NEC_POWER, "power", "same")):
        label = "%-8s " % ("cut_" + name)
        ref, new = amps = open_page()
        w = Watch(new)
        for amp in amps:
            amp.press(NEC_VOL_UP)
        for amp in amps:
            amp.wait(0.06)
        rf = new.e.xram[bp.HR_F]
        for amp in amps:
            amp.press(cmd)
        for amp in amps:
            amp.wait(3.0)
        ok = new.e.xram[bp.HR_F] == 0 and new.e.xram[bp.HN_MODE] == 0
        if expect == "home":
            ok = ok and new.page == 1 and screen_ok(ref, new)
        else:
            ok = ok and new.lcd.gram == ref.lcd.gram
        check("%sVol+ on the page, %s at roll frame %d: no roll left, %s" % (
              label, name, rf, "home = home_model" if expect == "home" else "screen identical to fast-lcd"),
              ok and 1 < rf < 14 and state(ref) == state(new))
        audio_checks(label, ref, new, quiet=True)


def tint_scenarios():
    """The status line's tint across an input change, whole firmware: input_apply (0x5640) draws the
    new input's placeholder through 0x4BC9 long before the periodic refresh runs the loader (2-3 s).
    Seen on the amp with hn8: the placeholder reddish after a no-signal input."""
    print("\nStatus tint across an input change (whole firmware)")
    LOCK = (0xC0, 2, 0)                       # P4.2 low: optical/coax lock
    # (name, setup keys, key, pins at the key, placeholder, then (text, reddish) once the loader has run)
    cases = (("usb_nosig_source_lock", [], NEC_SOURCE, [LOCK], "Digital input", (None, False)),
             ("usb_nosig_source_nolock", [], NEC_SOURCE, [], "Digital input", ("No signal", True)),
             ("usb_nosig_select_bt", [], NEC_BT, [], "initializing", ("Searching...", True)),
             ("usb_nosig_select_aux", [], 0x15, [], "Analog input", ("Analog input", False)),
             ("bt_searching_source", [(NEC_BT, 4.0)], NEC_SOURCE, [], "Digital input", ("Disconnected", True)),
             ("bt_searching_bt_key", [(NEC_BT, 4.0)], 0x0E, [], "BT Reconnect", ("Searching...", True)))
    for name, setup, cmd, pins, placeholder, (text, lost) in cases:
        amp = Amp(NEW)
        amp.boot()
        amp.press(NEC_POWER)
        amp.wait(9.5)
        for c, t in setup:
            amp.press(c)
            amp.wait(t)
        e = amp.e
        check("%-24s before the key: %r reddish (no signal)" % (name, buffer_text(e, bp.SMALL_BUF)),
              status_tint(e) == bp.DIM_LOST and home_ok(e), home_diff(e))
        for p in pins:
            amp.set_pin(*p)
        amp.press(cmd)
        amp.wait(0.3)
        check("%-24s 0.3 s after the key: %r in grey" % (name, placeholder),
              buffer_text(e, bp.SMALL_BUF) == placeholder and status_tint(e) == bp.DIM and e.xram[bp.HN_SIG] == 1,
              "(%r, %s)" % (buffer_text(e, bp.SMALL_BUF), status_tint(e) and "%04X" % status_tint(e)))
        amp.wait(4.2)
        got = buffer_text(e, bp.SMALL_BUF)
        check("%-24s once the loader has run: %r %s" % (name, got, "reddish" if lost else "grey"),
              (text is None or got == text) and status_tint(e) == (bp.DIM_LOST if lost else bp.DIM) and home_ok(e),
              home_diff(e))


def edge_scan():
    """The panel-scan model (tools/emu/panel_video.py: 60 Hz, 12 + 320 + 12 lines, one memory row
    per line time) over an entry and an exit, scanning x upwards and downwards: every frame whose
    scan lies between the end of the first step and the start of the last shows a whole 2-px edge."""
    import panel_video as pv
    print("\nPanel scan during the wipes: a whole edge in every frame")
    for scan, phase in [(sc, ph) for sc in ("up", "down") for ph in (0.0, 0.0042, 0.0083, 0.0125)]:
        amp = Amp(NEW, log_audio=False)
        w = Watch(amp)
        amp.set_pin(0xC0, 5, 0)
        amp.boot()
        amp.press(NEC_POWER)
        amp.wait(9.0 + phase)                  # the frame phase against the ticks
        frames = []
        for press, lead, n in ((NEC_VOL_UP, 0.0, 30), (None, 1.3, 60)):   # the exit starts ~2.0 s after the key
            amp.wait(lead)
            start = amp.e.cycles
            for f, cols in pv.panel_frames(amp, n, scan, [(0.0, press)] if press else []):
                f0 = start + f * CLOCK_HZ / pv.FPS
                line = CLOCK_HZ / pv.FPS / pv.LINES
                frames.append((f0 + pv.PORCH_BACK * line, f0 + (pv.PORCH_BACK + pv.ROWS) * line, cols))
        acc = bp.ORANGE
        for mode in (1, 2):
            st = [s for s in w.steps if s[1] == mode]
            # the edge appears with the first step that moves it (the cubic's first steps do not)
            t_in = next(s for s in st if s[3] != (318 if mode == 1 else 0))
            t_out = next(s for s in st if s[2] == N)
            end1 = t_in[0] + t_in[4] * CLOCK_HZ / 1000
            inside = [fr for fr in frames if fr[0] >= end1 and fr[1] <= t_out[0]]
            bad = []
            for k, (a, b, cols) in enumerate(inside):
                full = [x for x in range(319) if all(v == acc for v in cols[x]) and all(v == acc for v in cols[x + 1])]
                if not full:
                    bad.append(k)
            check("scan %-4s phase %4.1f ms %s: %d frames inside the wipe, each with a whole 2-px edge" %
                  (scan, phase * 1000, "entry" if mode == 1 else "exit", len(inside)), inside and not bad, str(bad[:5]))


# ---- INT1 at a volume press ----------------------------------------------------------------------
INT1_T0 = 9.0                            # seconds after Power: USB settled and unmuted


def int1_job(offset_ms):
    """Both images: Vol+ at INT1_T0 + offset with INT1's RAM effects injected at the press."""
    out = []
    for img in (BASE, NEW):
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
        e.iram[0x21] |= 0x10                 # INT1 0x5702..0x570D: re-mute request, countdown 30, no format
        e.iram[0x43], e.iram[0x44] = 0, 30
        e.iram[0x4E] = 0xFF
        amp.wait(1.5)
        dac = [c for c in hits["dac"] if c >= t]
        un = [c for c in hits["unmute"] if c >= t]
        tr = audio_transitions(amp)
        out.append((t, dac[:1], un[:1], [(round(c, 4), s) for c, s in tr if c >= t - 0.001],
                    amp.e.xram[bp.HN_MODE] if img is NEW else 0))
    return offset_ms, out


def int1():
    print("\nINT1 receiver event at a Vol+ press (USB, settled), 100 offsets 1 ms apart, against fast-lcd")
    t0 = time.time()
    with mp.get_context("fork").Pool() as pool:
        res = pool.map(int1_job, range(100))
    order_bad, late_bad, audio_bad, shifts, race, race_bad = [], [], [], [], [], []

    def key_first(a, d):
        """The key's volume write (NJW1194 0x10 changes) comes before the DAC reconfiguration."""
        v0 = dict(a[0][1]).get(("njw", 16)) if a else None
        kv = next((c for c, s in a if dict(s).get(("njw", 16)) != v0), None)
        return kv is not None and bool(d) and kv <= d[0]
    for off, ((tr, dr, ur, ar, _), (tn, dn, un, an, _)) in res:
        if not (dn and un and dn[0] < un[0]):
            order_bad.append(off)
        if not (ur and un and un[0] - ur[0] <= 0.10):
            late_bad.append(off)
        else:
            shifts.append(un[0] - ur[0])
        if key_first(ar, dr) != key_first(an, dn):
            race.append(off)
            # only the order of the two differs: as many audio states, the same one at the end, and
            # the DAC reconfiguration no later than fast-lcd's
            if not (len(ar) == len(an) and ar and an and ar[-1][1] == an[-1][1] and
                    dn and dr and (dn[0] - tn) - (dr[0] - tr) <= 0.10):
                race_bad.append(off)
        elif [s for _, s in ar] != [s for _, s in an] or any(cn - cr > 0.10 for (cr, _), (cn, _) in zip(ar, an)):
            audio_bad.append(off)
    check("DAC reconfiguration (0x46A0) before the unmute (0x33FB), every offset", not order_bad, str(order_bad[:8]))
    check("unmute no later than fast-lcd + 0.10 s, every offset", not late_bad,
          "(shift %+.3f .. %+.3f s)" % (min(shifts), max(shifts)) if shifts else str(late_bad[:8]))
    # When the press lands near a format poll, the stock main loop runs the key's volume write or the
    # poll's DAC reconfiguration first depending on where in the loop and in the 10-tick poll period
    # the press is seen. The two images' loops are not in the same phase (fast-lcd's slower home
    # refreshes after power-on lose more ticks, so its poll period is shifted), so around the poll one
    # image may take the key first and the other the poll. Both orders are stock behaviour; at those
    # offsets only the order may differ.
    print("    press/format-poll race resolved differently at offsets %s (key first in fast-lcd: %s)" %
          (race, [key_first(res[o][1][0][3], res[o][1][0][1]) for o in race]))
    check("where the key/poll order differs (%d offsets): the same number of audio states, the same final "
          "state, the DAC reconfiguration no later than fast-lcd + 0.10 s" % len(race), not race_bad, str(race_bad[:8]))
    check("audio states after the press: same order, none more than 0.10 s later, every other offset",
          not audio_bad, str(audio_bad[:8]))
    print("  %d runs x 2 images in %.0f s" % (len(res), time.time() - t0))


SWEEP_STATES = ["standby", "home", "volume", "volume_hp", "menu"]


# A key press arms a timer (RAM 0x37:0x38) whose expiry, in the main loop, clears the IR key
# state (0x492b). A command injected in the very iteration where it expires is lost (a race in
# the stock firmware too, it makes the key read as "go home" on page 2). The first Vol+ arms that
# timer at its press, so it expires exactly 0.5 s later; press the second key at 0.6 s, away from
# that instant.
VOL_SETTLE = 0.6


def reach(img, st):
    """A fresh amp driven from reset into state st (the C core's ctypes pointers can't be
    deep-copied, so every job replays from reset instead of cloning a snapshot)."""
    a = Amp(img, log_audio=False)
    a.set_pin(0xC0, 5, 0)                        # USB audio present
    a.boot()
    if st != "standby":
        a.press(NEC_POWER); a.wait(8.0)
    if st == "volume":
        a.press(NEC_VOL_UP); a.wait(VOL_SETTLE)
    elif st == "volume_hp":
        a.e.iram[0x2B] = 2                       # headphone branch of 0x5936
        a.press(NEC_VOL_UP); a.wait(VOL_SETTLE)
    elif st == "menu":
        a.press(NEC_MENU_OPEN); a.wait(1.5)      # see NEC_MENU_OPEN above the tour
    return a


def run(img, st, cmd):
    """A fresh amp reached into state st, cmd pressed and settled 0.5 s later (the 200 ms wipe
    takes N ticks; the volume page times out after 2 s and the menu after 9 s, so both still hold)."""
    amp = reach(img, st)
    amp.press(cmd)
    amp.wait(0.5)
    return amp


def outcome(amp):
    e = amp.e
    return (amp.page, amp.powered) + tuple(e.iram[a] for a in (0x31, 0x52, 0x47, 0x2B, 0x39, 0x17)) + \
        (e.sfr[0xA0], e.sfr[0x80] & 0x46, e.sfr[0xC0] & 0x41)


def job(args):
    st, cmd = args
    base, new = run(BASE, st, cmd), run(NEW, st, cmd)
    ob, on = outcome(base), outcome(new)
    ok = screen_ok(base, new)
    if not ok and base.powered and new.powered and base.page == new.page == 1:
        # a home the stock sequence has not finished: keys that switch the input postpone the refresh
        # by 2 s and leave parts of the old home on screen in both images; after power-on the screen
        # shows the logo. Once the periodic refresh has run, the home must be home_model's (or, still
        # before the first home, the logo: identical to fast-lcd).
        for amp in (base, new):
            amp.wait(3.0)
        ok = (new.page == 1 and home_ok(new.e)) or new.lcd.gram == base.lcd.gram
        return st, cmd, ob, on, ok, True
    return st, cmd, ob, on, ok, False


def sweep():
    print("\nIR sweep: 256 commands x %d states, against fast-lcd" % len(SWEEP_STATES))
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
        diff = [c for s, c, a, b, ok, later in res if s == st and a != b]
        scr = [c for s, c, a, b, ok, later in res if s == st and not ok]
        later = [c for s, c, a, b, ok, lt in res if s == st and lt]
        if later:
            print("    %-10s home not finished 0.5 s after %s: checked once the periodic refresh has run"
                  % (st, " ".join("%02X" % c for c in later)))
        check("%-10s 256 commands: same page, power, volumes, input, output, EQ, pins" % st, not diff,
              str(["%02X" % c for c in diff[:8]]))
        check("%-10s screens as expected (home: home_model; volume: vol_model; "
              "other: identical to fast-lcd)" % st, not scr, str(["%02X" % c for c in scr[:8]]))
    print("  sweep in %.0f s" % (time.time() - t0))


def report_steps():
    if STEP_MS:
        k, v = max(STEP_MS.items(), key=lambda kv: kv[1])
        print("\nWorst tick measured (wipe step, roll frame, spring): %.2f ms (%s)" % (v, k))


GROUPS = {
    "unit": [image_diff, test_home, test_status_tint, test_name_ptr, test_draw_volume, test_volpage,
             test_step, test_roll, test_spring, test_enter_vol, test_home_tail, test_align],
    "tour": [tour, input_scenarios, key_scenarios, flag_exit_scenarios, roll_scenarios, tint_scenarios, edge_scan],
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
