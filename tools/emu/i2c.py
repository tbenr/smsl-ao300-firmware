"""I2C slave model for the AO300 harness: devices that answer, and a log of every transfer.

    amp = Amp(image)
    bus = I2CBus(amp)                      # before amp.boot()
    bus.inputs[(0xB0, 0x01)] = 0x10        # what a read of that register returns
    ...
    for t in bus.log: print(bus.format(t))

Without it nothing drives the data line, so every transfer of the stock firmware ends in a
NACK and is retried five times, and every read returns 0xFF bits. The model hooks the
stock bit-bang primitives instead of decoding the pins:

    i2c_start 0x5B65, i2c_write_byte 0x56B9 (R7), the ACK sample at 0x535D,
    the data-bit sample at 0x57B5 (bit number in R5), i2c_stop 0x5C08.

They are the only code that touches the bus: i2c_read_reg16 (0x4CDF), i2c_write_reg
(0x4FAD) and dac_write (0x4D8A) are built on them. Every address ACKs unless it is listed in
`absent`. A read returns `inputs[(device, register)]` if set, else the last value written
there, else 0. Device addresses are the 8-bit write addresses the firmware uses (0xB0, 0x80,
0xC0, 0x62).

Each log entry is (cycle, site, kind, device, register, value, acked): `site` is the address
of the call into the stock routine that made the transfer, kind "R" or "W". The DAC's
registers are 24 bits wide and its value is (control byte, data).
"""
START, WRITE_BYTE, ACK_SAMPLE, BIT_SAMPLE, STOP = 0x5B65, 0x56B9, 0x535D, 0x57B5, 0x5C08
P3, SDA = 0xB0, 0x80
DAC = 0x62


class I2CBus:
    def __init__(self, amp, absent=()):
        self.e = amp.e
        self.absent = set(absent)
        self.regs = {}                 # (device, register) -> last value written
        self.inputs = {}               # (device, register) -> value a read returns
        self.log = []
        self._cur = None
        self._ack = False
        for addr, fn in ((START, self._start), (WRITE_BYTE, self._write), (ACK_SAMPLE, self._ack_sample),
                         (BIT_SAMPLE, self._bit_sample), (STOP, self._stop)):
            self.e.hooks[addr] = fn

    def _start(self, em):
        if self._cur is None:              # else a repeated start
            sp = em.sfr[0x81]              # return into the routine, then into its caller
            site = (((em.iram[sp - 2] << 8) | em.iram[sp - 3]) - 3) & 0xFFFF
            self._cur = {"cycle": em.cycles, "site": site, "dev": None, "bytes": [], "read": None, "acks": []}
        self._cur["addressed"] = False

    def _write(self, em):
        c = self._cur
        if c is None:
            return
        if not c["addressed"]:
            c["dev"], c["addressed"] = em.R(7) & 0xFE, True
        else:
            c["bytes"].append(em.R(7))
        self._ack = c["dev"] not in self.absent

    def _ack_sample(self, em):
        if self._cur is not None:
            self._cur["acks"].append(self._ack)
        em.pins[P3] = (SDA, 0 if self._ack else SDA)

    def _bit_sample(self, em):
        c = self._cur
        if c is None:
            return
        n = em.R(5)
        if n == 0:
            reg = c["bytes"][-1] if c["bytes"] else 0
            key = (c["dev"], reg)
            v = 0xFF if c["dev"] in self.absent else self.inputs.get(key, self.regs.get(key, 0))
            c["read"] = (reg, v)
        em.pins[P3] = (SDA, SDA if (c["read"][1] >> (7 - n)) & 1 else 0)

    def _stop(self, em):
        c, self._cur = self._cur, None
        em.pins[P3] = (0, 0)
        if c is None:
            return
        dev, by, ok = c["dev"], c["bytes"], all(c["acks"])
        if c["read"] is not None:
            entry = ("R", dev, c["read"][0], c["read"][1])
        elif dev == DAC and len(by) == 5:
            entry = ("W", dev, (by[0] << 16) | (by[1] << 8) | by[2], (by[3], by[4]))
        elif len(by) == 2:
            entry = ("W", dev, by[0], by[1])
        else:
            entry = ("W", dev, None, tuple(by))
        if ok and entry[0] == "W" and entry[2] is not None:
            self.regs[(dev, entry[2])] = entry[3][1] if dev == DAC else entry[3]
        self.log.append((c["cycle"], c["site"]) + entry + (ok,))

    @staticmethod
    def format(entry, clock_hz=24_000_000):
        cycle, site, kind, dev, reg, v, ok = entry
        regs = "--" if reg is None else ("%06X" % reg if dev == DAC else "%02X" % reg)
        vs = "%02X" % v if isinstance(v, int) else "/".join("%02X" % x for x in v)
        return "%9.3f  site %04X  %s  dev %02X  reg %s = %s%s" % (cycle / clock_hz, site, kind, dev, regs, vs,
                                                                  "" if ok else "  NACK")
