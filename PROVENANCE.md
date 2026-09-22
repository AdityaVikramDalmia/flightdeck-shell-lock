# Provenance

This component distills Flightdeck's cooperating-writer locking requirement from
`bin/lib/lock.sh` and `bin/lock-test.sh` at commit
`494799eea3b9e7ce8686506a288c297ccf96be8d`.

It is a standalone implementation using Python's standard-library `fcntl.flock`,
not a copy of the original Bash mkdir/PID takeover algorithm. Kernel-held file
locks replace stale-owner repair, and descriptor inheritance protects a surviving
child after wrapper termination. Tests and examples are newly authored synthetic
fixtures; no private configuration or operational data is included.
