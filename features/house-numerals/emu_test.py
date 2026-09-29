#!/usr/bin/env python3
"""Emulator tests for House Numerals hn5 (see README.md).

  python3 emu_test.py unit    image diff, then every routine at its hook: the home screen against
                              home_model, a wipe step by step, entry/exit/reversal/cancel logic
  python3 emu_test.py tour    whole firmware from reset, lockstep with fast-lcd: the tour, a volume
                              key per input, keys during the wipes, the stack check
  python3 emu_test.py int1    INT1 receiver event at a Vol+ press, 100 offsets, against fast-lcd
  python3 emu_test.py sweep   all 256 IR commands in five states, against fast-lcd
  python3 emu_test.py         all four
"""
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

BASE = open(bp.BASE_IMAGE, "rb").read()
NEW = open(bp.OUT_IMAGE, "rb").read()
LAB = bp.assemble()[1]
W, H = 320, 170
EASE = bp.EASE
STEP_END = 0x5B2D                        # main_tasks_on, after the lcall uk_tasks (0x5B2A)
fails = []


def check(name, ok, detail=""):
    print("  %-72s %s %s" % (name, "OK  " if ok else "FAIL", detail))
    if not ok:
        fails.append(name)


def emu(theme=(0xFF, 0xFF), img=NEW):
    return ut.emu(img, theme)


px, screen, fill_screen, ink_in, stray = ut.px, ut.screen, ut.fill_screen, ut.ink_in, ut.stray
stock_small, stock_big, scaled_match = ut.stock_small, ut.stock_big, ut.scaled_match


def stock_glyph(ch, theme=(0xFF, 0xFF)):
    return ut.stock_glyph(NEW, ch, theme)


_GLYPHS = {}


def glyphs():
    if not _GLYPHS:
        _GLYPHS.update({d: stock_glyph(str(d)) for d in range(10)})
    return _GLYPHS


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
    changed = {i for i in range(len(BASE)) if BASE[i] != NEW[i]} - {vp + 1, vp + 3}
    check("inside the base image only the hooks changed (plus version pointer)", changed == want,
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
    lab = dict(LAB, hn_ease=LAB["ease"], hn_font_small=LAB["font_small"], hn_font_big=LAB["font_big"],
               hn_map_small=LAB["map_small"], hn_map_big=LAB["map_big"])
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


def model_tag(fb, text, right, acc):
    t = text[:5].rstrip(" ")
    wd = bp.PF_TAG.width(t)
    w = wd + 2 * bp.TAG_PAD
    x = right - w
    for xx in range(x, x + w):
        fb[bp.TAG_Y0][xx] = fb[bp.TAG_Y1][xx] = acc
    for yy in range(bp.TAG_Y0 + 1, bp.TAG_Y1):
        fb[yy][x] = fb[yy][x + w - 1] = acc
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
                                                    bp.DIM, 0, spacing=bp.STAT_SP))
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


def home_state(e, inp=1, out=1, vol=32, hp=20, mute=False, eq=1, fmt=2, sub=2, status="96kHz", theme=None):
    ir = e.iram
    ir[0x45], ir[0x4F] = 1, 1
    ir[0x47], ir[0x2B], ir[0x31], ir[0x52], ir[0x39], ir[0x3D], ir[0x75] = inp, out, vol, hp, eq, fmt, sub
    ir[0x7E] = fmt
    ir[0x22] = (ir[0x22] & ~0x02) | (0x02 if mute else 0)
    if theme:
        ir[0x48], ir[0x49] = theme
    for k, ch in enumerate(status.encode() + b"\0"):
        e.xram[bp.SMALL_BUF + k] = ch


def home_draw(e):
    """What home_refresh_periodic draws: home_refresh, then the status line (y 135)."""
    c0 = e.cycles
    e.call(bp.HOME_REFRESH)
    e.setR(6, 0); e.setR(7, bp.STATUS_Y)
    e.call(0x3A53)
    return (e.cycles - c0) * 1000 / CLOCK_HZ


