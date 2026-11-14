# Bus and pin map of the stock firmware

What the control MCU writes and reads outside itself, taken from the stock v1.4 image in
two ways:

- **Trace**: the whole firmware run in the emulator with an I2C slave model
  (`tools/emu/i2c.py`), through power-on, every input, every setting and standby.
  `python3 tools/emu/bus_trace.py --steps` reproduces it.
- **Static**: every call site of the bus routines and every port-pin instruction in the
  disassembly.

The trace and static sections were not measured on the amp (traced 2026-10-01); "Hardware
read-back" and "Layer 3, item 1" below were, on 2026-10-05. Register and bit values are what
the firmware sends. Chip identities and the roles of pins are inferred from them, and are
marked as such. Register names come from the chips' datasheets as remembered and need a
check against the documents before a patch relies on a bit that stock never sets.

## Bus routines

Two buses share P3.7 (data) and P4.1 (clock). All I2C traffic goes through five bit-bang
primitives and three routines built on them:

| Address | Name | Use |
|---|---|---|
| 0x5B65 | `i2c_start` | also the repeated start |
| 0x56B9 | `i2c_write_byte` | R7, MSB first, waits while the clock is held low |
| 0x5339 | `i2c_read_ack` | R7 = 1 on ACK; gives up after 255 samples |
| 0x579C | `i2c_read_byte` | returns R7; the master sends no ACK or NACK clock after it |
| 0x5C08 | `i2c_stop` | |
| 0x4CDF | `i2c_read_reg16` | R7 device, R4:R5 register (only R5 is sent), one byte back, 5 tries |
| 0x4FAD | `i2c_write_reg` | R7 device, R4:R5 register (only R5 is sent), R3 data, 5 tries |
| 0x4D8A | `dac_write` | device 0x62: three address bytes (R7, R5, R3), control byte XDATA 3, data XDATA 4, 5 tries |

The firmware only ever reads the expander and the digital receiver (10 call sites of
`i2c_read_reg16`). The DAC and the clock generator are written blind, so stock never
checks that they are there.

## I2C devices

| Address (8-bit) | Chip | Written | Read |
|---|---|---|---|
| 0xB0 | AW9523B expander (register set matches: 0x7F reset, 0x11 control, 0x12/0x13 mode) | 0x02, 0x03 outputs; setup once | 0x00, 0x01 inputs |
| 0x80 | PCM9211 digital receiver | setup once, five registers per input | 0x38, 0x39 |
| 0xC0 | clock generator, Si5351 register layout | one table at power-on | never |
| 0x62 | CS43131 DAC | setup after every reset, mode, filter, mute | never |

The expander routines can address four chips (0xB0, 0xB2, 0xB4, 0xB6, pin ids 0x10 to
0x4F), but every call uses the first one. There is one expander, not four.

### Clock generator (0xC0), new

`clkgen_load` (0x5089) sends the 43 entries of the table at 0x92C6 (16-bit register, value)
in `audio_chips_init`, once per power-on. The register list is exactly what the Si5351
configuration tool exports. Decoded: PLL A multiplies the reference by 36, output divider 0
divides by 18, only output 0 is on (8 mA), outputs 1 to 7 are powered down. Output 0 is
therefore twice the reference frequency and never changes. Which crystal feeds it and
where the output goes is not known; a board photo of the chip would settle both.

### Expander (0xB0)

Setup in `expander_init`: reset, all pins GPIO, port 0 push-pull, directions 0x6E and 0x30
(1 is input). Pin ids are 0x10 + port 0 bit, 0x18 + port 1 bit.

| Pin | Id | Direction | What the firmware does with it | Role (inferred) |
|---|---|---|---|---|
| P0_0 | 0x10 | out | low on every input switch; on Bluetooth high 2 s later; remote command 0x0E on Bluetooth ("BT Reconnect") pulses it low for 0.3 s | Bluetooth module enable or reset |
| P0_1, P0_2, P0_3 | 0x11 to 0x13 | in | read on every main-loop pass while on Bluetooth | Bluetooth status, feed the status line |
| P0_4 | 0x14 | out | high from power-on; low pulse of about 0.2 s by "BT list clear" | Bluetooth module's clear-pairings line |
| P0_5 | 0x15 | in | signal present, Bluetooth | |
| P0_6 | 0x16 | in | never read | unknown |
| P0_7 | 0x17 | out | set low at power-on, never changed | unknown |
| P1_0 | 0x18 | out | high only on HDMI | HDMI path select |
| P1_1 to P1_3, P1_6, P1_7 | 0x19 to 0x1B, 0x1E, 0x1F | out | low, never changed | unused by the firmware |
| P1_4 | 0x1C | in | signal present, HDMI | |
| P1_5 | 0x1D | in | read with the format poll on USB, optical, coaxial | USB detect |

