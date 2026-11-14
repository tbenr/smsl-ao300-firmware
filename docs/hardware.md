# Hardware and firmware reference

What the control MCU talks to, the volume scale, the memory budget and the facts about the
stock firmware that the patches rely on. Every address refers to the stock v1.4 image
(sha256 `85e8ac50…`). [bus-map.md](bus-map.md) has the register-level detail.

## Hardware map, as seen from the MCU

What the control MCU (STC8C2K64S2) talks to, and how. Chip identities come from the
firmware's bus traffic, silkscreen labels on board photos (ASR thread page 25) and
retailer listings; pin roles come from the code. `docs/bus-map.md` has the full register
and pin tables, from an emulator trace of the stock image (`tools/emu/bus_trace.py`).

Two buses share the pins P3.7 (data) and P4.1 (clock):
- a 3-wire write-only bus with latch P2.0 for the NJW1194;
- a bit-banged I2C master (clock stretching, ACK check) for everything else.

| Subsystem | Chip | MCU interface | Notes |
|---|---|---|---|
| Volume, bass, treble, EQ presets, speaker/headphone volume | NJW1194 analogue volume/tone controller | 3-wire, 16-bit words (0x54EA / 0x54DA): data byte D15..D8, select D7..D4 (0=vol1, 1=vol2, 2=input sel, 3=treble, 4=bass), chip addr D3..D0 | Volume code n = 32 - n/2 dB, 0xFF = mute; steps vs dB in the "Volume scale" section. Tone byte: D15 boost/cut, D14..D11 level 0..10 dB, D10 tone on/off (0x22.4 = bypass) |
| DAC and its filter modes | CS43131 | I2C address 0x62, write-only (`dac_write` 0x4D8A, 5 tries); reset on MCU P3.4 | The five filter menu options are the CS43131's own modes: `dac_set_filter` (0x4ECD) writes register 0x090000 = 0x02, 0x42, 0x82, 0xC2, 0xE2 for settings 1..5. Mute is register 0x090003 (0xA3 / 0xA0). Full register list in `docs/bus-map.md` |
| GPIO expander | one AW9523B (silkscreen RST_AW9523) | I2C address 0xB0; pin ids 0x10..0x1F; register write 0x51AD, write-pin 0x1A7C, read-pin 0x2302, init 0x47BA. The routines can address four chips, but every call uses the first | Four outputs in use: 0x10 and 0x14 to the Bluetooth module, 0x17 (set low once), 0x18 high on HDMI. Six inputs: Bluetooth status and the signal-present lines. The mutes, relays, resets and mux lines are MCU pins. Pin table in `docs/bus-map.md` |
| Clock generator | Si5351 register layout (part not seen) | I2C address 0xC0, write-only; one 43-register table (0x92C6) sent at power-on by `clkgen_load` (0x5089) | Output 0 at twice the reference frequency, the other outputs off, never changed afterwards. Reference and destination unknown |
| Digital interface receiver | TI PCM9211 (fits: I2C 0x80, regs 0x38/0x39, net DIR_RST) | I2C read of sample-rate registers for optical, coax and Bluetooth | Bluetooth audio therefore arrives as SPDIF; lock pin on MCU P4.2 |
| USB audio | XMOS XU-316, own firmware | UART1 receive-only (ISR 0x55F2, `uart1_init` 0x59ED: 115200 baud from Timer2). `standby_power_step` (0x55BC) moves UART1 with the power state through P_SW1: on P3.6 (RxD_2; TxD_2 would be P3.7, the shared bus data pin, so never write SBUF while the amp is on) when powered, back on P3.0/P3.1, the bootloader's serial pins, in standby (pin pairs per the STC8G manual's S1_S table). USB activity on P4.5; USB_DET net | Incoming messages feed the PCM / DSD / DoP / MQA display |
| HDMI ARC | receiver near the HDMI socket (QFP-48, 1.2 V core; part not readable) | signal-present via expander pin 0x1C; routing shares the USB path, differing on P2.4 | Read by the signal-present routine 0x5232 |
| Bluetooth | separate module board | expander pin 0x10 (high only on the Bluetooth input; "BT Reconnect" pulses it low) and 0x14 ("BT list clear" pulses it low); status via expander pins 0x11..0x13; signal-present via expander pin 0x15 | own stack, out of reach |
| Signal presence per input (0x5232) | | USB: P4.5; optical/coax/AUX: P4.2 lock; Bluetooth: expander 0x15; HDMI: expander 0x1C; USB detect also expander 0x1D | Drives the on-screen status and a mute on signal loss (P2.5, after 1 s, digital inputs and headphone mode). There is no auto-standby; "Always ON / Auto OFF" is the display Dimmer timeout |
| Input routing | mux control + NJW1194 selector | P0.1, P0.2, P4.6, P2.4, expander pin 0x18, five receiver registers (0x24D6) | Per-input table in `docs/bus-map.md` |
| Power amplifier | MA5332MS, analogue in | mute on MCU P2.2 (high while muted and in headphone mode; role inferred from the trace) | no control interface |
| Speaker and headphone relays | two speaker relays, one headphone relay | P2.5 and P2.7, high in headphone mode (`p2_mute_pins_by_output`); which pin drives which relay is not known | |
| Display | ST7789-class colour LCD, 320 × 170 as drawn | bit-banged 8-bit bus on P1 (WR P0.5, CS P0.7, D/C P0.3), byte writes 0x567A / 0x5C9C with a delay call per byte; full clear 0x51EE | column offset 0x23. Window 0x4437: firmware y + 0x23 → CASET, firmware x → RASET, so pixels stream one 170-px vertical line at a time; P0 and P1 are push-pull (init 0x45CE). Two 1-bit fonts, stored rotated (glyph rows = screen columns): small 14 × 24 at 0x5DAB (42 bytes/glyph, painter 0x2DF8, status line and menus) and big 32 × 30 at 0x6A23 (120 bytes/glyph, painter 0x3F3C, input name and other centre-line text); glyph index = digits 6..15, A-Z 0x10.., a-z 0x2A.. (small font only); the big font's bytes hold house-numerals' fonts since hn17 (nothing there draws with the stock big glyphs, see "Memory budget"). Text colour from the theme table 0x9241 (RGB565: FFFF F800 07E0 33BF CFA0 07FF FC00 F81F). Home (refresh 0x5C8B): output/mute icon at 15,8 (0x5744), volume as two digits at 48,9 (0x5916; speaker volume 0x31 or headphone volume 0x52), format tag at 208,10, EQ tag at 266,10, input name centred at y 75, status line centred at y 135. Page variable 0x45 (1 home, 2 volume, 3+ menus; renderer 0x2101, jump table `ui_page_table` at 0x2143, page 2 entry `volpage_render` at 0x2167). Volume page (page 2): full clear, two digits at 130,75, "volume" at y 135, back home when the Timer0 countdown 0x3F:0x40 (200 ticks, armed by the key tail 0x0F48) runs out (0x3ED9 sets page 1 and 0x22.3); the next render only clears, and the periodic refresh 0x3FE3 draws home 10 main ticks later (0x27:0x28 is that refresh countdown: 10 after a render, 50 after each refresh). The volume keys (`key_volume_up` 0x0D03, `key_volume_up2` 0x0D83, `key_volume_down4` 0x0E2A, `key_volume_down` 0x0ED2) each set page 2 and open it directly, inline right after `mov 0x45,#0x02` (four sites: 0x0D33, 0x0DB3, 0x0E5A, 0x0F02, each `lcall ui_clear_screen` then the "volume" caption); the page-2 renderer at 0x2167 is only a second way in, not the path the keys use |
| Backlight | LED on GPIO P0.6 | on/off only; "Auto OFF" (0x29 = 2) clears it when the countdown 0x2F:0x30 runs out (0x33DB, main ticks), armed to 500 by every key (0x0BBD): about 6 s in the emulator, as main-loop passes miss some 10 ms ticks | no PWM peripheral on this MCU. Stock never arms it at power-on, see "AO300 PRO firmware" |
| Front panel | buttons / encoder (nets RE_A, RE_B) | P4.7, P5.4, P5.5, P2.6, P7.4 | Encoder scanned by Timer3 (0x5040, every 0.5 ms) through 0x396D into RAM 0x2D (0xFF idle); when no IR or panel key is pending, `read_key`'s tail (0x3E37) returns 0x2D on every powered page (menu pages other than 7 and 8 swap 0x1A and 0x1B first), so `dispatch_key` sees 0xFF (no key) on an idle pass. `tools/emu/ao300.py` runs Timer3 as well as Timer0 (see `docs/development.md`, "Testing") |
| Serial update port | CH340 USB serial chip (as the computer sees it) | UART1 on P3.0/P3.1 in standby; the STC bootloader uses the same pins | Reaches the computer through the amp's one USB-C socket, which also carries USB audio. The serial port drops off the host while USB or AUX is selected (`docs/open-questions.md`). The board also has a 4-pin header next to the HDMI receiver (silkscreen 5V, TXD, RXD, GND); flashing does not use it. The probe's code and comments call P3.0/P3.1 "the header pins" |
| Settings | MCU EEPROM area above 0xF400 | IAP routines 0x5956 (read) / 0x58AF (write) / 0x59D0 (erase) | Sector 0: magic 0x45 at 0x0001, power-on flag at 0x0002 (RAM 0x26; non-zero: a cold power-up turns the amp on). Sector 0x0200: the record 0x0201..0x020C = volume, input, output, 0x4A, EQ, 0x35, 0x2A, colour, headphone volume, 0x33, dimmer, filter. Loaded only at a cold boot (`settings_load_eeprom` 0x2F46), saved whole by `settings_save_eeprom` (0x492B) about 0.5 s after a change and after every power-on. Sector 0x0400 is erased by `key_power_off` (0x0CDA); no read or write of it was found |

