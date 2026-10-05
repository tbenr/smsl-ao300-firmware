# Debian trixie ships ser2net 4.6 (YAML config, RFC 2217). Alpine's package is still
# ser2net 3.5, which only reads the old flat line format and ignores this YAML silently.
FROM debian:trixie-slim
RUN apt-get update && apt-get install -y --no-install-recommends ser2net \
    && rm -rf /var/lib/apt/lists/*
# -d: stay in the foreground and log to stderr. Without it ser2net logs through
# syslog, which a container does not have, so config and device errors vanish.
CMD ["ser2net", "-d", "-c", "/etc/ser2net/ser2net.yaml"]