### Digital receiver (0x80)

`dir_init` (0x3B35) writes registers 0x20 to 0x24, 0x26, 0x27, 0x2F to 0x33, 0x37, 0x40
(twice: 0x33, then 0xC0), 0x60 to 0x62, 0x6A, 0x6D, 0x6F. `input_set_hw` then sets five per input (table
below). Reads: 0x39, low nibble, about every 100 ms on optical, coaxial and Bluetooth (codes 7 to
15 select the rate text of the status line); 0x38, low nibble, on Bluetooth (0 means no
stream and holds the mute).

### DAC (0x62)

Reset is the MCU pin P3.4, held low for 0.5 s; `dac_init` (0x1CE5) does it before every
setup. A format change runs it again, which includes most input switches. Registers
written, by block:

| Registers | Block (datasheet names to be checked) | Written |
|---|---|---|
| 0x010006, 0x01000B to 0x01000D, 0x01002C | clocking, serial-port sample rate and width (0x01002C not identified) | init; per mode |
| 0x020000 | power-down control | init sequence |
| 0x030001 to 0x03001B | PLL | only on HDMI (`dac_hdmi_setup`, 0x14E4): the DAC locks its PLL to the HDMI clock |
| 0x040002 to 0x040019, 0x050000 to 0x05000B | serial port format | init |
| 0x070000 to 0x070006 | DSD path, DSD volume | init; 0x070002 and 0x070004 change with the mode |
| 0x080000 | headphone output control | init (0x31) |
| 0x090000 | PCM filter option | the Filter menu, see below |
| 0x090001, 0x090002 | PCM volume B and A | init, both 0x00, never changed |
| 0x090003 | PCM path control 1 | mute: 0xA3 muted, 0xA0 playing (`dac_mute_reg_by_signal`) |
| 0x090004 | PCM path control 2 | init, 0x00 |
| 0x0B0000, 0x0F0010 | class H, interrupt mask | init |

**Filter menu** (`dac_set_filter`, 0x4ECD, called through `filter_apply` 0x5BB8 with the
setting in RAM 0x2C):

| Setting | Menu text | Register 0x090000 |
|---|---|---|
| 1 | FAST+LLatency | 0x02 |
| 2 | FAST+PhComp | 0x42 |
| 3 | SLOW+LLatency | 0x82 |
| 4 | SLOW+PhComp | 0xC2 |
| 5 | NON+Sampling | 0xE2 |

Bit 7 is slow roll-off, bit 6 phase compensation, bit 5 non-oversampling. Bit 1 is set in
all five and bit 0 in none: by the datasheet these are the high-pass filter and
de-emphasis.

## NJW1194 (3-wire, write-only)

| Select byte | Function | Values stock sends |
|---|---|---|
| 0x00, 0x10 | volume, one word per channel (to be checked in the datasheet) | always the same code to both, in speaker and headphone mode (table 0x9289); 0xFF is mute |
| 0x20 | input selector | 0x0C on the five digital inputs, 0x04 on AUX |
| 0x30 | treble | see EQ |
| 0x40 | bass | see EQ |

EQ presets (`eq_apply`, 0x48B2, setting in RAM 0x39). It calls `tone_write` (0x4837) with a
level 0 to 18, where 9 is flat, so the firmware's range is -9 to +9 dB. Tone byte: bit 7
boost, bits 6 to 3 level in dB, bit 2 tone circuit on.

| Setting | Name | Bass | Treble |
|---|---|---|---|
| 1 | Direct | not sent | 0x00, tone circuit bypassed |
| 2 | Tone | the user's Bass value | the user's Treble value |
| 3 | SDB | 0xAC, +5 dB | 0xA4, +4 dB |
| 4 | Bass | 0xA4, +4 dB | 0x04, 0 dB |
| 5 | Super Bass | 0xB4, +6 dB | 0x8C, +1 dB |
| 6 | Rock | 0x9C, +3 dB | 0x94, +2 dB |
| 7 | Soft | 0x94, +2 dB | 0x8C, +1 dB |
| 8 | Clear | 0x0C, -1 dB | 0x0C, -1 dB |

## Per input (`input_set_hw`, 0x24D6)

