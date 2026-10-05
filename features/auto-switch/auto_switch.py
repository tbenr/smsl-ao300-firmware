"""Auto-switch, stage 1: go to HDMI when the TV comes on (Bluetooth sensed, not enabled).

docs/probing-plan.md, after the layer 2 and 3 dumps of 2026-10-05. Two sources can be sensed
from any input without touching the audio path:

  * HDMI: the receiver's sample-rate calculator (PCM9211 register 0x37 selects the port it
    measures, 0x38 holds the result) pointed at AUXIN0, the HDMI receiver's I2S. The TV awake,
    muted or playing, gives a rate code; the TV in standby gives no result.
  * Bluetooth: the module's connection line, expander (AW9523B at 0xB0) input P0_5.

Once per 10 ms tick, with the amp on, as_tick runs after stock's signal_monitor. It paces
itself on stock's format-poll countdown (0x4B:0x4C, 10 ticks, inputs 1..5; AUX keeps its own)
so that on Bluetooth, where stock reads 0x38 itself to hold the mute, the target is back on
the DIR before that read:

    countdown 9: write 0x37 = 2 (the HDMI port)          not on HDMI, where stock's own
    countdown 5: read expander port 0 -> bt_raw           target (5, the main port) already
    countdown 2: read 0x38 -> hdmi_raw; write 0x37 = 0    measures the HDMI stream
                 then evaluate.

Evaluation, every 100 ms: a source is "on" when its reading says so (HDMI: bit 7 clear and a
rate code of 8, 9, 0xB, 0xC, 0xE or 0xF, which excludes the wandering idle codes; Bluetooth:
P0_5 high). HOLD consecutive "on" readings make it active; one "off" reading makes it
inactive. The edge inactive -> active is an activation. An activation switches the amp when
the source is in ENABLED, is not the selected input, the amp shows the home page, and the
selected input is silent (USB: P4.5 high; Optical, Coaxial: P4.2 high, no lock; Bluetooth:
P0_5 low; HDMI: no rate on the main port; AUX: always). The switch is direct-select's: g_input,
the OSD timer, input_apply, so it looks and sounds like a Source press. For the first HOLD
evaluations after a power-on no activation counts, so a TV that is already on does not pull
the amp to HDMI at every power-on. An activation that finds the selected input playing is
dropped (stage 1: no "steal", no deferred switch).

Hook: main_tick_tasks' `lcall signal_monitor` (0x3438), on the tick path only, after the
format poll. State in XDATA 0x01D0..0x01D6. Stage 2 (Optical and Coaxial through a receiver
scan) and stage 3 (a menu with a per-source mask) are not here; ENABLED and HOLD are build-time.

Other builds list "auto-switch" in INCLUDES and link HOOK and emit(a) through features.fixes
(tools/patch/features.py; README, "Feature graph").
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "tools", "patch"))
from uikit import S  # noqa: E402

HDMI, BLUETOOTH = 5, 4                # input numbers (g_input 0x47)
ENABLED = (HDMI,)                     # sources an activation may switch to. Bluetooth is sensed (for the "is it
                                      # playing" check) but off the list: the module is off whenever another input
                                      # is selected (expander P0_0), so a phone cannot connect, and keeping the module
                                      # on would let phones reconnect on their own, which the user does not want
HOLD = 10                             # consecutive 100 ms "on" readings before a source counts as active

HOOK = (0x3438, bytes([0x12, 0x54, 0x63]), 0x12, "as_tick")   # main_tick_tasks: lcall signal_monitor
SIGNAL_MONITOR, INPUT_APPLY = 0x5463, 0x5640
I2C_READ_REG16, I2C_WRITE_REG = 0x4CDF, 0x4FAD
RECEIVER, FS_TARGET, FS_RESULT, HDMI_PORT = 0x80, 0x37, 0x38, 2
EXPANDER, EXP_INPUT0, BT_LINE_BIT = 0xB0, 0x00, 5
SET_PHASE, BT_PHASE, READ_PHASE = 9, 5, 2    # countdown values the steps run at

X_PHASE, X_HDMI_RAW, X_BT_RAW, X_HDMI_CNT, X_BT_CNT, X_ACTIVE, X_ARMED = range(0x01D0, 0x01D7)
XDATA = [(0x01D0, 0x01D7, "auto-switch: phase (AUX), raw readings, hold counters, active bits, armed")]
ACTIVE_HDMI, ACTIVE_BT = 0x01, 0x02
VALID_RATES = (8, 9, 0xB, 0xC, 0xE, 0xF)   # 44.1, 48, 88.2, 96, 176.4, 192 kHz


def emit(a):
    mask = sum(ACTIVE_HDMI if s == HDMI else ACTIVE_BT for s in ENABLED)
    S(a, """
