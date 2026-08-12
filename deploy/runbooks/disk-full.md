# Disk almost full

**Alert:** DiskAlmostFull · **Severity:** critical · **Fires when:** system_disk_percent > 85 for 5 minutes

## Symptoms
Writes begin failing. Logging stops, databases refuse transactions, and the container may
be unable to write to its temporary directory.

## Diagnosis
Find the largest directories with `du -xh / | sort -rh | head -20`. Check inode exhaustion
separately using `df -i` — a filesystem can be full of tiny files while reporting free bytes.
Deleted files still held open by a running process are a classic cause of space that `du`
cannot see; find them with `lsof +L1`.

## Resolution
Rotate and compress logs, prune unused container images and volumes with `docker system prune`,
and clear package manager caches. Restart any process holding deleted file handles. Long term,
configure logrotate and set a retention policy on the Prometheus time series database.