| Input | NJW selector | P0.1 | P0.2 | P4.6 | P2.4 | Expander P1_0 | Receiver 0x34 | 0x37 | 0x42 | 0x6B | 0x6C | DAC clocking |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 USB | 0x0C | 0 | 0 | 0 | 1 | 0 | 03 | 00 | 02 | 44 | 44 | normal |
| 2 Optical | 0x0C | 1 | 1 | 1 | 1 | 0 | 02 | 00 | 02 | 44 | 11 | normal |
| 3 Coaxial | 0x0C | 1 | 1 | 1 | 1 | 0 | 01 | 00 | 02 | 44 | 11 | normal |
| 4 Bluetooth | 0x0C | 0 | 1 | 1 | 1 | 0 | 00 | 00 | 02 | 00 | 00 | normal |
| 5 HDMI | 0x0C | kept | kept | kept | 0 | 1 | 03 | 05 | 10 | 33 | 00 | PLL (`dac_hdmi_setup`) |
| 6 AUX | 0x04 | 0 | 0 | 0 | 1 | 0 | 03 | 00 | 02 | 44 | 44 | as left by the last input |

"kept": the HDMI branch does not touch that pin.

## MCU pins

Modes from `port_init` (0x45CE): P0, P1, P2 push-pull; P3.4 and P3.5 push-pull, the rest of
P3 quasi-bidirectional; P4.0, P4.1, P4.4, P4.6 push-pull, P4.3 open-drain, the rest of P4
quasi-bidirectional; P5 quasi-bidirectional.

| Pin | Direction | What the firmware does | Role (inferred where not already known) |
|---|---|---|---|
| P0.0, P4.0 | out | high first thing at power-on, low in standby | supply enables |
| P0.1 | out | per input | S/PDIF source enable (optical, coaxial) |
| P0.2, P4.6 | out | per input; P0.2 also high in standby | I2S source mux |
| P0.3, P0.5, P0.7, P1 | out | LCD D/C, WR, CS, data | |
| P0.4 | out | low in standby, high 0.4 s after power-on | LCD reset |
| P0.6 | out | backlight | |
| P2.0 | out | NJW1194 latch | |
| P2.1 | out | low for 0.1 s in `audio_chips_init`, with P4.3 | a chip reset |
| P2.2 | out | high while muted and in headphone mode | speaker amplifier mute |
| P2.4 | out | low only on HDMI | I2S source mux |
| P2.5 | out | high in headphone mode, low on mute | headphone output enable |
| P2.6 | in | read by the Timer0 handler (`t0_hold_mute_p26`) | a sense input used for the headphone mute |
| P2.7 | out | high in headphone mode | speaker/headphone switch |
| P3.0, P3.1 | UART1 | only in standby | the serial update port (`docs/hardware.md`) |
| P3.2 | INT0 | IR receiver | |
| P3.3 | INT1 | on USB, optical, coaxial: re-mute, unmute after 0.3 s, format read again (`int1_isr`) | a stream-change line from the XMOS or the receiver |
| P3.4 | out | low for 0.5 s before each DAC setup | DAC reset |
| P3.6 | UART1 RxD_2 | only while the amp is on | XMOS status messages |
| P3.7, P4.1 | bus | data, clock | |
| P4.2 | in | low is lock | receiver lock |
| P4.3 | out, open-drain | low for 0.1 s in `audio_chips_init`, and for 10 ms on a switch to USB (0x5D66) | a reset, probably the XMOS |
| P4.4 | out | high just before the audio chips are set up, low in standby | audio supply enable |
| P4.5 | in | USB activity | |
| P4.7, P5.4, P5.5, P7.4 | in | front panel | |
| P2.3, P3.5, P5.0 to P5.3 | | never written or read after `port_init` | not used by the firmware |

The volume keys also write the mute pins. On Optical and Coaxial without lock (P4.2 high) the
amp is muted by register only and P2.2, P2.5 and P2.7 stay as they were while it played; the
head of each volume key then sets P2.5 low and P2.7 and P2.2 high (0x0D17 in `key_volume_up`,
the same in the other three), whichever output is active. So P2.7 high is not only "headphone
mode". On the amp the first such key pops (2026-10-02); `features/fix-volume-pop` takes the
pin writes out.

An input chosen in the menu takes another path than the Source key. `input_menu_select`
(0x588B) mutes the NJW1194 and the DAC by register, sets P4.0 low and returns home; 300 main
ticks later (0x3375) the main loop sets P4.0 high and runs `expander_init` and
`audio_chips_init` again: the resets on P4.3 and P2.1, the clock generator, the receiver, the
DAC reset on P3.4, and the unmute. P2.2 is not set until the end of that (high for 75 ms just
before the unmute), and on inputs 1 to 5 the format poll unmutes the NJW1194 and the DAC about
0.5 s after the key, while P4.0 is still low. A pop is heard on the amp on such a change
(2026-10-02); which of these steps makes it is open. Emulator times, house-numerals on fast-lcd, from the Enter key:
P4.0 low at 0, high at 3.07 s, P4.3 and P2.1 low 3.08 to 3.18 s, P3.4 low 3.20 to 3.71 s, P2.2
high 3.83 s, unmute 3.90 s.

