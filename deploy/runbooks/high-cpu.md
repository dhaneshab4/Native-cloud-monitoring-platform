# High CPU utilisation

**Alert:** HighCPU · **Severity:** warning · **Fires when:** system_cpu_percent > 80 for 2 minutes

## Symptoms
Sustained processor saturation. Request latency rises, the dashboard shows a red CPU gauge,
and the application reports degraded status.

## Diagnosis
Identify the busiest processes with `top -o %CPU` or `ps aux --sort=-%cpu | head`. Check
whether load average exceeds the core count — a 1-minute load above the vCPU count means
work is queueing. Compare against the utilisation timeseries in Grafana to distinguish a
spike from a plateau.

## Resolution
A short spike from a batch job or deploy usually needs no action. A sustained plateau means
either a runaway process to restart, or genuine capacity exhaustion requiring more vCPU or
horizontal scaling. Raise CPU_WARN_PERCENT only if the current threshold is provably wrong
for this workload.
