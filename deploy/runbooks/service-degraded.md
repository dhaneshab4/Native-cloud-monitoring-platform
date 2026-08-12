# Application reporting degraded status

**Alert:** ServiceDegraded · **Severity:** warning · **Fires when:** system_status == 0 for 1 minute

## Symptoms
The service answers requests but /api/metrics returns HTTP 503 and the status pill on the
dashboard reads DEGRADED. At least one configured threshold has been breached.

## Diagnosis
Fetch /api/metrics and read the breaches array — it names the specific threshold and the
observed value. This distinguishes a genuine resource problem from a misconfigured limit.
Confirm the thresholds in effect by checking the startup log line that prints them.

## Resolution
Degraded is a signal, not a fault in itself: resolve the underlying resource pressure using
the CPU, memory or disk runbook the breach points at. If the threshold itself is wrong for
this host, correct CPU_WARN_PERCENT, MEM_WARN_PERCENT or DISK_WARN_PERCENT and redeploy.
