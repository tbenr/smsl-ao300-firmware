# Forwarding the amp's serial adapter with ser2net

Runs ser2net in Docker on the Linux machine the USB-serial adapter is plugged into, so
`tools/flash/flash_ao300.py` on another machine can reach the amp through
`-p rfc2217://<linux-host>:4000`. The flasher routes pyserial URLs through
`serial_for_url`; stock stcgal alone only opens device paths.

## Files

- `ser2net.yaml`: one connection, `telnet(rfc2217)` on TCP 4000, device `/dev/ttyUSB0`
  opened at 2400 baud even parity, modem lines ignored (`local`), a new connection
  kicks a stale one.
- `Dockerfile`: Debian trixie slim plus the distro `ser2net` package (4.6), run with
  `-d` so it stays in the foreground and logs to stderr (`docker compose logs`).
  Not Alpine: its package is ser2net 3.5, which reads only the old flat config format
  and starts with no connections when given this YAML ("No state given on line N").
- `docker-compose.yaml`: maps the adapter's `/dev/serial/by-id/...` path to
  `/dev/ttyUSB0` inside the container and publishes port 4000.

## Run

```bash
ls /dev/serial/by-id/          # put your adapter's name into docker-compose.yaml
docker compose up -d --build --force-recreate
docker compose logs -f
```

Then from the flashing machine, read-only first:

```bash
python3 tools/flash/flash_ao300.py -p rfc2217://<linux-host>:4000 identify
```

## Notes

- RFC 2217 is not optional. stcgal starts at 2400 baud and switches to 115200 during
  the handshake; over a plain TCP socket the device's baud never changes and the
  handshake fails right after the switch.
- The host kernel still owns the CH340, so ModemManager or brltty grabbing the device
  on the Linux box breaks this just as it breaks local flashing.
- With `devices:` the container fails to start while the adapter is unplugged;
  `restart: unless-stopped` retries until it appears.
- Publishing `4000:4000` listens on every interface. For an SSH-only setup bind to
  127.0.0.1 and use `ssh -L 4000:localhost:4000 <linux-host>`, then
  `-p rfc2217://localhost:4000`.
- Status: `identify` passed over the tunnel on 2026-10-05 (all checks ok, 2400 baud
  handshake and option readout). `dryrun` and `flash` are not yet tried this way; they
  add the switch to 115200 baud as an RFC 2217 control command, so run `dryrun` first.
