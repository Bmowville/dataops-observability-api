# Azure infrastructure

This directory defines the Azure production deployment for the DataOps Observability API. It uses subscription-scope Bicep to create one resource group, an Azure Container Apps environment, a manual migration job, and—only after the migration succeeds—the public API.

## Files

- `main.bicep` orchestrates subscription- and resource-group-scoped resources.
- `main.bicepparam` reads deployment-specific and secret values from process environment variables.
- `modules/container-apps-platform.bicep` creates the Consumption environment and migration job.
- `modules/api.bicep` creates the scale-to-zero public API.
- `release.ps1` compiles, previews, or executes the guarded release sequence.

## Safety model

The template defaults `deployApi` to `false`. Creating the manual job does not run it, so the release script deliberately separates deployment into these stages:

1. Deploy the resource group, Container Apps environment, and migration job.
2. Start one migration execution and wait for its exact status to become `Succeeded` with a non-null Azure `endTime`.
3. Deploy the API using the same immutable `v0.3.0` image digest.
4. Smoke-test `/live`, `/health`, and `/api/v1/pipelines` over HTTPS.

The script stops before stage 3 if the migration fails, stops, or times out. `-Mode Deploy` is additionally locked behind `-ConfirmDeployment`.

On the first release, `deployApi=false` guarantees that no API resource is created before migration success. On later incremental releases, Azure leaves the existing healthy API revision running while the migration executes. Database migrations must therefore remain backward-compatible with the currently deployed revision; use a separately reviewed maintenance procedure for a breaking schema change.

The workflow refuses to start a migration while another execution has no Azure `endTime`. After starting a migration, any exceptional exit before a terminal `endTime` triggers a stop request for that exact execution and a bounded confirmation poll. If the start request fails or returns no execution identifier, acceptance is treated as ambiguous: the script boundedly discovers executions that appeared after the attempt, stops only one uniquely attributable active execution, records the result in `migration-start-ambiguity.json`, and never deploys the API from that attempt. Do not retry until every discovered candidate and every nonterminal execution is terminal. An unconfirmed stop is recorded as `StopUnconfirmed`. Smoke tests use bounded retries and verify liveness, database readiness, a public read endpoint, and rejection of an anonymous write. The overall release is not atomic: if Azure creates the API but the final smoke tests fail, inspect the active revision and roll back or disable ingress before advertising the endpoint.

`WhatIf` and `Deploy` take one checkout-wide exclusive file lock under `infra/.artifacts`, protecting the shared review artifacts even when two subscriptions are targeted. The lock is released automatically when the PowerShell process exits. It is not a distributed lock: separate worktrees, developer machines, and CI runners must use an external concurrency group or a single release operator. The script also checks for active executions immediately before and after starting its exact migration, but that check does not replace cross-runner serialization.

Every Azure CLI child has separate stdout and stderr capture and a bounded process timeout. On timeout, the wrapper requests whole-process-tree termination and refuses to treat termination as confirmed while redirected descendant handles remain open. A subscription deployment submission or wait failure is acceptance-ambiguous: the script repeatedly probes and cancels the exact known deployment name, then boundedly confirms `Succeeded`, `Failed`, or `Canceled`. If the exact name cannot be found or cancellation remains unconfirmed, do not retry until that exact name has been checked after Azure propagation.

The release script records the migration execution identifier and final status without persisting container output. If migration logs are needed for diagnosis, stream them interactively and review them for sensitive values before retaining any excerpt. Files under `infra/.artifacts` are local release-control records and must remain uncommitted.

## Prerequisites

- PowerShell 7
- Azure CLI 2.53.0 or later
- Bicep CLI 0.22 or later (`v0.45.15` is pinned in CI)
- An explicit Azure subscription ID for preview or deployment
- `Microsoft.App` already registered

## Required process environment variables

Set these only in the local shell or an approved secret store. Do not commit them, paste them into issues, or include them in screenshots.

| Variable | Purpose |
| --- | --- |
| `NEON_POOLED_DATABASE_URL` | Neon pooled URL for the API; hostname contains `-pooler`. |
| `NEON_DIRECT_DATABASE_URL` | Neon direct URL for Alembic migrations. |
| `DATAOPS_INGESTION_API_KEY` | Production write/ingestion key, at least 24 characters. |
| `AZURE_SUBSCRIPTION_ID` | Required explicit subscription for preview and deployment. Active-subscription fallback is disabled. |

Both Neon URLs must target the same project, branch, database, and user and retain `sslmode=require&channel_binding=require`.

## Commands

Run local compilation only:

```powershell
./infra/release.ps1 -Mode Build
```

Build mode needs no production secrets; it compiles the parameter file with temporary synthetic values and restores the caller's environment.

Preview the Azure resources without deploying:

```powershell
./infra/release.ps1 -Mode WhatIf
```

A successful preview saves the redacted `FullResourcePayloads` result to `infra/.artifacts/what-if-output.json` and an ignored version-3 review manifest beside it. Review the detailed output before deployment. The manifest binds `DeploymentPrefix`, subscription, location, salted nonreversible fingerprints of the three secret deployment inputs, the detailed output hash, the timestamp, and hashes of every infrastructure file. It never stores database URLs or the ingestion key in plaintext. Deployment requires a matching artifact and manifest less than 24 hours old, so an input, preview, prefix, or infrastructure-file change forces a new preview.

After reviewing the preview, run the guarded deployment:

```powershell
./infra/release.ps1 -Mode Deploy -ConfirmDeployment
```

When `-DeploymentPrefix` is omitted from Deploy, the script automatically reuses the timestamped prefix saved by WhatIf. If a prefix is supplied explicitly, it must exactly match the reviewed manifest.

The script checks that `Microsoft.App` is already registered; it never registers providers itself.
