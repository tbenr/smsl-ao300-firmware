"""Fix: a volume key on Optical or Coaxial without a signal leaves the audio hardware alone.

Stock v1.4: with nothing playing on Optical or Coaxial (receiver lock P4.2 high) the amp is
muted by register only (NJW1194 mute code, DAC mute); the pins stay as they were while it
played. The head of each volume key then sets P2.5 low and P2.7 and P2.2 high, and the tail
writes the real volume to the NJW1194, which the main loop mutes again one tick later. On
the amp the first key after the signal went, or after Source reached the input, pops; later
keys find the pins already there (confirmed on the amp 2026-10-02: the pop, and that Coaxial
right after Optical is silent). With the mute key on, the head instead runs unmute_now: P2.2
low and the DAC unmuted for a tick, with no signal.

The fix: without lock a volume key only clears the mute key's flag, changes the number and
draws it. The unmute that follows the signal applies the volume from RAM as it always did
(audio_apply_mute, 0x58EB). With lock, and on the other inputs, the keys are stock.

Other builds list "fix-volume-pop" in INCLUDES and link HOOK, PATCHES and emit(a) through
features.fixes(INCLUDES) (tools/patch/features.py; docs/development.md, "Feature graph").
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "tools", "patch"))
from uikit import S  # noqa: E402

VOLUME_KEYS = (0x0D03, 0x0D83, 0x0E2A, 0x0ED2)   # key_volume_up, _up2, _down4, _down
HEAD_OFFSET = 0x0C                    # each handler: mov R7,0x47 / input 3 or 2 -> here, else to its mute-flag test
# The head on Optical and Coaxial, the same bytes in all four handlers (at 0x0D0F in key_volume_up):
#   jb 0x22.1,+0x10 (unmute_now) / jb P4.2,+2 (pins) / sjmp +0x0B (unmute_now) / clr P2.5 / setb P2.7 / setb P2.2 / sjmp +6
# becomes
#   jnb P4.2,+0x10 (lock: unmute_now, as stock with or without the mute key) / clr 0x22.1 / sjmp +0x0F (past unmute_now)
# The nine bytes after it (the rest of the old branch and the pin writes) are no longer reached.
HEAD_STOCK = bytes([0x20, 0x11, 0x10, 0x20, 0xC2, 0x02, 0x80])
HEAD_FIXED = bytes([0x30, 0xC2, 0x10, 0xC2, 0x11, 0x80, 0x0F])
PATCHES = [(entry + HEAD_OFFSET, HEAD_STOCK, HEAD_FIXED,
            "volume key 0x%04X on Optical/Coaxial: no lock -> clear the mute flag only" % entry)
           for entry in VOLUME_KEYS]

# vol_key_tail's `lcall volume_apply` becomes `lcall vp_apply`
HOOK = (0x0F4A, bytes([0x12, 0x4D, 0xDC]), 0x12, "vp_apply")
XDATA = []                            # XDATA the fix uses: none (stock RAM 0x47, 0x21.4, 0x43:0x44 only)


def emit(a):
    S(a, """
; vp_apply: replaces vol_key_tail's `lcall volume_apply` (0x0F4A; R7 = g_volume), the one write
; of the volume to the NJW1194 that all four volume keys share. On Optical and Coaxial without
; lock the chip keeps its mute code; on any other input, and with lock, this is volume_apply.
; Skipping the write also raises the re-mute request with its 1 s countdown, as Timer0 does when
; it sees no lock (t0_remute_no_lock, 0x3EA4). The head and Timer0 sample P4.2 on their own: if
; only this test saw it high, the volume would stay unwritten. With the request up, the main
; loop mutes and the unmute that follows writes the volume from RAM.
vp_apply:
mov A,0x47                  ; g_input
add A,#0xFE                 ; input - 2
jz vp_digital               ; 2 Optical
dec A
jnz vp_go                   ; not 3 Coaxial either
vp_digital:
jnb 0xC2,vp_go              ; P4.2 low: lock
setb 0x0C                   ; 0x21.4: re-mute request, served by main_tick_tasks
mov 0x43,#0x00              ; g_mute_timer = 100 ticks
mov 0x44,#0x64
ret                         ; no signal: the number changes, the chip does not
vp_go:
ljmp 0x4DDC                 ; volume_apply, returns to the tail
""")
