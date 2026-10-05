# probe: a read-only register dump over the programming header

Layer 2 of `docs/probing-plan.md`. One remote button makes the amp send what its chips
hold, as text, through the 4-pin programming header. It only reads. pr1 (on NEC 0x16) was
flashed on 2026-10-05 and replaced the same day by pr2 (the FN button), which was flashed
and gave thirteen dumps, the first 1204 bytes as the emulator predicted (`docs/bus-map.md`,
"Hardware read-back"). pr3 adds the FS line, the first write of layer 3; emulator-verified,
not yet flashed.

## What it does

A short press of the remote's FN button (NEC command 0x08), with the amp on and on the home
screen, sends at 115200 baud, 8N1, on the header's TXD:

```
PROBE 1
SCAN 62 80 B0 C0
B0 00: 00 00 10 00 6E 30 00 00 00 00 00 00 00 00 00 00
B0 10: 00 13 FF FF
80 20: ...            six lines, registers 0x20 to 0x7F
C0 00: ...            twelve lines, registers 0x00 to 0xBF
FS: 09 80 28 3C 80 58 80 80
P: p0 p1 p2 p3 p4 p5 p7
R: 01 01 01 01 01 01 14 14 09 09 01 05 00 00 00 00 00 D1 D1
END
```

- `SCAN`: every 8-bit write address that acknowledged (start, address byte, stop; no data).
  The emulator shows the four chips `docs/bus-map.md` knows; the amp may show more.
- `B0`, `80`, `C0`: the expander, the digital receiver and the clock generator, read with
  the stock `i2c_read_reg16`. A register that never acknowledges reads as 00 after five tries.
  The DAC is not read: its registers take a three-byte address and stock has no read routine.
- `FS` (pr3): the receiver's sample-rate calculator pointed at each of its eight ports in
  turn, DIR, ADC, AUXIN0 (the HDMI receiver's I2S), AUXIN1 (the XMOS's I2S), AUXIN2, main
  output port, AUX output port, DIT. Each byte is register 0x38 for that port: bit 7 set
  means no result within the wait (no clock on that port), else bits 6:4 repeat the port
  and bits 3:0 give the rate code (8 = 44.1 kHz, 9 = 48 kHz, 0xC = 96 kHz). This is the
  probe's one register write, to the calculator target 0x37, a measurement block outside the
  audio path; stock's value is read first and written back after the eight ports.
- `P`: ports P0, P1, P2, P3, P4, P5, P7 as read from the pins.
- `R`: RAM, in this order: page, input, power, output, EQ, filter, volume, headphone volume,
  bass, treble, dimmer, format, 0x75, 0x73 (the XMOS message), 0x76, 0x77, 0x78 (the UART
  buffer), format configured, format read.

The dump takes about 210 ms (longer when ports have no clock: up to 64 polls each), during
which the main loop waits, as it does for a stock input switch. The command is then swallowed, so the short press does not toggle Dimmer as it does
in stock while this image is flashed; the Dimmer menu and FN's long hold ("BT Reconnect",
which the decoder delivers as 0x0E) are as stock. A short press is reported once, on release,
so a press never dumps twice. In standby or in a menu FN goes to the stock path. `COMMAND`
in `probe.py` picks the command; pr1 used 0x16, a free code for a controller that can send
any.

## How

- Hook: read_key's `lcall ir_cmd_to_key` (0x3DA9) becomes `lcall pr_key`. Every other
  command, and FN in standby or in a menu, continues into ir_cmd_to_key with a tail jump,
  so direct-select's hook on that routine still applies in the same image.
- UART1 is the stock one, already set to 115200 baud. With the amp on, stock keeps it on
  P3.6/P3.7 (the XMOS line; P3.7 is also the bus data line). The dump switches P_SW1 to the
  header pins for its duration and switches back, with ES off meanwhile because the stock
  UART handler clears TI, which the sender polls. SBUF is never written while P_SW1 selects
  P3.6/P3.7 (the test checks every byte). XMOS bytes that arrive during the dump are lost;
  the next message repairs the format display.
- No XDATA, no RAM: the saved P_SW1 and IE go on the stack; loop state is in R0, R1 and B,
  which the stock I2C routines do not touch.

## On the amp

1. Flash `build/flash_probe.bin` (sha in `KNOWN_IMAGES`) the usual way.
2. Keep the USB-serial adapter on the header after flashing and open a terminal on it at
   115200 baud, 8N1, for example `python3 -m serial.tools.miniterm <port> 115200`; a
   forwarded port works too (`serial.serial_for_url("rfc2217://host:4000", 115200)`). The
   adapter's RX sees the header's TXD. The amp's TXD is idle while it is on and the stock
   firmware never transmits, so nothing arrives until the command.
3. Amp on, home screen, press FN on the remote. The dump arrives within a second.
4. Take one dump per input, with and without a signal, headphones in and out, and keep them
   outside the repository.

Reading status registers clears some flags (the receiver's error bits, the expander's
interrupt): harmless, but two dumps in a row can differ there.

## Tests (`emu_test.py`)

- the image differs from stock only in the hooks, the fixes' patches and the version pointer;
- the hook from read_key with the I2C model answering for the four chips and a seeded register
  file: the text is exactly what the chips and the RAM hold, every byte leaves with P_SW1 on
  the header and ES off, P_SW1 and IE come back, the bus saw reads and address probes only,
  no audio chip was written, and the amp's state afterwards is the reference's;
- all 256 commands through read_key and dispatch_key against stock plus the same fixes, on
  the home and volume pages, in a menu, in standby and on page 0: identical but for FN on
  the home page with the amp on, after which the state is the reference's for a command it
  ignores, Dimmer included;
- the whole firmware from a cold power-up on the EEPROM and I2C models: the dump, then Vol+
  and an XMOS message still work, P_SW1 is back on the XMOS line with ES on, nothing was
  written to a chip, nothing is sent in standby or in a menu, the standby recovery path is
  untouched, and the dump works again back home.

`--in <feature>` runs the hook test and the scenario on any image that includes the probe.
