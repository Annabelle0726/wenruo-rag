#!/bin/sh
# Emit a deterministic sha256 manifest of every regular file in the image root filesystem.
# Volatile, kernel-backed and per-container-injected paths are pruned so that two containers
# instantiated from the same image produce byte-identical manifests.
# Only file CONTENT is hashed; no mtimes, sizes-as-metadata or directory entries are emitted.
find / -xdev \
  \( -path /proc -o -path /sys -o -path /dev -o -path /run -o -path /tmp \
     -o -path /var/log -o -path /var/cache -o -path /var/tmp \
     -o -path /etc/hosts -o -path /etc/hostname -o -path /etc/resolv.conf \
     -o -path /etc/mtab \) -prune -o -type f -print0 2>/dev/null \
| xargs -0 -r sha256sum 2>/dev/null \
| sort -k2
