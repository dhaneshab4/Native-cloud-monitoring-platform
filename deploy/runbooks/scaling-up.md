# Adding capacity

## Symptoms
Resource utilisation is legitimately high because demand has grown. Restarting processes does
not help and no leak is present.

## Diagnosis
Confirm the plateau is sustained rather than a spike by reviewing the utilisation timeseries
over hours rather than minutes. Check whether load is evenly distributed across replicas: an
uneven distribution points at a routing problem rather than a capacity one.

## Resolution
Increase the replica count in the Kubernetes deployment, or raise the CPU and memory limits if
individual requests are the bottleneck. The PodDisruptionBudget keeps at least one replica
available during the rollout. Review resource requests as well as limits, since requests drive
scheduling decisions.
