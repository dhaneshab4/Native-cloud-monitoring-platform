# Rolling back a bad release

## Symptoms
Errors, latency, or failed health checks begin immediately after a deploy. The previous
version was healthy on the same infrastructure.

## Diagnosis
Compare the running image digest against the previous release. Every image is tagged with the
short commit SHA, so the offending change can be identified directly. Confirm the failure
correlates with the deploy time rather than with a traffic change.

## Resolution
Roll forward to the last known good digest rather than rebuilding from source, which is faster
and removes build variability. Under Kubernetes use `kubectl rollout undo deployment/monitoring-app`.
The deployment sets maxUnavailable to zero, so a rollback never reduces capacity below the
current replica count. Verify the signature with cosign before promoting any image.