Compared in the emulator for all 30 input pairs with a signal on every input, a direct jump
(direct-select, the Source key's `input_apply`) and the menu's path end with the same MCU
pins, NJW1194 words and I2C registers, with two exceptions. The menu's second `expander_init`
leaves expander P0_4 low (output register 0x02 = 0x00): the power-on code sets it high
afterwards, this path does not. And on AUX the DAC, which AUX does not use, keeps the last
input's mode after a direct jump and has the reset defaults after the menu. So nothing the
firmware configures needs the P4.0 cycle; whether a chip on that supply needs the power
cycle itself cannot be seen from the code. `features/fix-menu-input` replaces the path with
the Source key's steps.

Power-on order (times from the key press, emulator): supply enables, LCD reset released
at 0.4 s, backlight at 1.1 s, logo, P4.4 at 5.2 s, expander setup, resets P4.3 and P2.1,
clock generator, receiver, DAC reset and setup, input routing, tone, filter, volume, and
the speaker unmute (P2.2 low) at 8.5 s.

Power-off order (times from the Power key, emulator): NJW1194 and DAC muted by register at
0, P2.2 high at 1 ms, expander P0_0 low, the screen cleared, P4.4 low (`power_off_audio`,
0x5B0B), then in `standby_enter` P0.0 and P4.0 low 100 ms later and the NJW1194 selector set
to 0x04. P2.7 and P2.5 are not written: on speakers P2.7 stays low through standby, on
headphones it stays high and P2.5 goes low. Stock reaches P4.4 low at 150 ms and P0.0 / P4.0
low at 252 ms; with fast-lcd's clear it is 11 ms and 112 ms. With the mute key on, the supply
enables are the only pins that move.

## UART1

`uart1_init` (0x59ED): 115200 baud, receive only. `standby_power_step` (0x55BC) moves it
with the power state: header pins P3.0/P3.1 in standby, P3.6 (the XMOS) while the amp is
on. The handler (`uart1_isr`, 0x55F2) keeps two bytes: 0xFF ends a message, resets the
index and marks the buffer valid (RAM 0x78 = 0xFF); other bytes go to RAM 0x76, 0x77.

The only reader is `xmos_format_take` (0x408B), called from the format poll on USB,
optical and coaxial: with the buffer valid it copies the two bytes (format class, rate
index 1 to 12) for the format tag and status line. So an XMOS message is `class, rate,
0xFF`.

In standby the handler still runs on the header pins, but nothing reads the buffer there.
There is no service or factory protocol on the header. Bytes sent to the header in
standby would only show up as a wrong format tag on USB until the XMOS sends its next
message. The firmware never transmits; with the amp on, the UART's transmit pin is P3.7,
the bus data line.

## Remote keys cleared up

| NEC command | Key code | Handler | Does |
|---|---|---|---|
| 0x09 | 0x1C | 0x1047 | mute toggle: NJW1194 mute code, DAC mute, P2.2 high |
| 0x08 | 0x14 | 0x10BE | toggles Dimmer between Always ON and Auto OFF |
| 0x0E | 0x0A | 0x106D | on Bluetooth only: "BT Reconnect", pulses expander P0_0 low |
| (combination) | 0x38 | 0x10E1 | "BT list clear" (`bt_list_clear`, 0x3C14): on Bluetooth pulses expander P0_4 low, else "It's not BT!" |

## Hardware read-back (2026-10-05)

The first probe dump (`features/probe`, pr2) from the amp, on Optical with no stream, speakers,
volume 20, straight after a power-on. Kept outside the repository.

- **The scan finds exactly the four chips: 0x62, 0x80, 0xB0, 0xC0.** Nothing else answers on
  the bus.
- **Every register stock writes reads back as written**: 74 registers of the expander, the
  receiver and the clock generator, compared against the emulator trace.
- **Expander**: ID register 0x10 reads 0x23, the AW9523B's. Inputs at that moment: P0_1,
  P0_4, P0_5, P0_6 and P1_4, P1_5 high; P0_2, P0_3 low.
- **Receiver**: register 0x38 (fs calculator) 0x00 and 0x39 (biphase information) 0x80, no
  stream on the optical input; the undocumented-here registers read 0x25 = 01, 0x28 = 03,
  0x29 = 0C, 0x2A/0x2B = FF, 0x35/0x36 = 02, 0x41 = FF, 0x46/0x47 = D7, 0x6E = 0F, 0x78 = 3D,
  0x7D = 10, 0x7E = 06.
- **Clock generator**: register 0 reads 0x71. By the Si5351 datasheet that is SYS_INIT 0,
  LOL_B 1, LOL_A 1, LOS_CLKIN 1, LOS_XTAL 0, revision 1: a crystal is present and PLL A,
  the one the table programs, reports loss of lock. Register 1 (sticky flags, never cleared)
  reads 0xF8. Open: whether the part is a Si5351A or a clone with other status semantics, and
  whether output 0 is running. Registers 0xB0 to 0xBB read FF 0C 00 00 00 30 1E 12 60 60 B8 02.
- **Ports**: P0 FF, P1 00, P2 5B (P2.2, P2.5, P2.7 low: speakers, unmuted), P3 FF, P4 DF
  (P4.5 low, P4.2 high), P5 30, P7 00.
- **RAM**: page 1, input 2, powered, speakers, EQ 1, filter 1, volumes 20, bass and treble 9
  (flat), dimmer 1, format 1, XMOS bytes 01 00 with the buffer valid, format code 0x2C.

Polarity of the presence inputs, from `signal_present_update` (0x5232): USB present when P4.5
is low; optical, coaxial and AUX when P4.2 is low; Bluetooth when expander P0_5 is high; HDMI
when expander P1_4 is high. In this dump, taken on Optical with no stream, the optical lock
read "absent" and the USB, Bluetooth and HDMI lines all read "present". Stock only evaluates
the line of the selected input, so those three readings may be the idle levels of inputs
that are not selected (a receiver held off, a module not enabled) rather than sources. Only
dumps with each source switched off and on can tell.

**Second dump, HDMI (ARC) selected, TV off.** Against the first:

- The receiver's five per-input registers read as the routing table says for HDMI (0x34 =
  03, 0x37 = 05, 0x42 = 10, 0x6B = 33, 0x6C = 00), expander P1_0 reads high, P2.4 low.