Things the MCU firmware cannot change, because they happen elsewhere: USB decoding,
Bluetooth, SPDIF/ARC extraction, the DAC's conversion and filters themselves, and the
class-D amplification. The MCU only selects modes and values in those chips.

## Volume scale: 0–60 steps and dB

The number on screen is a step count; the dB value behind it is fixed by a table.

- **State.** Speaker volume is RAM 0x31 and headphone volume is RAM 0x52. RAM 0x2B picks
  which one is active: 1 is speakers, 2 is headphones. Both run from 0 to 60; the
  increment stops at 0x3C.
- **Power-on.** Both volumes are loaded from EEPROM at a cold boot and only clamped to
  0..60; standby keeps them in RAM. Stock therefore starts at the last volume on either
  output. Its only cap is on an output switch (0x5296): the headphone volume is cut to 30.
  `features/start-volume` caps both at power-on.
- **Hardware write.** 0x4DDC looks up code = table[60 − step] in the 61-byte table at
  0x9289 and sends it to the NJW1194 volume registers through 0x54DA / 0x54EA.
- **NJW1194 encoding** (from its datasheet): code n gives 32 − n/2 dB, in 0.5 dB steps;
  0xFF is mute.
- **Display.** Stock only ever shows the step, as two digits: at 48,9 on the home screen
  (0x5916) and at 130,75 on the volume page (0x5936). There is no dB text anywhere in
  the firmware. House Numerals (from hn8) shows the level below step 60 as a caption on its volume
  page ("−39.5 dB"), computed from the code table: `code − 35` half-dB steps.

