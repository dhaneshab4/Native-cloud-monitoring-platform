# Service will not start under systemd

## Symptoms
`systemctl start monitoring-app` fails, or the unit enters a restart loop with Restart=always
repeatedly triggering.

## Diagnosis
Read the journal with `journalctl -u monitoring-app -n 50 --no-pager`. Permission denied on a
path is usually the hardening block: ProtectSystem=strict makes most of the filesystem read
only, and SystemCallFilter restricts syscalls to the system-service set. A missing environment
file referenced without a leading dash also aborts startup.

## Resolution
Grant the narrowest exception needed, such as ReadWritePaths for a specific directory, rather
than removing the hardening. Confirm the service user exists and owns the working directory,
then run `systemctl daemon-reload` after editing the unit.