- Receiver register 0x38 reads 0x58 (0x00 on Optical without a stream); 0x7D and 0x7E
  changed too (10 06 to 00 02).
- Expander P1_4, the HDMI presence line, still reads high with the TV off.
- **The clock generator's status went from 0x71 to 0x51: PLL A reports lock on HDMI and
  loss of lock on Optical without a stream.** So its reference is not a free-running
  crystal of its own; it moves with the input, which points at a clock from the receiver
  (register 0x37 is the one the routing changes along with it). Which clock, and what
  output 0 feeds, is still open.

**Third dump, HDMI selected, TV on and sending audio over ARC.** Against the second, one
byte differs: receiver register 0x7D reads 0x50 (0x00 with the TV in standby). The HDMI presence line P1_4, the clock
generator's status, the ports and the RAM are the same. So between the TV off and on, with
HDMI selected, the expander line the firmware polls for HDMI does not move. The user saw the
status line say "Digital Input" in both states, with a brief "Disconnected" around the
moment the TV came out of standby: the TV keeps the ARC link up in standby, the line
follows the link and dropped only while it renegotiated. So P1_4 high is "link present",
not "audio playing"; register 0x7D is the one byte that moved between the link idle and
audio arriving.

**Fourth dump, HDMI selected, TV on and muted.** Receiver 0x7D reads 0x10 and 0x7E 0x00. The
three HDMI states, same routing, everything else in the dump identical:

| TV | 0x7D | 0x7E |
|---|---|---|
| standby, link up | 00 | 02 |
| on, muted | 10 | 00 |
| on, audio over ARC | 50 | 02 |

So with HDMI selected, bit 4 of 0x7D says the TV is awake and bit 6 says audio is flowing,
which is what an auto-switch needs. Not yet known: whether 0x7D still reflects ARC while
another input is selected, since the routing registers (0x34, 0x37, 0x42, 0x6B, 0x6C)
change per input and the first dump, on Optical, read 0x7D = 10 and 0x7E = 06 with no
optical stream. Dumps on Optical with the TV muted and playing would tell.

