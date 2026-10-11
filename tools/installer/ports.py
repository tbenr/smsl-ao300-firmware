"""Serial adapter detection for the installer: the USB serial ports pyserial can see.

candidates(ports) keeps the ports with a USB vendor id (the Bluetooth and debug ports a Mac
lists have none) and, on macOS, the cu. side of each cu./tty. pair, which is the one the
flasher's examples use. label(port) names the common adapter chips.
"""
import os

ADAPTERS = {
    (0x1A86, 0x7523): "CH340 USB serial",
    (0x1A86, 0x55D4): "CH9102 USB serial",
    (0x10C4, 0xEA60): "CP210x USB serial",
    (0x0403, 0x6001): "FTDI FT232 USB serial",
    (0x0403, 0x6015): "FTDI FT231X USB serial",
    (0x067B, 0x2303): "PL2303 USB serial",
}


def scan():
    """The USB serial ports present now, through pyserial."""
    from serial.tools import list_ports
    return candidates(list_ports.comports())


def candidates(ports):
    usb = [p for p in ports if getattr(p, "vid", None) is not None]
    devices = {p.device for p in usb}
    out = []
    for p in usb:
        base = os.path.basename(p.device)
        if base.startswith("tty.") and os.path.join(os.path.dirname(p.device), "cu." + base[4:]) in devices:
            continue                      # macOS lists each adapter twice; keep the cu. side
        out.append(p)
    return sorted(out, key=lambda p: p.device)


def label(port):
    name = ADAPTERS.get((port.vid, port.pid))
    if name is None:
        name = "%s %04X:%04X" % (port.description or "USB serial", port.vid, port.pid)
    return "%s  (%s)" % (port.device, name)


def looks_like_port(text):
    """A device path or a pyserial URL typed by the user."""
    text = text.strip()
    return text.startswith("/") or "://" in text
