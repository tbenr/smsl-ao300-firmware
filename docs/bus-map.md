# Bus and pin map of the stock firmware

What the control MCU writes and reads outside itself, taken from the stock v1.4 image in
two ways:

- **Trace**: the whole firmware run in the emulator with an I2C slave model
  (`tools/emu/i2c.py`), through power-on, every input, every setting and standby.
  `python3 tools/emu/bus_trace.py --steps` reproduces it.
- **Static**: every call site of the bus routines and every port-pin instruction in the
  disassembly.

Nothing here was measured on the amp (traced 2026-10-01). Register and bit values are what
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
| P3.0, P3.1 | UART1 | only in standby | the programming header |
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

Power-on order (times from the key press, emulator): supply enables, LCD reset released
at 0.4 s, backlight at 1.1 s, logo, P4.4 at 5.2 s, expander setup, resets P4.3 and P2.1,
clock generator, receiver, DAC reset and setup, input routing, tone, filter, volume, and
the speaker unmute (P2.2 low) at 8.5 s.

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