**Fifth dump, Optical selected, no optical stream, TV on and muted.** Against the first
(Optical, just after a power-on, TV presumably in standby): receiver 0x38 reads 0x80 (was
00), 0x7D 00 (was 10), 0x7E 00 (was 06), and the firmware's format code (RAM 0x4E, 0x58)
reads 0xE1 (was 0x2C). The two dumps differ in more than the TV's state (time since
power-on), so this pair alone does not say whether 0x7D follows ARC on Optical; the sixth
dump, same state with the TV playing, is the comparison that does.

**Sixth dump, Optical selected, no optical stream, TV playing over ARC.** Against the fifth,
the firmware's state is identical and the receiver differs in three registers: 0x7D reads
0x60 (was 00), 0x7E 06 (was 00), 0x38 00 (was 80). Register 0x7D over all six dumps:

| Selected | TV | 0x7D | 0x7E |
|---|---|---|---|
| HDMI | standby, link up | 00 | 02 |
| HDMI | on, muted | 10 | 00 |
| HDMI | on, audio | 50 | 02 |
| Optical | just after power-on | 10 | 06 |
| Optical | on, muted | 00 | 00 |
| Optical | on, audio | 60 | 06 |

**Bit 6 of receiver register 0x7D is set exactly when audio is arriving over ARC, with HDMI
selected and with Optical selected.** The firmware never reads it. By the PCM9211 datasheet
(section 8.5.59) register 0x7D is the GPIO input data register for the MPIO_A and MPIO_B
pins, and 0x7E the same for MPIO_C: live pin levels, no reset value. So the bit is a wire on
the board, from the HDMI receiver into one of the PCM9211's multipurpose pins, which the MCU
can only reach through this register. An auto-switch to HDMI can poll it from the main loop
on the other inputs (the format poll already reads the receiver every 100 ms). Register
0x38 is the DIR sample-frequency result; its bit 7 toggled between dumps and is not yet
understood. Which MPIO pin bit 6 is, and what the HDMI receiver drives it with, is for the
board.