def test_home():
    print("\nhome screen (home_refresh + the status line) against home_model")
    cases = [dict(inp=i) for i in range(1, 9)] + [dict(out=2, hp=7), dict(mute=True), dict(mute=True, out=2)]
    cases += [dict(eq=q) for q in (0, 2, 3, 4, 5, 6, 7, 8, 9)]
    cases += [dict(fmt=f, sub=u) for f in (0, 1, 3, 4, 5, 6) for u in (2, 3, 4, 5)]
    cases += [dict(vol=v) for v in (0, 5, 9, 10, 47, 60)]
    cases += [dict(status=t) for t in ("No signal", "Searching...", "2.8224MHz", "Analog input", "")]
    bad, worst = [], 0
    for c in cases:
        for theme in ((0xFF, 0xFF), (0x07, 0xE0)):
            e = emu(theme)
            home_state(e, **c)
            worst = max(worst, home_draw(e))
            if not home_ok(e):
                bad.append((c, theme, home_diff(e)))
    check("%d states x 2 tints (inputs, outputs, mute, EQ, formats, volumes, status lines): = home_model"
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


def expect_volume(e, v, acc):
    """Number box and position line as hn_draw_volume leaves them for volume v."""
    g = glyphs()
    v = min(v, 60)
    tens, ones = divmod(v, 10)
    ok = scaled_match(e, 244, 42, g[ones])
    ok = ok and ((not ink_in(e, 184, 42, 60, 64)) if tens == 0 else scaled_match(e, 184, 42, g[tens]))
    w = 4 * v
    return ok and all(px(e, x, y) == (acc if x < 40 + w else bp.TRACK)
                      for x in range(40, 280) for y in range(136, 139))


def test_draw_volume():
    print("\nhn_draw_volume (the 0x5936 hook): every step, three themes")
    for theme, acc in (((0xFF, 0xFF), bp.ORANGE), ((0xF8, 0x00), 0xF800), ((0x33, 0xBF), 0x33BF)):
        bad = []
        for v in range(61):
            e = emu(theme)
            e.iram[0x2B] = 1
            e.setR(7, v)
            e.call(0x5936)
            if not (expect_volume(e, v, acc) and (e.iram[0x48], e.iram[0x49]) == theme):
                bad.append(v)
        check("theme %02X%02X: steps 0-60, accent %04X, theme untouched" % (theme + (acc,)), not bad, str(bad[:5]))
    e = emu(); e.iram[0x2B] = 1; e.setR(7, 25); e.call(0x5936)
    check("only the number box and the line are drawn", stray(e, [(184, 42, 120, 64), (40, 136, 240, 3)]) == 0)
    check("XDATA 0x05 = 2 as stock; HN_VOL 25, HN_NUM \"25\"",
          e.xram[5] == 2 and e.xram[bp.HN_VOL] == 25 and bytes(e.xram[bp.HN_NUM:bp.HN_NUM + 3]) == b"25\0")
    e = emu(); e.iram[0x2B] = 2; e.iram[0x52] = 33; e.setR(7, 10); e.call(0x5936)
    check("headphone output draws RAM 0x52 (33), as stock", expect_volume(e, 33, bp.ORANGE))
    e = emu(); e.iram[0x2B] = 1; e.setR(7, 75); e.call(0x5936)
    check("a value above 60 is drawn as 60", expect_volume(e, 60, bp.ORANGE))
    e = emu(); e.iram[0x2B] = 1
    e.setR(7, 45); e.call(0x5936)
    e.setR(7, 44); e.call(0x5936)
    check("redraw 45 -> 44 leaves nothing behind", expect_volume(e, 44, bp.ORANGE))
    e.setR(7, 4); e.call(0x5936)
    check("redraw 44 -> 4 blanks the tens digit", expect_volume(e, 4, bp.ORANGE))
    # during a wipe: only recorded, unless the wipe has revealed the box / the line
    for vf, want_num, want_line in ((0, False, False), (bp.VF_NUM, True, False),
                                    (bp.VF_LINE, False, True), (bp.VF_ALL, True, True)):
        e = emu(); e.iram[0x2B] = 1
        e.xram[bp.HN_MODE], e.xram[bp.HN_VF] = 1, vf
        e.setR(7, 37); e.call(0x5936)
        num = ink_in(e, 184, 42, 120, 64)
        line = ink_in(e, 40, 136, 240, 3)
        check("wipe running, revealed %-10s: number %s, line %s, HN_VOL 37" %
              (bin(vf), "drawn" if want_num else "not drawn", "drawn" if want_line else "not drawn"),
              num == want_num and line == want_line and e.xram[bp.HN_VOL] == 37)


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
    e.call(LAB["hn_volpage"])
    ref = emu()
    for k, ch in enumerate("OPTICAL"):
        stock_small(ref, ch, 16 + 14 * k, 30)
    check("input name in white at 16,30, as the stock small glyphs", ink_in(e, 16, 30, 98, 24) and
          all(px(e, x, y) == px(ref, x, y) for x in range(16, 114) for y in range(30, 54)))
    check("divider 1x104 at 140,14", all(px(e, 140, y) == bp.DIVIDER for y in range(14, 118)))
    ref = emu((bp.ORANGE >> 8, bp.ORANGE & 0xFF))
    for k, ch in enumerate("VOL"):
        stock_small(ref, ch, 158 + 14 * k, 14)
    check("VOL in the accent at 158,14, as the stock small glyphs",
          all(px(e, x, y) == px(ref, x, y) for x in range(158, 200) for y in range(14, 38)))
    check("number and line for 25", expect_volume(e, 25, bp.ORANGE))
    check("nothing else drawn", stray(e, [(16, 30, 98, 24), (140, 14, 1, 104), (158, 14, 42, 24),
                                           (184, 42, 120, 64), (40, 136, 240, 3)]) == 0)
    check("render flags cleared as by 0x22FA",
          not e.iram[0x22] & 0x08 and e.iram[0x32] == 0 and e.iram[0x46] == 0)
    check("theme colour untouched; the page is on screen (HN_VF all)",
          (e.iram[0x48], e.iram[0x49]) == (0xFF, 0xFF) and e.xram[bp.HN_VF] == bp.VF_ALL)
    e.lcd.save_png(os.path.join(HERE, "build", "unit_volpage.png"))
    e = emu()
    e.iram[0x47], e.iram[0x2B], e.iram[0x31] = 7, 1, 5
    e.call(LAB["hn_volpage"])
    check("input 7 (no name): name area empty, number drawn",
          not ink_in(e, 0, 0, 140, 130) and expect_volume(e, 5, bp.ORANGE))
    e = emu(); e.iram[0x47], e.iram[0x2B], e.iram[0x31] = 2, 1, 25
    e.xram[bp.HN_MODE] = 1
    e.call(LAB["hn_volpage"])
    check("during a wipe: nothing drawn, volume recorded", not any(e.lcd.gram) and e.xram[bp.HN_VOL] == 25)


# ---- a wipe, step by step ----------------------------------------------------------------------
VOL_BOXES = {bp.VF_NAME: (16, 30, 14 * 7, 24), bp.VF_DIV: (140, 14, 1, 104), bp.VF_VOL: (158, 14, 42, 24),
             bp.VF_NUM: (184, 42, 120, 64), bp.VF_LINE: (40, 136, 240, 3)}


def home_setup(e, inp=2, status="No signal"):
    e.iram[0x45] = 1
    e.iram[0x47], e.iram[0x2B], e.iram[0x31] = inp, 1, 25
    e.iram[0x3D], e.iram[0x75], e.iram[0x7E] = 2, 2, 2       # PCM
    e.iram[0x4F] = 1
    for k, ch in enumerate(status.encode() + b"\0"):
        e.xram[bp.SMALL_BUF + k] = ch


def home_reference(inp=2, status="No signal"):
    """The home screen as the refresh draws it (home_refresh + the status line), on black."""
    e = emu()
    home_setup(e, inp, status)
    e.call(bp.HOME_REFRESH)
    e.setR(6, 0); e.setR(7, bp.STATUS_Y)
    e.call(0x3A53)
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
    check("ease table: 21 positions 318 -> 0, symmetric, every step at least 2 px, at most 25",
          len(EASE) == 21 and EASE[0] == 318 and EASE[-1] == 0 and
          all(2 <= EASE[k] - EASE[k + 1] <= 25 for k in range(20)) and
          all(EASE[k] + EASE[20 - k] == 318 for k in range(21)), str(EASE))
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
    for k in range(1, 21):
        worst = max(worst, run_steps(e, 1)[0])
        x = EASE[k]
        got_x = e.xram[bp.HN_X] << 8 | e.xram[bp.HN_X + 1]
        rev = {b for b, (bx, by, bw, bh) in VOL_BOXES.items() if bx >= x + 2 or k == 20}
        vf = e.xram[bp.HN_VF]
        if vf != sum(rev):
            bad.append((k, "flags %s" % bin(vf)))
        new = [b for b in rev if not any(b in o for o in order)]
        order.append(set(new))
        s = screen(e)
        for xx in range(W):
            for yy in range(H):
                if k < 20 and xx < x:
                    want = 0x1234
                elif k < 20 and xx < x + 2:
                    want = bp.ORANGE
                else:
                    want = 0
                    for b, (bx, by, bw, bh) in VOL_BOXES.items():
                        if bx <= xx < bx + bw and by <= yy < by + bh and (b in rev or b == bp.VF_LINE):
                            want = refs[xx][yy]
                if s[xx][yy] != want:
                    bad.append((k, xx, yy, hex(s[xx][yy]), hex(want)))
                    break
            if bad and bad[-1][0] == k:
                break
        if got_x != x:
            bad.append((k, "x", got_x))
    names = {bp.VF_NAME: "name", bp.VF_DIV: "divider", bp.VF_VOL: "VOL", bp.VF_NUM: "number", bp.VF_LINE: "line"}
    print("    entry reveal: " + ", ".join("%s at step %d (x %d)" % ("+".join(names[b] for b in o), k + 1, EASE[k + 1])
                                           for k, o in enumerate(order) if o))
    check("entry: each step x = ease[k]; old page left of the edge, 2-px accent edge, black band, "
          "elements once the edge is left of them", not bad, str(bad[:3]))
    check("entry: final screen = hn_volpage's render; mode 0, HN_VF all",
          screen(e) == refs and e.xram[bp.HN_MODE] == 0 and e.xram[bp.HN_VF] == bp.VF_ALL)
    check("entry: worst step %.2f ms (at most %g)" % (worst, STEP_LIMIT), worst <= STEP_LIMIT)
    STEP_MS["entry"] = worst
    e.call(LAB["hn_step"])
    check("hn_step when idle: nothing", screen(e) == refs and e.xram[bp.HN_STEP] == 20)

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
        for k in range(1, 21):
            if k == 11:                       # the stock refresh loads the status line 10 ticks in
                for j, ch in enumerate(status.encode() + b"\0"):
                    e.xram[bp.SMALL_BUF + j] = ch
                e.xram[bp.HN_SBUF] = 1
            worst = max(worst, run_steps(e, 1)[0])
            x = 318 - EASE[k]
            rev = {b for b, (x0, x1, y0, y1) in boxes.items()
                   if k == 20 or (x1 < x and (b != bp.HF_STAT or k >= 11))}
            drawn = set().union(*order) if order else set()
            if k < 20 and {bp.HF_NAME, bp.HF_STAT} <= rev - drawn:
                rev.discard(bp.HF_STAT)       # not in the name's step: the status line waits one
            if e.xram[bp.HN_HF] != sum(rev):
                bad.append((k, "flags", bin(e.xram[bp.HN_HF]), bin(sum(rev))))
            new = [b for b in rev if not any(b in o for o in order)]
            order.append(set(new))
            s = screen(e)
            for xx in range(W):
                for yy in range(H):
                    if k < 20 and xx >= x + 2:
                        want = vs[xx][yy]
                    elif k < 20 and xx >= x:
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
        check("input %d exit: final screen = the home refresh = home_model; mode 0, HN_VF 0, HN_HF all" % inp,
              e.lcd.gram == href.lcd.gram and home_ok(href) and e.xram[bp.HN_MODE] == 0 and e.xram[bp.HN_VF] == 0 and
              e.xram[bp.HN_HF] == bp.HF_ALL)
        check("input %d exit: worst step %.2f ms (at most %g)" % (inp, worst, STEP_LIMIT), worst <= STEP_LIMIT)
        STEP_MS["exit_%d" % inp] = worst

    # reversals: entry turned round into an exit at the same x, and back
    href = home_reference()
    vref = volpage_render()
    for turn in (1, 5, 10, 19):
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
        ok = e.xram[bp.HN_MODE] == 0 and xs == [318 - EASE[k] for k in range(20 - turn + 1, 21)]
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
            e.call(bp.HOME_REFRESH)
            e.setR(6, 0); e.setR(7, bp.STATUS_Y)
            e.call(0x3A53)
            same, note = same and screen(e) == h, " (status line at the refresh, tick 10)"
        check("entry turned round after step %2d (x %3d): exit from there, %d steps, home as the stock refresh%s"
              % (turn, x0, turn, note), ok and same, str(xs[:3]))
    for turn in (1, 6, 12, 19):
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
        ok = e.xram[bp.HN_MODE] == 0 and xs == [EASE[k] for k in range(20 - turn + 1, 21)]
        check("exit turned round after step %2d (x %3d) by a volume key: entry from there, %d steps, page for 27"
              % (turn, x0, turn), ok and screen(e) == screen(volpage_render(vol=27)), str(xs[:3]))
    e = home_reference(); e.iram[0x4F] = 1
    e.call(LAB["hn_enter_vol"]); e.iram[0x59] = 1; e.call(LAB["hn_clear"])
    check("entry turned round before its first step: stops, screen untouched (the page never showed)",
          e.xram[bp.HN_MODE] == 0 and screen(e) == screen(href))


STEP_MS = {}
STEP_LIMIT = 8.0                          # ms: a step must stay well inside the 10 ms tick


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
        check("%s, exit at step 7: entry at step 13, same x" % label,
              (e.xram[bp.HN_MODE], e.xram[bp.HN_STEP], xv(e)) == (1, 13, 318 - EASE[7]) and EASE[13] == 318 - EASE[7])
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
            ok = e.xram[bp.HN_MODE] == 2 and e.xram[bp.HN_STEP] == 13 and xv(e) == EASE[7] and not seen
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
    # uk_tasks: a step only after a tick, and only with the amp on
    for tick, power, mode, want in ((0, 1, 1, False), (1, 1, 1, True), (1, 0, 1, False), (1, 2, 1, False), (1, 1, 0, False)):
        e = st(mode, 0, 3, EASE[3])
        e.iram[0x4F] = power
        e.iram[0x20] = 0x80 if tick else 0
        e.iram[0x45] = 5                      # a page without a renderer: main_tick_tasks draws nothing
        seen = []
        e.hooks[0x3325] = lambda em: seen.append(em.xram[bp.HN_STEP])
        e.call(LAB["uk_tasks"])
        check("uk_tasks: tick %d, 0x4F %d, mode %d -> main_tick_tasks%s" % (tick, power, mode,
              ", then one step" if want else " only"),
              seen == [3] and e.xram[bp.HN_STEP] == (4 if want else 3))
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
    ("vol_up", NEC_VOL_UP, 0.5, "vol"),
    ("vol_up2", NEC_VOL_UP, 0.5, "vol"),
    ("back_home", None, 2.5, "home"),
    ("source", NEC_SOURCE, 11.0, "home"),   # OPTICAL has no signal: ~10 s detect timeout
    ("menu", NEC_MENU_OPEN, 1.5, "same"),   # opens the menu (page -> 3), screen identical to fast-lcd
    ("menu_down", NEC_DOWN, 1.0, "same"),   # navigates the cursor down inside the menu (RAM 0x17)
    ("menu_timeout", None, 9.5, "home"),    # ~9 s of inactivity in the menu returns home
    ("hdmi", NEC_HDMI, 3.0, "home"),
    ("vol_down", NEC_VOL_DOWN, 0.5, "vol"),
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
    """What hn_volpage draws for this amp's state, on a black screen."""
    e = emu((amp.e.iram[0x48], amp.e.iram[0x49]))
    for a in (0x31, 0x47, 0x2B, 0x52):
        e.iram[a] = amp.e.iram[a]
    e.call(LAB["hn_volpage"])
    return e.lcd.gram


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
    """Logs every wipe step (start clock, mode, step, x after, duration) and uk_fill calls."""

    def __init__(self, amp):
        self.amp = amp
        self.steps, self.fills, self._open = [], [], None
        self.on_step = None                  # fn(step record) after each step
        e = amp.e
        e.hooks[LAB["hn_step"]] = self._start
        e.hooks[LAB["uk_fill"]] = lambda em: self.fills.append(
            (em.cycles, (em.R(2) << 8) | em.R(3), em.R(1), (em.R(6) << 8) | em.R(7)))

    def _start(self, em):
        mode = em.xram[bp.HN_MODE]
        self._open = (em.cycles, mode) if mode else None
        if mode:                             # STEP_END runs on every main pass: hook it only now
            em.hooks[STEP_END] = self._end

    def _end(self, em):
        em.hooks.pop(STEP_END, None)
        if self._open:
            c0, mode = self._open
            x = em.xram[bp.HN_X] << 8 | em.xram[bp.HN_X + 1]
            self.steps.append((c0, mode, em.xram[bp.HN_STEP], x, (em.cycles - c0) * 1000 / CLOCK_HZ))
            self._open = None
            if self.on_step:
                self.on_step(self.steps[-1])

    def mark(self):
        return len(self.steps), len(self.amp.events), len(self.fills)

    def since(self, mark):
        return self.steps[mark[0]:]

    def worst(self):
        return max((s[4] for s in self.steps), default=0.0)


def wipe_checks(label, w, mark, mode, n=20):
    """The steps since mark: n of them, all in this mode, x from the ease table."""
    st = [s for s in w.since(mark)]
    xs = [s[3] for s in st]
    want = [EASE[k] if mode == 1 else 318 - EASE[k] for k in range(21 - n, 21)]
    check("%s%s: %d steps, x as the ease table" % (label, "entry" if mode == 1 else "exit", n),
          [s[1] for s in st] == [mode] * n and xs == want, "(%d steps, x %s)" % (len(st), xs[:3]))
    return st


def vol_entry_checks(step, new, w, mark):
    """A volume-key entry from home: 20 steps, and the NJW1194 volume write before the first."""
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
    ref = volpage_reference(new)
    rs = [[ref[xx * 240 + 0x23 + yy] for yy in range(H)] for xx in range(W)]
    for xx in range(W):
        for yy in range(H):
            p = px(new.e, xx, yy)
            if xx < x:
                want = before[xx][yy]
            elif xx < x + 2:
                want = accent_of(new)
            else:
                want = 0
                for b, (bx, by, bw, bh) in VOL_BOXES.items():
                    if bx <= xx < bx + bw and by <= yy < by + bh and (bx >= x + 2 or b == bp.VF_LINE):
                        want = rs[xx][yy]
            if p != want:
                return (xx, yy, hex(p), hex(want))
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
        mid = []

        exit_end = []

        def at_step(rec, before=before, mid=mid, step=step):
            if rec[1] == 1 and rec[2] == 10 and not mid:
                mid.append(mid_entry_ok(new, before, 10) or True)
                new.lcd.save_png(os.path.join(HERE, "build", "tour_%s_mid.png" % step))
            if rec[1] == 2 and rec[2] == 20:
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
            check("%-12s volume page exactly as hn_volpage draws it" % step,
                  new.page == 2 and new.lcd.gram == volpage_reference(new))
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
    new's state (both page 1, both powered), hn_volpage's exact render (both page 2, both powered),
    or bit-identical to base otherwise."""
    if base.powered and new.powered:
        if new.page == 1 and base.page == 1:
            return home_ok(new.e)
        if new.page == 2 and base.page == 2:
            return new.lcd.gram == volpage_reference(new)
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
                  new.e.xram[bp.HN_MODE] == 0 and len(st) < 20)
        else:
            vol_entry_checks(name, new, w, mark)
            print("    %s unmute countdown at the press: %d" % (label, cd_press))
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new),
              "%s vs %s" % (state(ref), state(new)))
        check("%spage %d, screen as expected (volume: hn_volpage's render; home: home_model)" %
              (label, page), new.page == page and screen_ok(ref, new))
        new.lcd.save_png(os.path.join(HERE, "build", "inputs_%s.png" % name))
        for amp in amps:
            amp.wait(2.5)
        if name != "splash":
            wipe_checks(label, w, (mark[0] + 20,) + mark[1:], 2)
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
    e.call(bp.HOME_REFRESH)
    e.setR(6, 0); e.setR(7, bp.STATUS_Y)
    e.call(0x3A53)
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
    ("source_late_exit", [], "exit", 0.17, NEC_SOURCE, 1.0, "source", None),
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
            check("%svolume page exactly as hn_volpage draws it (latest value)" % label,
                  new.page == 2 and new.lcd.gram == volpage_reference(new))
            if name.endswith("in_exit"):
                xs = [s[3] for s in st if s[1] == 1]
                check("%sturned round: entry steps from x %d leftwards, first at %d" % (label, x_at, xs[0] if xs else -1),
                      bool(xs) and xs[0] < x_at and xs[-1] == 0 and all(a > b for a, b in zip(xs, xs[1:])))
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
        w.on_step = lambda rec: rec[1] == 2 and rec[2] == 20 and ends.append(new.e.cycles)
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
        check("%sentry and exit ran (40 steps)" % label, [s[1] for s in st] == [1] * 20 + [2] * 20)
        check("%stwo ticks after the exit: a whole home screen (= the stock refresh for that state)" % label,
              new.page == 1 and screen(new.e) == stock_home_now(new))
        new.lcd.save_png(os.path.join(HERE, "build", "keys_%s_end.png" % name))
        for amp in amps:
            amp.wait(2.0)
        check("%slater: home = home_model" % label, new.page == 1 and screen_ok(ref, new))
        check("%ssame page, power, volumes, input, output" % label, state(ref) == state(new))
        audio_checks(label, ref, new, quiet=True)


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
            t_in = next(s for s in st if s[2] == 1)
            t_out = next(s for s in st if s[2] == 20)
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
    takes 20 ticks; the volume page times out after 2 s and the menu after 9 s, so both still hold)."""
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
        check("%-10s screens as expected (home: home_model; volume: hn_volpage; "
              "other: identical to fast-lcd)" % st, not scr, str(["%02X" % c for c in scr[:8]]))
    print("  sweep in %.0f s" % (time.time() - t0))


def report_steps():
    if STEP_MS:
        k, v = max(STEP_MS.items(), key=lambda kv: kv[1])
        print("\nWorst wipe step measured: %.2f ms (%s)" % (v, k))


GROUPS = {
    "unit": [image_diff, test_home, test_name_ptr, test_draw_volume, test_volpage,
             test_step, test_enter_vol, test_home_tail, test_align],
    "tour": [tour, input_scenarios, key_scenarios, flag_exit_scenarios, edge_scan],
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