; as_tick: replaces main_tick_tasks' `lcall signal_monitor` (0x3438), on the 10 ms tick.
; RAM: g_power_on 0x4F, g_input 0x47, g_ui_page 0x45, g_format_poll_lo 0x4C, g_osd_timer 0x27:0x28.
as_tick:
lcall 0x%04X                ; signal_monitor, as stock
mov A,0x4F                  ; g_power_on
jnz as_on
mov DPTR,#0x%04X            ; standby: forget everything (the grace period restarts)
clr A
movx @DPTR,A                ; hdmi count
inc DPTR
movx @DPTR,A                ; bt count
inc DPTR
movx @DPTR,A                ; active bits
inc DPTR
movx @DPTR,A                ; armed
ret
as_on:
mov A,0x47
cjne A,#0x06,as_phase_stock ; AUX: stock's format-poll countdown does not run, keep our own
mov DPTR,#0x%04X            ; phase
movx A,@DPTR
dec A
jnz as_phase_own
mov A,#10
as_phase_own:
movx @DPTR,A
sjmp as_phased
as_phase_stock:
mov A,0x4C                  ; g_format_poll_lo: 10 right after stock's poll, down to 1
as_phased:
mov R0,A                    ; R0 = phase (i2c routines leave R0 alone)
cjne A,#%d,as_not_set
mov A,0x47
cjne A,#0x%02X,as_set_target
ret                         ; HDMI selected: stock's target (the main port) is what we want
as_set_target:
mov R3,#0x%02X              ; the HDMI port
sjmp as_write_target
as_not_set:
cjne A,#%d,as_not_bt
mov R7,#0x%02X              ; expander
mov R4,#0x00
mov R5,#0x%02X              ; input port 0
lcall 0x%04X                ; i2c_read_reg16
mov DPTR,#0x%04X            ; bt raw
mov A,R7
movx @DPTR,A
ret
as_not_bt:
cjne A,#%d,as_done
mov R7,#0x%02X              ; receiver
mov R4,#0x00
mov R5,#0x%02X              ; calculator result
lcall 0x%04X                ; i2c_read_reg16
mov DPTR,#0x%04X            ; hdmi raw
mov A,R7
movx @DPTR,A
mov A,0x47
cjne A,#0x%02X,as_restore
sjmp as_eval                ; HDMI selected: nothing to restore
as_restore:
mov R3,#0x00                ; stock's target on the other inputs: the DIR
lcall as_write_target_call
sjmp as_eval
as_done:
ret
as_write_target:
lcall as_write_target_call
ret
as_write_target_call:
mov R4,#0x00
mov R5,#0x%02X              ; calculator target
mov R7,#0x%02X              ; receiver
ljmp 0x%04X                 ; i2c_write_reg (R3 = data)

