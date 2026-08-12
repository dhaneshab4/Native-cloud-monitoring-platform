# Verifying image provenance

## Symptoms
An image needs to be confirmed as genuinely produced by this pipeline before it is promoted,
or a supply chain audit requires evidence of build origin.

## Diagnosis
Every image pushed from main is signed with cosign using keyless OIDC and carries an attested
SPDX software bill of materials. Signatures are made against the digest rather than a tag,
because a tag can be repointed at different content after signing.

## Resolution
Run cosign verify with the certificate identity regexp matching the repository and the GitHub
Actions OIDC issuer. To inspect dependencies, download the SBOM attestation and review the
package list. A tag that will not verify against its digest should never be promoted.
