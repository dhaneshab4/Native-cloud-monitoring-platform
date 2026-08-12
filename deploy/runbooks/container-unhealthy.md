# Container reported unhealthy

## Symptoms
`docker ps` shows the container as unhealthy, or Kubernetes restarts the pod repeatedly and
it enters CrashLoopBackOff.

## Diagnosis
Read the last probe result with `docker inspect --format "{{json .State.Health}}" monitoring-app`.
The HEALTHCHECK probes /readyz rather than /healthz, so an unhealthy container means metric
collection is failing even though the process still answers HTTP. Read the application logs
for the exception raised by the readiness probe.

## Resolution
Investigate why collection fails: psutil cannot read /proc, the configured DISK_PATH does not
exist in the container, or the filesystem is not mounted. Correct the configuration and
redeploy. Extend start_period rather than the failure threshold if the service is simply slow
to start.
