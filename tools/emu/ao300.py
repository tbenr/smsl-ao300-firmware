"""AO300 harness for emu8051: boot the whole firmware, press remote keys, log audio events.

    amp = Amp(image_bytes)
    amp.boot()                    # reset -> standby main loop, real Timer0 and Timer3 ISRs
    amp.press(0x01); amp.wait(8)  # Power, then let the power-on sequence finish
    amp.lcd.save_png("home.png")

press() puts a NEC command where the INT0 decoder leaves it (RAM 0x6A, flag 0x20.4),
so the main loop picks it up exactly as a real remote press.

Two timer interrupts run, on one 0.5 ms grid. The Timer0 ISR (0x000B -> 0x3E67) runs
every 10 ms. timer3_isr (0x009B -> 0x5040) runs every 0.5 ms (Timer3 reload 0xD120 in 1T
mode) and stores encoder_scan's result in the encoder key 0x2D, 0xFF while the knob is
idle. Without it 0x2D stays 0, and read_key hands dispatch_key a phantom key 0 on every
idle main-loop pass on every powered page, which among other things keeps re-arming
the Auto OFF countdown 0x2F:0x30.
When both are due, Timer0 runs first. An interrupt whose enable bits are clear at its
tick is skipped, not held pending. e.on_tick fires every 0.5 ms; amp.ticks counts
Timer0 ticks only.

Audio events (amp.events, as (cycle, name, detail) tuples) cover everything that
touches the analogue or digital audio path: calls to the NJW1194, CS43131 and AW9523
writers and to input_set_hw, plus every change of the MCU pins the firmware uses for
mutes, muxes, the speaker/headphone switch and the backlight. amp.state holds the last value per
register and pin; amp.state_changes records it after every write that changed it
(and amp.state_log at every 10 ms tick), so two images can be compared on what the
audio chips actually see, in order.
"""
from emu8051 import Emu8051

CLOCK_HZ = 24_000_000
TICK = CLOCK_HZ // 100                 # Timer0: 10 ms
T3_TICK = 0x10000 - 0xD120             # Timer3: reload 0xD120, 1T = 12000 clocks = 0.5 ms
T3_PER_TICK = TICK // T3_TICK

# NEC commands of the stock remote (table at 0x9398)
NEC_POWER, NEC_UP, NEC_MENU, NEC_DOWN, NEC_SOURCE = 0x01, 0x02, 0x03, 0x06, 0x07
NEC_VOL_UP, NEC_VOL_DOWN = 0x0A, 0x0B

# state key and value for each audio writer: which register it sets, and to what
STATE_KEY = {
    "njw1194_write": lambda r: (("njw", r[7]), r[5]),          # R7 select|addr, R5 data
    "dac_i2c_write": lambda r: (("dac", r[4]), (r[5], r[7])),
    "expander_write": lambda r: (("exp", r[7], r[3]), r[5]),
    "input_set_hw": lambda r: (("input",), r[7]),
}

AUDIO_CALLS = {
    0x54EA: "njw1194_write",       # R5 data, R7 select/address
    0x4D9E: "dac_i2c_write",
    0x51AD: "expander_write",
    0x24D6: "input_set_hw",
}
AUDIO_PINS = {                     # SFR -> {bit: name}
    0x80: {1: "P0.1 mux", 2: "P0.2 mux", 6: "P0.6 backlight"},
    0xA0: {2: "P2.2 amp mute", 4: "P2.4 mux", 5: "P2.5 hp", 7: "P2.7 hp"},   # p2_mute_pins_by_output; roles in docs/bus-map.md
    0xC0: {0: "P4.0", 6: "P4.6 mux"},
}


