"""Fix: arm the Dimmer "Auto OFF" screen-off countdown after a power-on.

Stock v1.4 bug, fixed by SMSL in the AO300 PRO V1.2: with Dimmer set to Auto OFF (RAM 0x29 = 2),
post_power_on (0x5585) never loads the screen-off countdown g_screen_off (0x2F:0x30), and
countdown16_dec (0x5A78) does nothing while it is 0, so the backlight stays on until the first
key press. The PRO arms it at the end of its post-power-on routine with the key dispatcher's
own code (0x0BBD): countdown = (dimmer - 1) * 0x01F4, i.e. 500 main ticks (about 6 s).

Other builds list "fix-auto-off" in INCLUDES and link HOOK and emit(a) through
features.fixes(INCLUDES) (tools/patch/features.py; README, "Feature graph").
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "tools", "patch"))
from uikit import S  # noqa: E402

# post_power_on's tail call `ljmp ui_clear_screen` becomes `ljmp fx_auto_off`
HOOK = (0x55B9, bytes([0x02, 0x5D, 0x42]), 0x02, "fx_auto_off")
SCREEN_OFF_TICKS = 0x01F4             # as the key dispatcher arms it for dimmer 2 (0x0BD5)


def emit(a):
    S(a, """
; fx_auto_off: replaces post_power_on's tail `ljmp ui_clear_screen` (0x55B9). With Dimmer on
; Auto OFF, arm the screen-off countdown as a key press would, then take the stock tail call.
; Arming before the jump keeps the stack depth as stock; the countdown is only read by the
; main loop (0x33DB), so the order against ui_clear_screen does not matter.
fx_auto_off:
mov A,0x29                  ; g_dimmer_mode: 1 Always ON, 2 Auto OFF
cjne A,#0x02,fx_ao_done
mov 0x2F,#0x%02X            ; g_screen_off_hi
mov 0x30,#0x%02X            ; g_screen_off_lo
fx_ao_done:
ljmp 0x5D42                 ; ui_clear_screen, the stock tail call
""" % (SCREEN_OFF_TICKS >> 8, SCREEN_OFF_TICKS & 0xFF))
