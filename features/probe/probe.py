"""Probe: a read-only register dump over the programming header, on one remote command.

The remote's FN button (NEC command 0x08), with the amp on and on the home screen, sends a
text dump at 115200 baud, 8N1, on the header's TXD. Nothing else changes: the command is
swallowed ("no key"), the audio chips are only read, no register is written, and the amp
carries on. In standby or in a menu the command goes to the stock path.

Stock gives a short FN press the Dimmer toggle (key 0x14, 0x10BE) and a long hold "BT
Reconnect" (the decoder turns the tenth repeat into 0x0E). The decoder reports a short press
once, on release (inject_key_08), so the dump runs once per press and never on a repeat.
While this image is flashed the short press on the home screen is the dump instead of the
Dimmer toggle; the Dimmer menu and the long hold are as stock. COMMAND picks the command:
0x16 is the free one next to direct-select's, for a controller that can send any code.

The dump (hex, ASCII, CRLF lines):

    PROBE 1
    SCAN 62 80 B0 C0                 every 8-bit write address that ACKs (start, address, stop)
    B0 00: .. (16 bytes) ..          expander registers 0x00..0x13
    B0 10: .. .. .. ..
    80 20: ..                        digital receiver registers 0x20..0x7F
    C0 00: ..                        clock generator registers 0x00..0xBF
    FS: r0 r1 r2 r3 r4 r5 r6 r7      the receiver's rate calculator (register 0x38) pointed at each
                                     of its ports in turn: DIR, ADC, AUXIN0 (the HDMI receiver's
                                     I2S), AUXIN1 (the XMOS), AUXIN2, main out, AUX out, DIT; bit 7
                                     set = no result within the wait, bits 3:0 the rate code
    P: p0 p1 p2 p3 p4 p5 p7          the MCU ports as read
    R: ..                            RAM: page, input, power, output, EQ, filter, volume, volume hp,
                                     bass, treble, dimmer, format, 0x75, 0x73, 0x76, 0x77, 0x78,
                                     format cfg, format read (RAM_LIST)
    END

Reads go through the stock i2c_read_reg16 (0x4CDF), the scan through the stock bit-bang
primitives. The DAC (0x62) is not read: its registers take a three-byte address and stock has
no read routine for it.

The FS line is the one write this probe makes (pr3, layer 3 item 1 of docs/probing-plan.md):
the receiver's register 0x37 selects which port its sample-rate calculator measures, a
measurement block outside the audio path. pr_fs reads stock's value, points it at ports 0 to
7 in turn, polls 0x38 until the result is for that port (bit 7 clear, bits 6:4 = port, up to
64 reads), and writes stock's value back. Nothing else is written.

UART1: with the amp on, stock keeps UART1 on P3.6/P3.7 (the XMOS line; P3.7 is also the bus
data line). The dump switches P_SW1 to P3.0/P3.1 (the header) for its duration and restores
it, with ES off meanwhile because uart1_isr clears TI, which the sender polls. XMOS bytes
during the dump are lost; the next message repairs the format display. The sender never
writes SBUF while P_SW1 selects P3.6/P3.7.

Hook: read_key's `lcall ir_cmd_to_key` (0x3DA9) becomes `lcall pr_key`; every other command
continues into ir_cmd_to_key (or direct-select's replacement of it) with `ljmp`, so the two
fixes stack. Blocks the main loop for about a second (about 300 bus reads and 1.2 KB of text),
as a stock input switch does.

Other builds list "probe" in INCLUDES and link HOOK and emit(a) through features.fixes
(tools/patch/features.py; README, "Feature graph").
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                                "tools", "patch"))
from uikit import S  # noqa: E402

HOOK = (0x3DA9, bytes([0x12, 0x5D, 0x10]), 0x12, "pr_key")   # read_key: lcall ir_cmd_to_key
XDATA = []                            # none: stack and registers only
COMMAND = 0x08                        # the NEC command: the remote's FN button (0x16: a free code)
IR_CMD_TO_KEY = 0x5D10
I2C_START, I2C_WRITE_BYTE, I2C_READ_ACK, I2C_STOP, I2C_READ_REG16 = 0x5B65, 0x56B9, 0x5339, 0x5C08, 0x4CDF
DELAY_LONG = 0x5D03                   # about 2.5 ms: the last stop bit leaves before the pins switch back
IE, ES_BIT, P_SW1, SBUF, TI_BIT, B = 0xA8, 0xAC, 0xA2, 0x99, 0x99, 0xF0
PORTS = (0x80, 0x90, 0xA0, 0xB0, 0xC0, 0xC8, 0xF8)        # P0 P1 P2 P3 P4 P5 P7
DEVICES = [(0xB0, 0x00, 0x14), (0x80, 0x20, 0x60), (0xC0, 0x00, 0xC0)]   # (address, first register, count)
RAM_LIST = [0x45, 0x47, 0x4F, 0x2B, 0x39, 0x2C, 0x31, 0x52, 0x35, 0x2A, 0x29, 0x3D, 0x75, 0x73, 0x76, 0x77,
            0x78, 0x4E, 0x58]
HEAD, SCAN, PINS, RAM, END, CRLF = "\r\nPROBE 1\r\nSCAN", "", "\r\nP:", "\r\nR:", "\r\nEND\r\n", "\r\n"
FS = "\r\nFS:"
I2C_WRITE_REG = 0x4FAD                # R7 device, R4:R5 register, R3 data
DIR, FS_TARGET, FS_RESULT, FS_PORTS, FS_POLLS = 0x80, 0x37, 0x38, 8, 64


def emit(a):
    S(a, """