The stock curve:

| Step | Code | NJW1194 gain | Relative to step 60 |
|---|---|---|---|
| 60 | 0x23 | +14.5 dB | 0.0 dB |
| 59 | 0x24 | +14.0 dB | −0.5 dB |
| 50 | 0x36 | +5.0 dB | −9.5 dB |
| 45 | 0x40 | 0.0 dB | −14.5 dB |
| 40 | 0x4A | −5.0 dB | −19.5 dB |
| 35 | 0x54 | −10.0 dB | −24.5 dB |
| 30 | 0x63 | −17.5 dB | −32.0 dB |
| 20 | 0x81 | −32.5 dB | −47.0 dB |
| 10 | 0x9F | −47.5 dB | −62.0 dB |
| 1 | 0xBA | −61.0 dB | −75.5 dB |
| 0 | 0xFF | mute | −∞ |

Shape of the curve:
- 60→59 is a 0.5 dB step;
- 59→35 is 1 dB per step;
- 35→1 is 1.5 dB per step.

Steps 1 to 60 cover 75.5 dB in total. The NJW1194 is at unity gain at step 45 and adds
gain above it.

Showing dB instead of steps is a display-only change. The volume code, the table and the
EEPROM format stay as they are:

- **Text table.** Replace the two-digit calls at 0x5916 and 0x5936 with a lookup that
  formats a dB string. Stored as twice the dB value, one byte per step fits, so the table
  is 61 bytes. The formatting code adds about 60 bytes.
