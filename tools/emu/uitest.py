"""Shared emulator helpers for UI theme tests (tools/patch/uikit.py and the features built with it).

    import uitest as ut
    e = ut.emu(image, theme=(0xFF, 0xFF))
    ut.paint(e, labels, kit, "font_big", text="USB", x=16, y=75)
    ut.px(e, x, y)

Screen coordinates are firmware coordinates: x 0..319, y 0..169.
"""
from emu8051 import Emu8051

W, H = 320, 170
STR_AT = 0x0200                          # scratch XDATA for test strings (not used by the firmware)


def emu(img, theme=(0xFF, 0xFF)):
    """A fresh emulator on img, SP as the firmware sets it, RAM 0x48:0x49 = the COLOR tint."""
    e = Emu8051(img)
    e.sfr[0x81] = 0x88
    e.iram[0x48], e.iram[0x49] = theme
    return e


def px(e, x, y):
    return e.lcd.screen_pixel(x, y)


def screen(e):
    return [[px(e, x, y) for y in range(H)] for x in range(W)]


def fill_screen(e, colour):
    e.lcd.gram = [colour] * len(e.lcd.gram)


def ink_in(e, x0, y0, w, h):
    return any(px(e, x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h))


def stray(e, boxes):
    """Lit pixels outside every (x, y, w, h) box."""
    n = 0
    for x in range(W):
        for y in range(H):
            if px(e, x, y) and not any(bx <= x < bx + bw and by <= y < by + bh
                                       for bx, by, bw, bh in boxes):
                n += 1
    return n


def stock_small(e, ch, x, y):
    """The stock small_glyph_paint 0x2DF8: one 14 x 24 character in the COLOR tint."""
    e.setR(6, 0); e.setR(7, y); e.setR(4, x >> 8); e.setR(5, x & 0xFF); e.setR(3, ord(ch))
    e.call(0x2DF8)


def stock_big(e, ch, x, y):
    """The stock big_glyph_paint 0x3F3C: one 30 x 32 character in the COLOR tint."""
    e.setR(6, 0); e.setR(7, y); e.setR(4, x >> 8); e.setR(5, x & 0xFF); e.setR(3, ord(ch))
    e.call(0x3F3C)


def stock_glyph(img, ch, theme=(0xFF, 0xFF)):
    """30 x 32 bitmap of a big-font character, painted by the stock big_glyph_paint."""
    e = emu(img, theme)
    stock_big(e, ch, 10, 10)
    return [[px(e, 10 + i, 10 + j) for j in range(32)] for i in range(30)]


def scaled_match(e, x0, y0, ref):
    """The 2x image of a 30 x 32 bitmap ref at x0, y0."""
    return all(px(e, x0 + 2 * i + a, y0 + 2 * j + b) == ref[i][j]
               for i in range(30) for j in range(32) for a in (0, 1) for b in (0, 1))


def set_fp(e, labels, kit, font, text=None, code_ptr=None, x=0, y=0, ink=0xFFFF, bg=0, clip=(0, 319), scale=1):
    """Fill uk_paint's parameter block: text goes to scratch XDATA (STR_AT), or code_ptr is used."""
    if text is not None:
        for k, ch in enumerate(text.encode() + b"\0"):
            e.xram[STR_AT + k] = ch
        ptr, spc = STR_AT, 0
    else:
        ptr, spc = code_ptr, 1
    f = labels[font]
    vals = [f >> 8, f & 0xFF, ptr >> 8, ptr & 0xFF, spc, x >> 8, x & 0xFF, y, ink >> 8, ink & 0xFF,
            bg >> 8, bg & 0xFF, clip[0] >> 8, clip[0] & 0xFF, clip[1] >> 8, clip[1] & 0xFF, scale]
    for k, v in enumerate(vals):
        e.xram[kit.FP + k] = v


def fp_end(e, kit):
    return (e.xram[kit.FP_END] << 8) | e.xram[kit.FP_END + 1]


def paint(e, labels, kit, *args, **kw):
    """set_fp, then uk_paint; returns the clocks it took."""
    set_fp(e, labels, kit, *args, **kw)
    c0 = e.cycles
    e.call(labels["uk_paint"])
    return e.cycles - c0


def firmware_strings(base):
    """Every NUL-terminated printable string in the stock string area (0x9040..0x9397)."""
    out, cur = [], b""
    for b in base[0x9040:0x9398]:
        if b == 0:
            if len(cur) >= 2:
                out.append(cur.decode())
            cur = b""
        elif 0x20 <= b < 0x7F:
            cur += bytes([b])
        else:
            cur = b""
    return sorted(set(out))


def sample_rate_strings(base):
    """The status strings format 0x3CDC writes for every sample-rate code."""
    seen = set()
    for v in range(256):
        e = emu(base)
        e.setR(7, v)
        e.call(0x3CDC, 2_000_000)
        s = bytes(e.xram[0x50:0x69]).split(b"\0")[0]
        if s:
            seen.add(s.decode())
    return sorted(seen)


def set_tp(e, labels, kit, font, text, x=0, y=0, ink=0xFFFF, bg=0, clip=(0, 319), align=0, spacing=0,
           code_ptr=None):
    """Fill uk_text's parameter block: text goes to scratch XDATA (STR_AT), or code_ptr is used."""
    if code_ptr is None:
        for k, ch in enumerate(text.encode() + b"\0"):
            e.xram[STR_AT + k] = ch
        ptr, spc = STR_AT, 0
    else:
        ptr, spc = code_ptr, 1
    f = labels[font]
    vals = [f >> 8, f & 0xFF, ptr >> 8, ptr & 0xFF, spc, x >> 8, x & 0xFF, y, ink >> 8, ink & 0xFF,
            bg >> 8, bg & 0xFF, clip[0] >> 8, clip[0] & 0xFF, clip[1] >> 8, clip[1] & 0xFF, align, spacing]
    for k, v in enumerate(vals):
        e.xram[kit.tp_base + k] = v


def tp_end(e, kit):
    return (e.xram[kit.TP["END"]] << 8) | e.xram[kit.TP["END"] + 1]


def text(e, labels, kit, *args, **kw):
    """set_tp, then uk_text; returns the clocks it took."""
    set_tp(e, labels, kit, *args, **kw)
    c0 = e.cycles
    e.call(labels["uk_text"])
    return e.cycles - c0