; pr_key: replaces read_key's `lcall ir_cmd_to_key` (0x3DA9). The command (FN, 0x08), amp on, home page:
; the dump, then "no key". Anything else: ir_cmd_to_key as stock (tail call, the return goes
; back into read_key).
pr_key:
mov A,0x6A                  ; g_ir_cmd
cjne A,#0x%02X,pr_stock
mov A,0x4F                  ; g_power_on
jz pr_stock
mov A,0x45                  ; g_ui_page
cjne A,#0x01,pr_stock
lcall pr_dump
mov R7,#0xFF                ; "no key", as ir_cmd_to_key returns for a command past its table; the Dimmer toggle is skipped
clr A
mov 0x6F,A                  ; g_ir_key2: ir_cmd_to_key's side effect
ret
pr_stock:
ljmp 0x%04X                 ; ir_cmd_to_key

; pr_dump: the whole dump on UART1 moved to the header pins. ES off meanwhile (uart1_isr
; clears TI). Registers: R0 device, R1 register, B count; the stock I2C routines use R2..R7.
pr_dump:
push 0x%02X                 ; IE
clr 0x%02X                  ; ES
push 0x%02X                 ; P_SW1
mov A,0x%02X
anl A,#0x3F                 ; S1_S = 00: UART1 on P3.0/P3.1, the header
mov 0x%02X,A
mov DPTR,#pr_s_head
lcall pr_str
mov R0,#0x02                ; scan: every write address but the general call
pr_scan:
lcall 0x%04X                ; i2c_start
mov A,R0
mov R7,A
lcall 0x%04X                ; i2c_write_byte
lcall 0x%04X                ; i2c_read_ack: R7 = 1 on ACK
mov A,R7
push ACC
lcall 0x%04X                ; i2c_stop
pop ACC
jz pr_scan_next
mov A,R0
lcall pr_sp_hex
pr_scan_next:
inc R0
inc R0
mov A,R0
jnz pr_scan                 ; 0xFE + 2 wraps to 0
""" % (COMMAND, IR_CMD_TO_KEY, IE, ES_BIT, P_SW1, P_SW1, P_SW1, I2C_START, I2C_WRITE_BYTE, I2C_READ_ACK, I2C_STOP))
    for dev, first, count in DEVICES:
        S(a, """
mov R0,#0x%02X
mov R1,#0x%02X
mov 0x%02X,#0x%02X          ; B: register count
lcall pr_regs
""" % (dev, first, B, count))
    S(a, """
lcall pr_fs
mov DPTR,#pr_s_pins
lcall pr_str
""")
    for port in PORTS:
        S(a, "mov A,0x%02X\nlcall pr_sp_hex" % port)
    S(a, """
mov DPTR,#pr_s_ram
lcall pr_str
mov DPTR,#pr_ramlist
mov R1,#%d
pr_ram:
clr A
movc A,@A+DPTR
mov R0,A
inc DPTR
""" % len(RAM_LIST))
    a.i("mov A,@R0", 0xE6)
    S(a, """
push DPH
push DPL
lcall pr_sp_hex
pop DPL
pop DPH
djnz R1,pr_ram
mov DPTR,#pr_s_end
lcall pr_str
lcall 0x%04X                ; delay_long: the last stop bit leaves
pop 0x%02X                  ; P_SW1 back (P3.6/P3.7 while the amp is on)
pop 0x%02X                  ; IE back: ES on again
ret

