# CI pipeline failing

## Symptoms
The workflow reports a red check on a commit. Downstream jobs are skipped because the build
job depends on lint, tests, and the configuration validation jobs.

## Diagnosis
Identify which job failed first — later failures are usually consequences. Lint failures are
formatting or rule violations. Test failures name the assertion. The Prometheus and Kubernetes
validation jobs fail when configuration is syntactically valid but semantically wrong, such as
a rule file that cannot be loaded from the path the config references.

## Resolution
Reproduce locally with the same command the pipeline runs before pushing a speculative fix.
Formatting failures are resolved with `make fmt`. Remember that run blocks execute under
`bash -e`, so a test command returning non-zero terminates the step immediately.