**Seventh dump, Optical selected, an optical stream (48 kHz) and ARC audio both playing.**
Against the sixth: receiver 0x38 and 0x39 read 09 (the DIR's 48 kHz code), 0x5C to 0x5E
read 20 02 DB (00 before), 0x7D reads 0x30 and 0x7E 0x04; P3.3 (INT1) reads low and P4.2
(lock) low; the firmware's format code is 0x30; the clock generator's status reads 0x01:
PLL A locked and, for the first time, a signal on its CLKIN input. **Bit 6 of 0x7D read 0
with ARC audio still playing.**

**What the receiver registers are (PCM9211 datasheet, SBAS495D).** With them the 0x7D
story collapses:

| Register | Name | Stock writes | Meaning |
|---|---|---|---|
| 0x34 | DIR input source | 02 Optical, 01 Coaxial, 00 Bluetooth, 03 USB, HDMI, AUX | RXIN2 optical, RXIN1 coaxial (amplifier on), RXIN0 the Bluetooth module's S/PDIF, RXIN3 the HDMI receiver's S/PDIF output, where the DIR is parked on the inputs that do not use it |
| 0x37 | fs calculator target | 00, 05 on HDMI | DIR; on HDMI the main output port |
| 0x38 | fs calculator result | read | bit 7 calculating, bits 6:4 port, bits 3:0 rate code (9 = 48 kHz) |
| 0x39 | incoming biphase info | read | bit 7 "calculating or unlocked", bit 6 non-audio, bits 3:0 rate code |
| 0x5C to 0x5E | DIR channel status bytes 2 to 4 | read | 20 02 DB with the optical stream |
| 0x6B | main output port source | 44 USB, Optical, Coaxial, AUX; 33 HDMI; 00 Bluetooth | clocks and data from AUXIN1 (the XMOS I2S, on MPIO_C), AUXIN0 (the HDMI receiver's I2S) or DIR/ADC automatic |
| 0x6C | AUX output port source | 44 USB, AUX; 11 Optical, Coaxial; 00 HDMI, Bluetooth | AUXIN1, DIR, or automatic |
| 0x6F | MPIO group functions | 48 | MPIO_A: CLKST, VOUT, XMCKO, INT0 outputs; MPIO_B: the AUX output port; MPIO_C: AUXIN1 |
| 0x7D | GPIO input data, MPIO_A and MPIO_B | read | bits 7:4 the AUX output port's clock and data lines, bits 3:0 the MPIO_A outputs, all as pin levels at the instant of the read |

So the HDMI receiver feeds the PCM9211 twice, as the datasheet's jitter-cleaning
arrangement describes: its I2S on AUXIN0 and its S/PDIF on RXIN3. The MCU's INT1 line is
the receiver's INT0 output on MPIO_A, and its lock pin P4.2 is in all likelihood CLKST.
Register 0x7D's upper nibble samples the AUX output port's clock and data lines, which
toggle whenever that port has a source; its values across the seven dumps (00, 10, 50, 10,
00, 60, 30) are snapshots of toggling lines, and the match with the TV's state in dumps two
to six was chance. **No ARC activity indicator was found on Optical.** The deterministic one
is the DIR itself: on USB and AUX the DIR is parked on RXIN3, the HDMI receiver's S/PDIF, so
register 0x39 (bit 7 clear, a rate code) says that ARC audio is arriving, without any
write. On Optical, Coaxial and Bluetooth the DIR carries the selected input; an auto-switch
there would have to move it to RXIN3 while the selected input is unlocked, which is a
register write (layer 3). Still to confirm: a dump on USB with the TV playing, then muted.

**Eighth dump, Coaxial selected, no coaxial stream, TV and optical playing.** The receiver
sits on RXIN1 (0x34 = 01) and reads unlocked (0x39 = 89: bit 7 set, the last rate code
held), 0x38 = 00, channel status bytes 00: the HDMI stream is invisible on an input whose
own S/PDIF is selected, as the model says. The clock generator's status read 0x61.

**The serial port and the USB and AUX inputs.** Every attempt to dump on USB or AUX ended
with the amp's serial port dropping off the host computer (the host itself gets an I/O error
on the device; it comes back on Coaxial). USB and AUX are the two inputs on which the XMOS
path is selected (P0.2 and P4.6 low). The amp has one USB-C socket for both the serial port
and USB audio, so the likeliest cause is that the socket goes to the XMOS whenever those
inputs are selected; what switches it is not known (`docs/open-questions.md`). Not in the
firmware. The USB and AUX dumps are deferred until there is another way to read the serial
port on those inputs.

**Ninth dump, Bluetooth selected, a Bluetooth stream playing.** The receiver sits on RXIN0
(0x34 = 00), locked at 44.1 kHz (0x38 = 08, 0x39 = 08), channel status bytes 04 .. 0B,
output ports automatic (0x6B = 0x6C = 00), lock pin P4.2 low, INT1 high. Expander P0_0
reads high (the module enabled), P0_5 high (signal present), and the three status lines
P0_1, P0_2, P0_3 all low. By `main_tick_tasks` (0x3399) those three make the code in RAM
0x25 as P0_2 * 4 + P0_1 * 2 + P0_3, and `status_bt_text` (0x4F63) names it: 0 SBC, 1 aptX,
2 AAC, 3 aptX HD, 4 LDAC, 5 to 7 LHDC. So the module reports the codec on
three lines, and this stream was SBC. On Optical in the first dump P0_1 read high, a code
the firmware does not evaluate off the Bluetooth input.

**Tenth dump, Bluetooth connected and paused.** Identical to the ninth but for the sampled
port lines (0x7D 30, 0x7E 00): the receiver stays locked at 44.1 kHz, the signal-present
line stays high, the codec lines keep SBC. The module keeps its S/PDIF running with digital
silence while paused, so to the firmware a paused Bluetooth source is a playing one.

**Eleventh dump, Bluetooth input, phone disconnected.** The receiver loses lock (0x39 = 88,
0x38 = 00, channel status bytes 00), the lock pin P4.2 goes high, and expander P0_5, the
Bluetooth signal-present line, goes low; the module's enable line stays high and the codec
lines stay at 0. The clock generator's status reads 0x51 (CLKIN lost, PLL A still reporting
lock). So on Bluetooth the firmware's signal presence is the module's P0_5 line, which
follows the connection, and the receiver's lock follows it too.

**The module is not discoverable while another input is selected** (tried on the amp,
2026-10-05: on Optical the phone could not find the amp). The firmware lowers expander P0_0
on every input switch and raises it only on Bluetooth, two seconds after the switch, so P0_0
is the module's enable: a connected phone drops the moment another input is selected (tried
the same day), so the module is off whenever P0_0 is low. (The connection line reading high
on Optical in the first dumps was then the line's idle level with the module off, not a
link.) A feature that wants Bluetooth activations from other inputs has to keep P0_0 high
while the amp is on.

**Twelfth dump, Coaxial selected, a 44.1 kHz stream playing.** The receiver on RXIN1 locks
(0x38 = 0x39 = 08), channel status bytes 01 .. 02 (a consumer source), the lock pin P4.2
low, INT1 high (it read low during the optical stream), the clock generator's status 0x01
(locked, CLKIN present) as with the optical stream. The firmware's format code reads 0x2C,
which with the optical 48 kHz stream read 0x30: `format_read` turns the receiver's rate
code into these status codes (8 to 0x2C, 9 to 0x30), and 0x2C is also the power-on value.
Coaxial behaves as Optical in every register but the input select.

