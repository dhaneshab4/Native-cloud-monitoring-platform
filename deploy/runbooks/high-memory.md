# High memory utilisation

**Alert:** HighMemory · **Severity:** warning · **Fires when:** system_memory_percent > 80 for 2 minutes

## Symptoms
Available RAM is shrinking. Swap activity increases, response times become erratic, and in
containers the kernel OOM killer may terminate the process without warning.

## Diagnosis
Rank consumers with `ps aux --sort=-%mem | head`. Inspect `free -h` to separate genuinely
used memory from cache and buffers, which the kernel reclaims on demand. A steadily climbing
system_memory_used_bytes with no plateau indicates a leak rather than load.

## Resolution
Restart the leaking process as an immediate mitigation, then capture a heap profile before
it grows again. Under Kubernetes, confirm the pod memory limit is realistic — a limit below
steady-state usage guarantees repeated OOM kills and CrashLoopBackOff.