- **Width.** A dB string is up to 6 cells ("−75.5" plus a unit), 84 px in the 14 × 24
  font. The home spot at 48,9 has room up to the format tag at x 208. The volume page
  needs the text re-centred.
- **Reference point.** Relative to step 60 (0 dB at maximum, negative below) is the usual
  hi-fi convention and is what the UI theme designs use. The NJW1194's own gain
  (+14.5 to −61 dB, 0 dB at step 45) is the alternative.
- **Curve, optional.** Making the steps even is a separate change: rewrite the 61 bytes
  at 0x9289. Evening it out changes how loud each step is, not just the label, so it
  should be a deliberate choice.

## Memory budget for custom features

Measured from the images; the code/EEPROM split is the chip's own setting (0xF400).

| Region | Size | Used | Free |
|---|---|---|---|
| Code flash, 0x0000..0xF3FF | 62464 bytes | 56642 bytes (features/house-numerals hn19) | 5822 bytes after the image, plus 988 unused inside it (0x93A7..0x96FF and 0x977D..0x97FF: the fixes' standalone slots, which an image that includes them leaves as 0xFF) and 25 at 0x7DBA..0x7DD2 (the end of the stock big font's area, below) |
| EEPROM area, 0xF400..0xFDFF | 2560 bytes, 5 sectors of 512 | sectors at offsets 0x0000, 0x0200, 0x0400 | 2 sectors, 1 KB |
| Internal direct RAM, 0x00..0x7F | 128 bytes | all (registers, bit flags, variables up to 0x7F) | none |
| Internal indirect RAM, 0x80..0xFF | 128 bytes | stack from 0x88 (`mov SP,#0x88` at 0x44A5) | stack headroom only |
| External RAM (XDATA) | 2 KB by chip naming, not measured | page 0 (0x0000..0x00FF): display cell buffers, locals | ~1.7 KB from 0x0100 |

The stock big font (`font_big_32x30`, 0x6A23..0x7DD3, 5040 bytes) is dead in house-numerals
since hn17 and in phosphor-panel: `big_text_render`'s hook goes straight to the theme's name
painter and the stock number painters are unreachable, so the theme keeps its own data there
(house-numerals 5015 bytes of fonts, phosphor-panel 4520 bytes: the status and icon fonts and
the cell map; `features/house-numerals/README.md`, "Memory"; the tests trap `big_glyph_paint`
and `bignum_digit` on every run). Phosphor Panel pp4 ends at 0xDC34 (56373 bytes); its
dot-matrix name font alone is 9711 bytes, three times the plain face, because the grid breaks
the run-length runs every third row. The stock small font (0x5DAB..0x6A23, 3192 bytes) is still drawn
by the menus, the Treble and Bass pages and the RESET page; drawing those with a theme font
(mono16 and mono28 cover every firmware string but `W` and `+`) would free it too.

Rules of thumb: new code appends after the existing patch area (0x9400 upward); new
state goes in XDATA, preferably 0x0100..0x0400 so it is safe even if the XRAM size
assumption is wrong; new settings can use the two free EEPROM sectors. Rough cost of the
features discussed so far: screen-off re-arm 14 bytes (built, fix-auto-off); power-on volume cap 23 bytes
(built, start-volume); volume keys without a signal 24 bytes (built, fix-volume-pop); menu input switch 23 bytes (built, fix-menu-input); a settings menu layer ~270 bytes once and ~45 per setting (sketched in
`docs/menu-system.md`); status-line redraw skip ~40 bytes
+ 26-byte XDATA buffer; backlight PWM a few hundred bytes + menu + 1 EEPROM byte; HDMI
auto-switch ~60 bytes. Space is not the limit; the hand-assembled hook method and the
emulator coverage are.

