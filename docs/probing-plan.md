# Probing the amp beyond stock: plan

Goal: find out what the control MCU can do with the chips around it that the stock firmware
does not, without risk to the amp or the speakers. Three layers, each riskier than the last.
Layer 1 is done (2026-10-01); its results are in `docs/bus-map.md`.

A bad image cannot brick the MCU: the STC bootloader runs on every cold power-up and
`flash_ao300.py recover` restores stock. The DAC, receiver, expander and clock generator are
set up again by the firmware at every power-on. What can be harmed: speakers and ears
(full-scale output), two outputs driving one net, and the two parts that keep state, the
Bluetooth module and the XMOS.

## Layer 1: emulator and disassembly (done)

`tools/emu/bus_trace.py` runs stock through every input and setting with the I2C slave model
`tools/emu/i2c.py`. Everything in `docs/bus-map.md` is from that trace and the disassembly;
nothing is measured.

## Before layer 2: checks that need no build

- **Datasheets.** Check against the documents, and correct `docs/bus-map.md` where they
  differ: the CS43131 register names and the bits of 0x090000 to 0x090004; the NJW1194
  select addresses (are 0x00 and 0x10 the two channels?); the STC8C2K64S2 P_SW1 table (the
  UART1 pin pairs were taken from the STC8G manual); the AW9523B register set.
- **Board.** A photo or a meter reading settles what the trace can only infer: the clock
  generator's part and crystal and where its output goes; which nets P2.1, P2.2, P2.5, P2.7,
  P4.3, P4.4, P0.0 and P4.0 are (MUTE_AMP, MUTE_HP, DIR_RST, relays, supply enables); that
  the header's TXD is P3.1.
- **XMOS messages.** Tabulate the jump tables after `xmos_format_take` (0x408B): what each
  format class and rate index means.

## Layer 2: a read-only probe build (done: flashed and the first dump captured 2026-10-05)

`features/probe/`, on stock, including the six fixes every image for the amp carries, version
`v1.4 tbenr pr1`. The design below is what was built; its README has the dump format and the
steps on the amp.

- **Trigger.** The remote's FN button (NEC 0x08; pr1 used the free code 0x16), home page,
  amp on. Nothing runs unless that command arrives.
- **Channel.** The programming header, 115200 baud, to the USB-serial adapter used for
  flashing. With the amp on, UART1 sits on P3.6/P3.7, and P3.7 is the bus data line: the
  routine must switch P_SW1 to the header pins, send, wait for the last byte to leave, and
  switch back. It must never write SBUF while UART1 is on P3.6/P3.7. `uart1_isr` clears TI,
  so the sender either turns ES off for the dump or does not wait on TI. XMOS bytes that
  arrive during a dump are lost; the next message repairs the display.
- **What it dumps.** All reads, through the stock `i2c_read_reg16`:
  - an address scan (start, address, ACK sample, stop; no data byte), to find chips the
    firmware never talks to;
  - the expander's registers 0x00 to 0x13;
  - the receiver's registers 0x20 to 0x7F;
  - the clock generator's registers 0x00 to 0xB7 (stock never reads them);
  - the MCU ports P0 to P5 as read from the pins;
  - the UART buffer bytes.
  The DAC is not in the list: its registers take a three-byte address and stock has no read
  routine for it. Reading it means writing one, which belongs to layer 3 thinking.
- **Read hazards.** Some status registers clear when read (the receiver's error flags,
  the expander's input ports clear its interrupt). Harmless for the amp, but compare dumps
  with that in mind.
- **Tests** (AGENTS.md): the dump run at its hook with `i2c.py` supplying the chips
  (`absent` for the scan); the bytes captured with an `sfr_watch` on SBUF, checked against
  the model; P_SW1 restored and SBUF never written while it selects P3.6/P3.7; the sweep of
  all 256 commands against stock plus the same fixes in every state the hook reads; the
  image diff; a full-firmware scenario from reset, since the hook is in the key path. All in
  `features/probe/emu_test.py`, passing.
- **On the amp.** The user says go for the flash and again for the serial listener. Take
  one dump per input, with and without a signal, and keep them outside the repository.

Layer 2 answers: is anything else on the bus; do the chips hold the values the trace says;
which expander inputs and MCU pins move when a cable or headphone is plugged in.

First dump, 2026-10-05 (`docs/bus-map.md`, "Hardware read-back"): nothing else on the bus,
every written register reads back, the expander is an AW9523B, and the clock generator
reports PLL A unlocked on Optical without a stream and locked on HDMI (second dump, TV
off): its reference comes with the input, probably from the receiver. Seven dumps on
2026-10-05 (HDMI and Optical, TV in standby, muted and playing, then an optical stream too)
and the PCM9211 datasheet gave the receiver's wiring: the HDMI receiver's I2S on AUXIN0 and
its S/PDIF on RXIN3, the DIR parked on RXIN3 on USB and AUX. Deferred: USB and AUX dumps
(the adapter drops off the Linux box on those two inputs while the amp's USB cable is in
that box; unplug the cable or isolate the adapter first), which would confirm that
register 0x39 shows the ARC stream there. Still to take: Bluetooth with and without a
stream; Coaxial with a stream; headphones in; a second read of the clock generator's status
after its sticky flags are cleared.

## Layer 3: single writes

Only after layer 2, one register per build or per command, each taken from a datasheet
first.

- Speakers disconnected, headphones unplugged, amp muted, until a write is known to be
  quiet.
- Read the old value first where the chip allows it, restore it afterwards.
- No change to expander direction registers or MCU pin modes for a net that is not
  identified on the board.
- Bluetooth module: query commands only. Nothing is sent to the XMOS.
- No change to the reset vector, the standby key handler or `read_key`'s bootloader jump.

## Features this could lead to, in order of value and safety

1. **Balance**: a per-channel offset on the NJW1194 volume codes. Analogue, every input.
   Needs the datasheet check that the two volume words are the two channels.
2. **Sample rate on the status line for every digital input**: the receiver register is
   already polled.
3. **DAC options**: de-emphasis, the high-pass filter, per-channel digital volume. Digital
   inputs only, and only after the register check.
4. **Custom EQ presets**: other bass and treble levels in `eq_apply`'s presets. Convenience
   only: the Tone preset with the Treble and Bass menus already reaches every pair, -9 to
   +9 dB each. The tone words carry only level, direction and on/off, so the two bands'
   corner frequencies cannot be moved from firmware.

Out of reach from the MCU: a parametric EQ (no DSP in the signal path of the non-USB
inputs), the XMOS firmware, the Bluetooth stack, the HDMI receiver, the class-D stage.