; as_eval: once per 100 ms. R6 = new active bits; R7 = edges (inactive -> active).
as_eval:
mov R6,#0x00
mov DPTR,#0x%04X            ; hdmi raw
movx A,@DPTR
jb ACC.7,as_hdmi_off        ; no result
anl A,#0x0F
mov DPTR,#as_rates
movc A,@A+DPTR
jz as_hdmi_off
mov DPTR,#0x%04X            ; hdmi count
movx A,@DPTR
cjne A,#%d,as_hdmi_more
sjmp as_hdmi_on
as_hdmi_more:
inc A
movx @DPTR,A
cjne A,#%d,as_bt
as_hdmi_on:
mov A,R6
orl A,#0x%02X
mov R6,A
sjmp as_bt
as_hdmi_off:
mov DPTR,#0x%04X
clr A
movx @DPTR,A                ; count = 0
as_bt:
mov DPTR,#0x%04X            ; bt raw
movx A,@DPTR
jnb ACC.%d,as_bt_off
mov DPTR,#0x%04X            ; bt count
movx A,@DPTR
cjne A,#%d,as_bt_more
sjmp as_bt_on
as_bt_more:
inc A
movx @DPTR,A
cjne A,#%d,as_edges
as_bt_on:
mov A,R6
orl A,#0x%02X
mov R6,A
sjmp as_edges
as_bt_off:
mov DPTR,#0x%04X
clr A
movx @DPTR,A
as_edges:
mov DPTR,#0x%04X            ; active bits
movx A,@DPTR
cpl A
anl A,R6                    ; A = newly active
mov R7,A
mov A,R6
movx @DPTR,A                ; active = new
mov DPTR,#0x%04X            ; armed: counts the first evaluations after a power-on
movx A,@DPTR
cjne A,#%d,as_arming
sjmp as_armed
as_arming:
inc A
movx @DPTR,A
ret                         ; grace period: no activation counts
as_armed:
mov A,R7
anl A,#0x%02X               ; ENABLED
jz as_no_edge
jb ACC.0,as_to_hdmi
mov R7,#0x%02X              ; Bluetooth
sjmp as_switch
as_to_hdmi:
mov R7,#0x%02X              ; HDMI
as_switch:
mov A,0x45                  ; g_ui_page
cjne A,#0x01,as_no_edge     ; not on the home page
mov A,R7
cjne A,0x47,as_check_silent ; the source is already selected?
as_no_edge:
ret
as_check_silent:
mov A,0x47
cjne A,#0x01,as_sil_2
jnb P4.5,as_no_edge         ; USB: activity low = playing
sjmp as_go
as_sil_2:
cjne A,#0x02,as_sil_3
sjmp as_sil_lock
as_sil_3:
cjne A,#0x03,as_sil_4
as_sil_lock:
jnb P4.2,as_no_edge         ; Optical, Coaxial: lock low = playing
sjmp as_go
as_sil_4:
cjne A,#0x04,as_sil_5
mov DPTR,#0x%04X            ; bt raw
movx A,@DPTR
jb ACC.%d,as_no_edge        ; Bluetooth: connected = playing
sjmp as_go
as_sil_5:
cjne A,#0x05,as_go          ; AUX (6): always silent
mov DPTR,#0x%04X            ; hdmi raw: the main port's rate, stock's own target on HDMI
movx A,@DPTR
jb ACC.7,as_go              ; no result: TV off
anl A,#0x0F
mov DPTR,#as_rates
movc A,@A+DPTR
jnz as_no_edge              ; a rate: the TV is on, HDMI is playing
as_go:
mov A,R7
mov 0x47,A                  ; g_input = the source
mov 0x27,#0x00              ; g_osd_timer, as a Source press
mov 0x28,#0xC8
ljmp 0x%04X                 ; input_apply: switch the hardware, refresh the display
""" % (SIGNAL_MONITOR, X_HDMI_CNT, X_PHASE, SET_PHASE, HDMI, HDMI_PORT, BT_PHASE, EXPANDER, EXP_INPUT0, I2C_READ_REG16,
       X_BT_RAW, READ_PHASE, RECEIVER, FS_RESULT, I2C_READ_REG16, X_HDMI_RAW, HDMI, FS_TARGET, RECEIVER, I2C_WRITE_REG,
       X_HDMI_RAW, X_HDMI_CNT, HOLD, HOLD, ACTIVE_HDMI, X_HDMI_CNT, X_BT_RAW, BT_LINE_BIT, X_BT_CNT, HOLD, HOLD,
       ACTIVE_BT, X_BT_CNT, X_ACTIVE, X_ARMED, HOLD, mask, BLUETOOTH, HDMI, X_BT_RAW, BT_LINE_BIT, X_HDMI_RAW,
       INPUT_APPLY))
    a.L("as_rates")
    a.data("db rate codes 0..15: 1 = a real stream", bytes(1 if r in VALID_RATES else 0 for r in range(16)))