; pr_fs: the receiver's rate calculator on each port. Stock's target (0x37) saved on the stack
; and restored; per port: write the target, poll 0x38 until bit 7 is clear and bits 6:4 name
; that port (a result left from the previous port is skipped), at most FS_POLLS reads; print
; the last value read. R0 port, B poll counter; i2c_write_reg uses R1, R2, R4, R7.
pr_fs:
mov DPTR,#pr_s_fs
lcall pr_str
mov R7,#0x80              ; receiver
mov R4,#0x00
mov R5,#0x37              ; calculator target
lcall 0x4CDF                ; i2c_read_reg16: stock's target
mov A,R7
push ACC
mov R0,#0x00
pr_fs_port:
mov A,R0
mov R3,A                    ; data: the port
mov R4,#0x00
mov R5,#0x37
mov R7,#0x80
lcall 0x4FAD                ; i2c_write_reg: target = port
mov 0xF0,#64              ; B: polls left
pr_fs_poll:
mov R7,#0x80
mov R4,#0x00
mov R5,#0x38              ; calculator result
lcall 0x4CDF                ; i2c_read_reg16 -> R7
mov A,R7
jb ACC.7,pr_fs_again        ; still calculating
swap A
anl A,#0x07
cjne A,0x00,pr_fs_again     ; a result for another port (R0 is direct 0x00)
sjmp pr_fs_done
pr_fs_again:
djnz 0xF0,pr_fs_poll
pr_fs_done:
mov A,R7
lcall pr_sp_hex
inc R0
cjne R0,#8,pr_fs_port
pop ACC
mov R3,A                    ; stock's target back
mov R4,#0x00
mov R5,#0x37
mov R7,#0x80
ljmp 0x4FAD                 ; i2c_write_reg, then return

; pr_regs: registers R1.. of device R0, B of them, 16 per line, through i2c_read_reg16.
pr_regs:
mov A,R1
anl A,#0x0F
jnz pr_regs_rd
mov DPTR,#pr_s_crlf
lcall pr_str
mov A,R0
lcall pr_hex
mov A,#0x20
lcall pr_tx
mov A,R1
lcall pr_hex
mov A,#0x3A                 ; ':'
lcall pr_tx
pr_regs_rd:
mov A,R1
mov R5,A                    ; register (R4:R5, only R5 is sent)
mov R4,#0x00
mov A,R0
mov R7,A                    ; device
lcall 0x%04X                ; i2c_read_reg16 -> R7 (0 after 5 NACKs)
mov A,R7
lcall pr_sp_hex
inc R1
djnz 0x%02X,pr_regs         ; B
ret

; pr_sp_hex: " " then A in hex. pr_hex: A in hex. pr_nib: low nibble of A as one digit.
; pr_tx: A on UART1, waits for TI (ES is off). pr_str: the string at DPTR until 0.
pr_sp_hex:
push ACC
mov A,#0x20
lcall pr_tx
pop ACC
pr_hex:
push ACC
swap A
anl A,#0x0F
lcall pr_nib
pop ACC
anl A,#0x0F
pr_nib:
mov DPTR,#pr_hexdigits
movc A,@A+DPTR
pr_tx:
mov 0x%02X,A                ; SBUF
pr_tx_wait:
jnb 0x%02X,pr_tx_wait       ; TI
clr 0x%02X
ret
pr_str:
clr A
movc A,@A+DPTR
jz pr_str_done
inc DPTR
lcall pr_tx
sjmp pr_str
pr_str_done:
ret
""" % (DELAY_LONG, P_SW1, IE, I2C_READ_REG16, B, SBUF, TI_BIT, TI_BIT))
    a.L("pr_hexdigits")
    a.data('db "0123456789ABCDEF"', b"0123456789ABCDEF")
    for name, text in (("pr_s_head", HEAD), ("pr_s_fs", FS), ("pr_s_pins", PINS), ("pr_s_ram", RAM),
                       ("pr_s_end", END), ("pr_s_crlf", CRLF)):
        a.L(name)
        a.data("db %r, 0" % text, text.encode("ascii") + b"\0")
    a.L("pr_ramlist")
    a.data("db " + ", ".join("0x%02X" % x for x in RAM_LIST), bytes(RAM_LIST))