**Thirteenth dump, headphones plugged in** (same state as the twelfth otherwise). Nothing
changed but the sampled port lines: P2.6 reads high as in every dump, expander P0_6 high as
in every dump, the output setting still speakers. The jack is not sensed by anything the
MCU can read; the speaker/headphone choice is the Output menu only, as the stock UI implies.

## Layer 3, item 1: the receiver's rate calculator on every port (pr3, 2026-10-05)

Probe pr3 adds the FS line: register 0x37 pointed at each of the receiver's eight ports in
turn, register 0x38 read until it names that port, stock's target written back. First dump,
Optical selected with no optical stream, TV playing over ARC, the amp's USB socket connected
to the host computer:

| Port | 0x38 | Reading |
|---|---|---|
| 0 DIR | 00 | out of range: no optical stream |
| 1 ADC | 19 | 48 kHz |
| 2 AUXIN0, the HDMI receiver's I2S | 28 | **44.1 kHz: the TV's ARC audio, seen from Optical** |
| 3 AUXIN1, the XMOS's I2S | 3A | 64 kHz code |
| 4 AUXIN2 (no pins: MPIO_B is the AUX output) | 4A | 64 kHz code |
| 5 main output port (source AUXIN1 on Optical) | 5A | 64 kHz code, as port 3 |
| 6 AUX output port (source DIR, unlocked) | 6A | 64 kHz code |
| 7 DIT | 70 | out of range |

Every port returned a result within the wait. The 64 kHz code on the ports with no real
stream (an idle XMOS, an unlocked DIR, a port without pins) is the calculator's reading of
whatever clock is there, not a stream; the AUXIN0 reading is a real rate.

Second pr3 dump, same state with the TV muted: the HDMI port still reads 28, 44.1 kHz. The
TV keeps its ARC stream running with digital silence while muted, so the calculator sees
the stream's clock, not whether there is sound on it. (Port 4 read 40 instead of 4A: the
idle code wanders.)

Third pr3 dump, same state with the TV in standby: the HDMI port reads A9, bit 7 set, no
result within the 64 polls: no clock on the port. The ports with no stream read 30, 40, 50,
60 this time (rate 0, out of range) where the first dump had the 64 kHz code: the idle
readings wander between "out of range" and the 64 kHz code, the ADC's 48 kHz and the HDMI
port's 44.1 kHz are steady.

**Result.** From Optical, with one register write and no change to the audio path, the
receiver's calculator reports the HDMI port's rate whenever the TV is awake and streaming
(muted or not) and no result when it is in standby. "TV on" is therefore readable from
any input, and an auto-switch to HDMI can rest on it: a valid rate code (8, 9, 0xB, 0xC,
0xE or 0xF) with bit 7 clear on port 2 means the TV is on; anything else, including the
wandering idle codes, means it is not. The same port 3 reading would do for a USB host,
untested while the USB dumps are deferred. The calculator result register is also what
stock reads on Bluetooth, so there the poll must restore the target before stock's read.

The clock generator's CLKIN carries a signal only with an S/PDIF stream on the receiver:
the receiver's recovered clock. Its XTAL input is always present (a crystal, or the
receiver's buffered crystal output). PLL A: locked on HDMI and on Optical with a stream,
unlocked on Optical without one.

## What this opens up

Reachable from MCU code without new hardware, none of it tried:

- **Balance.** The NJW1194 takes a volume code per channel and stock always sends the same
  one to both. It works on every input, AUX included.
- **Custom presets, convenience only.** The presets are constants in `eq_apply`, one bass
  and one treble level each. They add no sound the amp cannot already make: the Treble and
  Bass menus step through all 19 levels, -9 to +9 dB (checked in the emulator), and the Tone
  preset applies them. A changed preset is a named shortcut to one such pair.
- **DAC options stock never sets**: de-emphasis and the high-pass filter (0x090000), the
  per-channel digital volume (0x090001, 0x090002), and whatever 0x090003 and 0x090004 offer
  besides mute. Digital inputs only.
- **Sample rate on every digital input.** The receiver's rate register is already polled.
- **A debug channel.** With the amp on, the header pins are idle, and in standby the
  receive path on them already works.

Still closed: the XMOS, the Bluetooth module's stack, the HDMI receiver, the class-D stage.

The next steps, and the rules for trying any of this on the amp, are in
`docs/probing-plan.md`.
