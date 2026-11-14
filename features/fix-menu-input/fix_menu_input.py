"""Fix: an input chosen in the menu is switched as the Source key switches it.

Stock v1.4: Enter on the menu's INPUT list runs input_menu_select (0x588B). Unlike the Source
key's input_apply (0x5640) it does not set the input's hardware. It mutes by register, sets
P4.0 low (one of the two supply enables) and arms 0x41:0x42 with 300 main ticks; when that
runs out the main loop (0x3375) sets P4.0 high and runs expander_init and audio_chips_init,
the power-on chip setup, which ends in the unmute. The speaker mute pin P2.2 stays low until
the very end, and on inputs 1 to 5 the format poll opens the NJW1194 and the DAC again about
0.5 s after the key. So the supply returns and the chips are reset with the path open, and the
amp pops (heard on the amp 2026-10-02). The second expander_init also leaves expander P0_4 low,
which the power-on code sets high.

The fix: the menu's choice does what the Source key does. It mutes, arms the format poll and
the 2 s unmute countdown and calls input_set_hw; P4.0 stays high and nothing is set up again.
The menu's own handling (page, list state, settings save) is stock's. In the emulator the two
paths end in the same pins, NJW1194 words and I2C registers for all 30 input pairs, apart from
P0_4 and the DAC on AUX (which AUX does not use).

It needs no other feature and none needs it: direct-select calls the stock input_apply, this
calls the stock input_set_hw.

Other builds list "fix-menu-input" in INCLUDES and link HOOK and emit(a) through
features.fixes(INCLUDES) (tools/patch/features.py; docs/development.md, "Feature graph").
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "tools", "patch"))
from uikit import S  # noqa: E402

INPUT_MENU_SELECT = 0x588B            # R7 = input; g_input (0x47) already holds it
# input_menu_select's `lcall audio_apply_mute` becomes `ljmp mi_switch`
HOOK = (0x5892, bytes([0x12, 0x58, 0xD3]), 0x02, "mi_switch")
XDATA = []                            # XDATA the fix uses: none (stock RAM 0x47, 0x43:0x44, 0x4B:0x4C only)
UNMUTE_TICKS = 0x00C8                 # as input_apply arms it (0x5648)
FORMAT_POLL_TICKS = 0x000A            # as input_step arms it (0x5635)


def emit(a):
    S(a, """
; mi_switch: replaces input_menu_select's `lcall audio_apply_mute` (0x5892), reached with 0x22.4
; cleared and the settings save armed, as input_apply is at 0x5645. Do what input_step and
; input_apply do for the Source key: mute, format poll in 10 ticks, unmute countdown 200 ticks,
; input_set_hw. Then rejoin input_menu_select at 0x589D, past its `clr P4.0` and the re-init
; countdown (0x5895..0x589C, no longer reached): page, refresh countdown, clear, list state.
; A jump in and a jump back, so the stack is as deep as in stock when input_set_hw runs, one
; call below the key handler, as on the Source key's path.
mi_switch:
lcall 0x58D3                ; audio_apply_mute: NJW1194 mute code, DAC mute
mov 0x4B,#0x%02X            ; g_format_poll: 10 ticks
mov 0x4C,#0x%02X
mov 0x43,#0x%02X            ; g_mute_timer: 200 ticks, then mute_timer_expired unmutes
mov 0x44,#0x%02X
mov R7,0x47                 ; g_input
lcall 0x24D6                ; input_set_hw: NJW1194 selector, muxes, receiver, DAC clocking
ljmp 0x589D                 ; input_menu_select's tail
""" % (FORMAT_POLL_TICKS >> 8, FORMAT_POLL_TICKS & 0xFF, UNMUTE_TICKS >> 8, UNMUTE_TICKS & 0xFF))
