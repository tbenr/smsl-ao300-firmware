#!/usr/bin/env python3
"""Render what the AO300's panel shows, from the emulator, as a 60 fps video.

The ST7789 refreshes the glass from its memory on its own: FRCTRL2 0x0F is 60 Hz, and the
porch setting B2 0C 0C gives 12 + 320 + 12 lines per frame. Each memory row (= firmware x)
is read once per frame, at its own moment in the scan, so one frame on the glass mixes what
the memory held over 16.7 ms. This samples the emulated panel memory the same way: one
memory row per line time. Animations therefore show their real frame steps and torn frames,
not just the finished screens.

MADCTL is 0x90 (MY=1, ML=1). The default reading: memory row 0 is refreshed first, so the
scan runs along firmware x from 0 to 319. --scan down reverses it. This is inferred from the
init sequence and not yet confirmed on the glass. The video uses firmware coordinates, like
the emulator PNGs.

Writes OUT_60fps.mp4 (real time) and OUT_slow4x.mp4 (the same frames at 15 fps). Needs
ffmpeg on the PATH.

    python3 tools/emu/panel_video.py IMAGE OUT [--scan up|down] [--seconds 5.5]
                                     [--press 0.5:0x0A --press 1.5:0x0A ...]

The amp boots, powers on (USB audio present) and settles for 9 s before the video starts.
Presses are NEC commands at times from the video start; the default is Vol+ at 0.5, 1.5 and
2.3 s, which shows the volume page opening, two redraws and the timeout back home.
"""
import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ao300 import Amp, CLOCK_HZ, NEC_POWER, NEC_VOL_UP  # noqa: E402

FPS = 60
PORCH_BACK, ROWS, PORCH_FRONT = 12, 320, 12
LINES = PORCH_BACK + ROWS + PORCH_FRONT
W, H = 320, 170
COL0 = 0x23                 # first panel column the firmware draws in (firmware y 0)
PANEL_COLS = 240
SCALE = 3


def press_arg(s):
    t, cmd = s.split(":")
    return float(t), int(cmd, 0)


def frame_bytes(cols, lut):
    """cols[x] = 170 RGB565 pixels of firmware column x -> 320x170 RGB24, row-major."""
    out = bytearray(W * H * 3)
    for x in range(W):
        col = cols[x]
        for y in range(H):
            p = col[y]
            c = lut.get(p)
            if c is None:
                c = lut[p] = bytes(((p >> 11) * 255 // 31, ((p >> 5) & 63) * 255 // 63, (p & 31) * 255 // 31))
            i = (y * W + x) * 3
            out[i:i + 3] = c
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image", help="firmware image (.bin)")
    ap.add_argument("out", help="output path prefix")
    ap.add_argument("--scan", choices=("up", "down"), default="up",
                    help="panel refresh order along firmware x (default up: 0 to 319)")
    ap.add_argument("--seconds", type=float, default=5.5, help="video length")
    ap.add_argument("--press", type=press_arg, action="append",
                    help="TIME:NEC press at TIME seconds, e.g. 0.5:0x0A (repeatable)")
    args = ap.parse_args()
    presses = sorted(args.press or [(0.5, NEC_VOL_UP), (1.5, NEC_VOL_UP), (2.3, NEC_VOL_UP)])

    amp = Amp(open(args.image, "rb").read(), log_audio=False)
    amp.set_pin(0xC0, 5, 0)                      # USB audio present
    amp.boot()
    amp.press(NEC_POWER)
    amp.wait(9.0)

    inp = ["-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "%dx%d" % (W, H)]
    outp = ["-vf", "scale=%d:%d:flags=neighbor" % (W * SCALE, H * SCALE), "-pix_fmt", "yuv420p",
            "-c:v", "libx264", "-crf", "12"]

    def ffmpeg(rate, path):
        return subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error"] + inp + ["-r", str(rate), "-i", "-"] +
                                outp + [path], stdin=subprocess.PIPE)
    writers = [ffmpeg(FPS, args.out + "_60fps.mp4"), ffmpeg(FPS // 4, args.out + "_slow4x.mp4")]

    clocks_per_line = CLOCK_HZ / FPS / LINES
    order = range(ROWS) if args.scan == "up" else range(ROWS - 1, -1, -1)
    gram = amp.lcd.gram
    cols = [[0] * H for _ in range(W)]
    lut = {}
    start = amp.e.cycles
    nframes = int(args.seconds * FPS)
    pi = 0
    for f in range(nframes):
        while pi < len(presses) and presses[pi][0] <= f / FPS:
            amp.press(presses[pi][1])
            pi += 1
        frame0 = start + f * CLOCK_HZ / FPS
        for k, r in enumerate(order):
            amp.e.run(None, 1 << 40, stop_cycles=int(frame0 + (PORCH_BACK + k) * clocks_per_line))
            base = r * PANEL_COLS + COL0
            cols[r] = gram[base:base + H]
        amp.e.run(None, 1 << 40, stop_cycles=int(frame0 + LINES * clocks_per_line))
        fb = frame_bytes(cols, lut)
        for w in writers:
            w.stdin.write(fb)
    for w in writers:
        w.stdin.close()
        w.wait()
    print("wrote %s_60fps.mp4 and %s_slow4x.mp4 (%d frames, scan %s)" % (args.out, args.out, nframes, args.scan))


if __name__ == "__main__":
    main()
