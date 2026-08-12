# Rotating credentials

## Symptoms
A token has leaked, expired, or is due for scheduled rotation. Authentication begins failing
against the registry or a deployment target.

## Diagnosis
Determine the scope of the exposed credential and where it is consumed — repository secrets,
the systemd EnvironmentFile, or a Kubernetes secret. Any credential committed to git or pasted
into a chat, ticket, or log must be treated as public regardless of how briefly it was visible.

## Resolution
Revoke first and reissue second; an exposed credential that has been revoked is harmless.
Prefer keyless OIDC where the platform supports it, since there is no long lived secret to
rotate at all. Never store a token in the remote URL, where it persists in git config.
