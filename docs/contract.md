# Lock and process contract

Every cooperating writer must use the same persistent lock path on the same host.
The lock is advisory: it does not stop a program that ignores it from editing the
protected resource. It is not a transaction, backup system, or distributed lock.

The wrapper opens a regular lock file without following a final-component symlink,
rejects hardlinked files and special files, opens without blocking on a FIFO, waits with a monotonic deadline, and verifies that the
path still names the acquired inode before starting the command. Use a directory
controlled by the cooperating user; ancestor symlinks and malicious concurrent
directory replacement are outside the trust contract.

The file is never unlinked on release. The wrapper closes its descriptor when the
command exits. The child inherits that same locked open-file description on a descriptor numbered at least 3. Deliberately closed stdin, stdout, or stderr remain closed; the lock never occupies those streams. SIGKILL
of the wrapper therefore leaves the lock held while a child retaining its copy
continues. A command that closes inherited descriptors can weaken that crash guarantee. The wrapper still retains its own descriptor while waiting during normal operation. Commands must not explicitly unlock the inherited description.
Descendants that retain the descriptor can keep the lock after the immediate
command exits; avoid backgrounding unrelated long-lived jobs inside the command.

SIGINT, SIGTERM, and SIGHUP are forwarded to the command's dedicated process group.
The wrapper waits for the immediate command before returning `128 + signal`.
A command that ignores a signal can keep running and keep the lock. There is no
implicit escalation to SIGKILL. If forwarding fails (for example, a command changed credentials), the wrapper reports the failure and keeps waiting with its lock held. When a lock waiter receives those signals, it
exits without launching the command.

Locks are not reentrant. A command that invokes Shell Lock on the same path waits
on its own outer lock and eventually times out. Different paths do not contend.

File descriptors, not process IDs, govern ownership. No PID reuse or stale-owner
deletion algorithm is needed. Power-loss durability of files written by the
command remains the command's responsibility; advisory locking does not imply
`fsync` or an atomic write.
