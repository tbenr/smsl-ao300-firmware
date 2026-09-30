"""Fix: direct input selection over IR (six new NEC commands).

Stock's Source button (NEC command 0x07) only steps to the next input. Six new commands,
sent with the stock remote's address bytes 0x12 0x34, jump straight to one input, so a
home-automation controller can select an input deterministically:

    0x10 -> 1 USB audio     0x11 -> 2 Optical    0x12 -> 3 Coaxial
    0x13 -> 4 Bluetooth     0x14 -> 5 HDMI (ARC) 0x15 -> 6 AUX IN

Mechanism: ir_cmd_to_key (0x5D10) turns the raw NEC command byte (RAM 0x6A) into an internal
key code through a 15-entry table at 0x9398. Raw commands 0x10..0x15 are unused (stock reads
past the table into erased flash -> "no key"). The hook replaces its first 3 bytes with
`ljmp ds_select`. The routine:
  * for 0x10..0x15, only when powered on (RAM 0x4F != 0) and on the home screen (RAM 0x45
    == 1), and only when the target differs from the current input (RAM 0x47): writes the
    input number to 0x47, sets the OSD timer as a Source press does and calls the stock
    "apply input" tail (0x5640: switches the mux, refreshes OSD and LEDs), then returns "no
    key" (R7 = 0xFF) so the dispatcher does nothing else. A command for the input already
    selected is swallowed without the apply: re-applying it re-initialises the source and
    interrupts the audio (ds2);
  * for 0x10..0x15 otherwise (standby, a menu page): "no key";
  * for every other command, the stock table lookup, but only for 0x00..0x0E. Stock read
    erased flash (0xFF = "no key") above the table; the span it can reach (0x9398 + cmd, up
    to 0x9497) holds this fix's code in the standalone image, so the routine refuses those
    commands explicitly instead of reading code bytes as key codes.

Other builds list "direct-select" in INCLUDES and link HOOK and emit(a) through
features.hooks / features.emit (tools/patch/features.py; README, "Feature graph").
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "tools", "patch"))
from uikit import S  # noqa: E402

# ir_cmd_to_key's first instructions `mov R7,0x6A ; mov A,R7` become `ljmp ds_select`
HOOK = (0x5D10, bytes([0xAF, 0x6A, 0xEF]), 0x02, "ds_select")
HOOK_RESUME = 0x5D17          # stock continues here: mov R7,A ; clr A ; mov 0x6F,A ; ret
XDATA = []                    # none: stock RAM only (0x6A, 0x4F, 0x45, 0x47, 0x27:0x28, 0x6F)
TABLE_ADDR = 0x9398           # ir_cmd_to_key_table, 15 entries (commands 0x00..0x0E)
TABLE_LEN = 15
APPLY_TAIL = 0x5640           # input_apply: switch hardware + refresh display
CMD_LO = 0x10                 # first direct command
NINPUTS = 6                   # commands CMD_LO .. CMD_LO + NINPUTS - 1


def emit(a):
    S(a, """
; ds_select: replaces ir_cmd_to_key's entry (0x5D10). Raw NEC command 0x6A -> internal key in R7.
; RAM: g_ir_cmd 0x6A, g_input 0x47, g_power_on 0x4F, g_ui_page 0x45, g_osd_timer 0x27:0x28, g_ir_key2 0x6F
ds_select:
mov A,0x6A                  ; raw NEC command byte
clr C
subb A,#0x%02X              ; A = cmd - 0x10 ; C=1 if cmd < 0x10
jc ds_stock                 ; below range -> stock path
cjne A,#%d,ds_c1            ; never branches; sets C=1 if A < 6
ds_c1:
jnc ds_stock                ; A >= 6 (cmd > 0x15) -> stock path
mov R7,A                    ; R7 = index 0..5
mov A,0x4F                  ; g_power_on
jz ds_eat                   ; standby -> ignore
mov A,0x45                  ; g_ui_page
xrl A,#1                    ; zero iff page == 1 (home)
jnz ds_eat                  ; in a menu -> ignore
mov A,R7
inc A                       ; input number 1..6
cjne A,0x47,ds_apply        ; not the current input -> switch
sjmp ds_eat                 ; already selected -> ignore (no re-init, no OSD)
ds_apply:
mov 0x47,A                  ; g_input = target
mov 0x27,#0x00              ; g_osd_timer: show the input name, as a real press does
mov 0x28,#0xC8
lcall 0x%04X                ; input_apply: switch hardware + refresh display
ds_eat:
mov R7,#0xFF                ; return "no key" to read_key
clr A
mov 0x6F,A                  ; g_ir_key2: stock side effect of ir_cmd_to_key
ret
ds_stock:
mov A,0x6A                  ; replay the displaced stock instructions
cjne A,#%d,ds_c2            ; never branches; sets C=1 if cmd < 15
ds_c2:
jnc ds_eat                  ; cmd >= 15: not in the table -> "no key" (stock read erased flash)
mov DPTR,#0x%04X            ; ir_cmd_to_key_table
movc A,@A+DPTR              ; A = table[cmd]
ljmp 0x%04X                 ; ir_cmd_to_key's tail: mov R7,A ; clr A ; mov 0x6F,A ; ret
""" % (CMD_LO, NINPUTS, APPLY_TAIL, TABLE_LEN, TABLE_ADDR, HOOK_RESUME))
