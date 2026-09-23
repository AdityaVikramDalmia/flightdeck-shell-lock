# Shell Lock

> **Deprecated for new Claude Code integrations — 2026-09-22.** Retained as an
> Apache-2.0 public reference implementation. This is a maintainer status
> decision, not a claim that Claude
> Code replaces every capability. No ongoing feature work or support is promised.

Public reference implementation, licensed under Apache-2.0.

Run a command under an exclusive local file lock. Useful for shell jobs, scheduled
tasks, build scripts, and agents that must not write the same resource concurrently.
No service, database, AI account, or shell-specific library is required.

Requires Python 3.8+ on macOS or Linux, and a local filesystem supporting advisory
`flock` locks. It does not support Windows or distributed/network-filesystem locks.

```sh
make test
make install PREFIX="$HOME/.local"
shell-lock --timeout 10 .locks/build.lock -- make test
shell-lock --timeout 0 .locks/backup.lock -- ./backup.sh
```

Or run `./bin/shell-lock` directly. Parent directories are created as needed.
Command arguments are executed directly; use `sh -c '...'` explicitly for shell
syntax. The command receives normal stdin/stdout/stderr (including streams deliberately
left closed), and its exit status is preserved. A busy lock times out with exit 75 without starting the command.

The kernel releases the lock when the last inherited lock descriptor closes.
There is no stale PID file to reap. The command inherits the descriptor named by
`SHELL_LOCK_FD`, so killing the wrapper alone does not normally unlock a child that
is still running. Do not close that descriptor in the command. Signal forwarding
and crash boundaries are documented in [the contract](docs/contract.md).

**Keep the lock file in place.** Never delete or replace it to unlock it: different
inodes can otherwise protect different commands under the same apparent pathname.
The tool leaves the file in place after exit and detects replacement while waiting.

| Exit | Meaning |
|---|---|
| Command's status | Command was started; its status is returned |
| `75` | Lock could not be acquired within the timeout |
| `73` | Lock-file/storage operation failed |
| `126` / `127` | Command is not executable / not found |
| `2` | Invalid CLI usage |
| `128 + signal` | Wrapper received a handled termination signal |

An executed command can itself return any of those codes; stderr distinguishes
wrapper diagnostics. See [examples](examples/demo.sh) and [provenance](PROVENANCE.md).

## License and maintenance

Copyright 2026 Aditya Dalmia. Licensed under [Apache-2.0](LICENSE), with
[attribution](NOTICE) and [source provenance](PROVENANCE.md). This is a public
reference implementation, deprecated for new Claude Code integrations as of 2026-09-22. See the [release preparation index](docs/release/README.md),
[contributing guide](CONTRIBUTING.md), and [security contact](SECURITY.md).
