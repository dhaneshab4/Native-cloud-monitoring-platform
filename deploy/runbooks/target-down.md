# Prometheus cannot scrape the target

**Alert:** TargetDown · **Severity:** critical · **Fires when:** up{job="monitoring-app"} == 0 for 1 minute

## Symptoms
Graphs flatline and stop updating. The Prometheus targets page shows the endpoint as DOWN
with a scrape error. Alerting is effectively blind for that instance.

## Diagnosis
Open /targets in the Prometheus UI and read the error text. Connection refused means the
process is not listening; no such host means DNS or service discovery is wrong; a context
deadline means the scrape timed out. Verify reachability from inside the network with
`docker compose exec prometheus wget -qO- http://app:5000/metrics`.

## Resolution
Restart the application if it is genuinely down. If it is running, check that the scrape
target name matches the compose service name rather than the container name, that the port
is correct, and that no network policy blocks traffic between the two.