## Key facts about the firmware

- Container obfuscation: fixed-key byte cipher, key 0x4C, permutation table inside the
  updater. Records are `0x70, type, u16 checksum, u32 length, data`; the checksum is the
  negated byte sum. Record 0xFF is the flash image.
- IR path: NEC decoder in the INT0 handler (0x2681) stores the command byte at RAM 0x6A;
  `ir_cmd_to_key` (0x5D10) maps it through the 15-byte table at 0x9398; the dispatcher
  (0x0BB4) switches on the result through a Keil switch helper at 0x2072. The decoder times
  the falling edges with Timer1, checks the address bytes 12 34 and sets bit 0x20.4 for
  `read_key`. A held Vol+, Vol-, Up or Down sets the bit again on every repeat code but the
  first. NEC 0x08 acts on release (200 ms after its last repeat, `inject_key_08`) and becomes
  0x0E at its tenth repeat. 300 ms after the last frame or repeat the Timer0 ISR clears 0x6A
  (0x34, 0x3EAC), which ends the repeats.
- Inputs live in RAM 0x47 (1..6); `input_apply` (0x5640) switches the hardware via
  `input_set_hw` (0x24D6) and saves the setting to EEPROM.
- Power flag is RAM 0x4F (0 = standby). Source on the remote while in standby resets the
  MCU into the STC bootloader.
- The updater sends no download password and uses no user key, so stcgal's `stc8d`
  protocol can also talk to the chip. The vendor tool rewrites the option bytes and the clock
  trim from its own container every time; `tools/flash/flash_ao300.py` reads the chip first,
  checks it, and writes the options back unchanged.
- Flash can't be read back over ISP. The vendor updater is the only source of the stock
  image, so keep it.
- Key handlers found through the dispatcher, run in the emulator: 0x1047 (key 0x1C, NEC 0x09) is the mute
  toggle (it goes home first; it runs on page 1 only: in a menu `dispatch_key` turns the key
  into "home" at 0x0C23, and on the volume page `read_key` does at 0x3DD6, so there the key
  closes the page without muting; house-numerals hn14 changes both, see its README), 0x10BE (key 0x14, NEC 0x08) toggles Dimmer, 0x106D (key 0x0A, NEC 0x0E) is "BT
  Reconnect", 0x10E1 (four-press combo 0x38) is "BT list clear", 0x0F62 (key 0x59) steps
  the EQ. None is a hidden service function.

## AO300 PRO firmware (V1.2, package AO300PROFW20260507)

Same MCU, same clock and EEPROM split, and the same codebase with eARC additions. The
package ships a plain Intel HEX of the image next to the updater (identical to the
updater's payload). The updater is a newer STC-ISP build (6.96A) whose cipher table sits
elsewhere; `stc_release.py` now locates the table by search, so it unpacks both.

Differences from AO300 v1.4: eARC with a CEC on/off menu (different HDMI receiver, not
portable), an `AT+GETCODEC` query to the Bluetooth module (the Pro transmits on UART1,
the AO300 never does), and the fix named in SMSL's note: with Dimmer set to Auto OFF,
the screen-off countdown was not armed after a power-on, so the display stayed lit until
the next key press. The AO300 v1.4 code has the same omission (the countdown at RAM
0x2F:0x30 is only armed inside the key dispatcher; the power-on routine at 0x5585 ends
without arming it). The Pro arms it at the end of its post-power-on routine. The IR
command table is identical, so no new remote codes exist.

Backported in `features/fix-auto-off`: post_power_on's tail (0x55B9) arms the countdown
to 500 when RAM 0x29 == 2, the same value a key press loads. In the emulator the bug only
shows after a cold power-up. Entering standby with the remote's Power key goes through the
key dispatcher, which arms the countdown; it freezes in standby and drains after the next
power-on, so stock times out there too.
