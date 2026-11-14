# Reaching the amp's serial port from another computer

Runs ser2net in Docker on the Linux machine the amp's USB socket is plugged into, so
`tools/flash/flash_ao300.py` on another machine can reach the amp through
`-p rfc2217://<linux-host>:4000`. The flasher routes pyserial URLs through
`serial_for_url`; stock stcgal alone only opens device paths.

**The forwarded port has no authentication.** Anyone who can reach it can erase and flash
the amp. By default the container listens on 127.0.0.1 only; open it to a network only if
you trust every machine on it.

## Files

- `ser2net.yaml`: one connection, `telnet(rfc2217)` on TCP 4000, device `/dev/ttyUSB0`
  opened at 2400 baud even parity, modem lines ignored (`local`), a new connection
  kicks a stale one.
- `Dockerfile`: Debian trixie slim plus the distro `ser2net` package (4.6), run with
  `-d` so it stays in the foreground and logs to stderr (`docker compose logs`).
  Not Alpine: its package is ser2net 3.5, which reads only the old flat config format
  and starts with no connections when given this YAML ("No state given on line N").
- `docker-compose.yaml`: maps the amp's `/dev/serial/by-id/...` path to `/dev/ttyUSB0`
  inside the container and publishes port 4000 on `AO300_BIND` (default 127.0.0.1).

## Run

```bash
ls /dev/serial/by-id/          # put the amp's name into docker-compose.yaml
docker compose up -d --build --force-recreate
docker compose logs -f
```

Then reach it in one of two ways, read-only first:

- **Through SSH** (the default binding): `ssh -L 4000:localhost:4000 <linux-host>` on the
  flashing machine, then

  ```bash
  python3 tools/flash/flash_ao300.py -p rfc2217://localhost:4000 identify
  ```

- **Directly on a trusted network:** put `AO300_BIND=0.0.0.0` in a `.env` file next to
  `docker-compose.yaml` (git ignores it) and recreate the container, then

  ```bash
  python3 tools/flash/flash_ao300.py -p rfc2217://<linux-host>:4000 identify
  ```

## Notes

- RFC 2217 is not optional. stcgal starts at 2400 baud and switches to 115200 during
  the handshake; over a plain TCP socket the device's baud never changes and the
  handshake fails right after the switch.
- The host kernel still owns the CH340, so ModemManager or brltty grabbing the device
  on the Linux machine breaks this just as it breaks local flashing.
- With `devices:` the container fails to start while the amp is unplugged;
  `restart: unless-stopped` retries until it appears.
- `identify`, `dryrun` and `flash` all work this way (ser2net 4.6; `docs/status.md`). The
  switch to 115200 baud travels as an RFC 2217 control command.