class Amp:
    def __init__(self, image, log_audio=True, emu=Emu8051):
        self.e = emu(image)
        self.lcd = self.e.lcd
        self.events = []
        self.state = {}                    # audio state: last value per register / pin
        self.state_log = []                # state at every Timer0 tick: [(tick, frozen state)]
        self.state_changes = []            # [(cycle, frozen state)] after every write that changed it
        self.calls = {}                    # writer name -> set of argument tuples seen
        self.ticks = 0                     # Timer0 ticks
        self._t3_count = 0
        self.e.tick_every = T3_TICK
        self.e.on_tick = self._tick
        self.e.start_ticks()
        if log_audio:
            self._hook_audio()

    def _tick(self, e):
        self._t3_count += 1
        if self._t3_count == T3_PER_TICK:
            self._t3_count = 0
            self._timer0(e)
        if e.sfr[0xA8] & 0x80 and e.sfr[0xAF] & 0x20 and e.sfr[0xD1] & 0x08:   # EA, ET3, T3R
            e.interrupt(0x009B)

    def _timer0(self, e):
        self.ticks += 1
        self.state_log.append((self.ticks, tuple(sorted(self.state.items(), key=repr))))
        if e.sfr[0xA8] & 0x82 == 0x82:                # EA and ET0
            e.interrupt(0x000B)

    def _hook_audio(self):
        e = self.e
        for addr, name in AUDIO_CALLS.items():
            def hook(em, name=name):
                r = [em.R(n) for n in range(8)]
                regs = " ".join("R%d=%02X" % (n, r[n]) for n in (3, 4, 5, 7))
                self.events.append((em.cycles, name, regs))
                self.calls.setdefault(name, set()).add(regs)
                k, v = STATE_KEY[name](r)
                self._set_state(em, k, v)
            e.hooks[addr] = hook
        for sfr, bits in AUDIO_PINS.items():
            prev = e.sfr_watch.get(sfr)
            if prev is None:                          # only writes that move these pins
                e.sfr_watch_mask[sfr] = sum(1 << b for b in bits)

            def watch(em, old, new, bits=bits, prev=prev):
                if prev:
                    prev(em, old, new)
                for b, name in bits.items():
                    if (old ^ new) & (1 << b):
                        self.events.append((em.cycles, name, str((new >> b) & 1)))
                        self._set_state(em, ("pin", name), (new >> b) & 1)
            e.sfr_watch[sfr] = watch

    def _set_state(self, em, key, value):
        if self.state.get(key, object()) != value:
            self.state[key] = value
            self.state_changes.append((em.cycles, tuple(sorted(self.state.items(), key=repr))))

    @property
    def t(self):
        return self.e.cycles / CLOCK_HZ

    @property
    def page(self):
        return self.e.iram[0x45]

    @property
    def powered(self):
        return self.e.iram[0x4F] != 0

    def set_pin(self, sfr, bit, value):
        """Force what the firmware reads on an input pin (e.g. 0xC0, 5, 0 = USB activity)."""
        m, v = self.e.pins.get(sfr, (0, 0))
        m |= 1 << bit
        v = (v & ~(1 << bit)) | ((value & 1) << bit)
        self.e.pins[sfr] = (m, v)

    def boot(self, seconds=1.0):
        self.wait(seconds)

    def press(self, cmd):
        self.e.iram[0x6A] = cmd
        self.e.iram[0x20] |= 0x10                     # bit 0x20.4: new IR command

    def wait(self, seconds):
        self.e.run_for(seconds)

    def wait_idle(self, seconds, step=0.02):
        """Wait `seconds`; return the time of the last LCD write in that span (None if none)."""
        last = None
        end = self.e.cycles + int(seconds * CLOCK_HZ)     # whole clocks: no float drift
        chunk = max(1, int(step * CLOCK_HZ))
        while self.e.cycles < end:
            p0 = self.lcd.pixels
            n0 = len(self.lcd.log)
            self.e.run(None, 1 << 40, stop_cycles=min(end, self.e.cycles + chunk))
            if self.lcd.pixels != p0 or len(self.lcd.log) != n0:
                last = self.t
        return last
