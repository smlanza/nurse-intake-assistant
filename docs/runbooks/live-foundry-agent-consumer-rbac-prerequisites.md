# Live Foundry Agent Consumer RBAC Prerequisites

## 1. Scope

The normal live Consumer RBAC workflow is now the guided daily coordinator:

```bash
.venv/bin/python scripts/rebuild_daily_azure_environment.py \
  --config .env.daily-azure.local --live --json
```

It discovers the current Web App system identity and approved Foundry project
scope, resolves the fixed Consumer role, checks existing assignments, prompts
for the exact assignment only when mutation is required, immediately rereads
and compares the approved identity and scope evidence, deploys through the
constrained repository Bicep boundary, verifies read-only, and continues hosted validation.
The manual commands below are troubleshooting and recovery procedures.

Before execution, the operator must explicitly approve one resource group,
Foundry account, child project, model deployment, and Linux Web App parameter
set. Do not infer replacements from documentation, naming conventions, Azure
history, or prior transcripts, and do not treat disposable names as defaults.

It does not provision an agent, invoke a model or agent, acquire a
managed-identity token, change production providers, send notifications, or
establish production clinical readiness. Mock-safe providers, suppressed
hosted notifications, and mandatory human nurse review remain unchanged.

## 2. Azure Authentication

The operator must authenticate and inspect the active account before any
automated live Azure operation:

```bash
az login
az account show --output json
```

Manually confirm the intended subscription. Do not copy subscription or tenant
identifiers into documentation, logs, commits, or AI responses. If login is
missing or expired, stop immediately with a sanitized `prerequisite_missing`
result. Do not retry Azure commands or attempt alternate credentials.

## 3. Safe Shell Variables

Use placeholders or fictional disposable values only:

```bash
export rg="<existing-disposable-resource-group>"
export loc="centralus"
export web_app_name="<existing-fictional-linux-web-app>"
export base_url="https://${web_app_name}.azurewebsites.net"
export foundry_project_endpoint="<verified-project-endpoint>"
export foundry_account_name="<existing-foundry-account-name>"
export foundry_project_name="<existing-foundry-project-name>"
export model_deployment_name="<existing-model-deployment>"
```

Never hard-code secrets, credentials, subscription or tenant IDs, principal
IDs, complete Azure resource IDs, identity headers, real patient data, or real
contact information.

## 4. Foundry Prerequisite Deployment Through Authoritative Bicep

The only authoritative boundaries for this prerequisite are:

- `infra/foundry-only.bicep`
- `infra/modules/foundry.bicep`
- `infra/foundry-only.bicepparam`
- `scripts/deploy_foundry_infra.py`
- `scripts/verify_foundry_infra.py`

The operator-local `infra/foundry-only.bicepparam` must remain ignored and
uncommitted. Compile and check locally, then preview against the existing
disposable group:

```bash
set -o pipefail

az bicep build \
  --file infra/foundry-only.bicep \
  --stdout > /dev/null

az bicep build-params \
  --file infra/foundry-only.bicepparam \
  --stdout > /dev/null

python scripts/deploy_foundry_infra.py \
  --mode foundry-only \
  --parameters infra/foundry-only.bicepparam \
  --resource-group "$rg" \
  --location "$loc" \
  --check

python scripts/deploy_foundry_infra.py \
  --mode foundry-only \
  --parameters infra/foundry-only.bicepparam \
  --resource-group "$rg" \
  --location "$loc" \
  --what-if \
  --json |
  python -m json.tool
```

Manually review the sanitized counts. Stop for deletes, unsupported or unknown
changes, destructive replacement, or unrelated changes. Only after a safe
preview may the operator request deployment:

```bash
set -o pipefail

python scripts/deploy_foundry_infra.py \
  --mode foundry-only \
  --parameters infra/foundry-only.bicepparam \
  --resource-group "$rg" \
  --location "$loc" \
  --live \
  --json |
  python -m json.tool

python scripts/verify_foundry_infra.py \
  --resource-group "$rg" \
  --project-endpoint "$foundry_project_endpoint" \
  --model-deployment-name "$model_deployment_name" \
  --json |
  python -m json.tool
```

Current read-only proof must verify the AIServices account, child Foundry
project, valid project endpoint contract, model deployment, and successful
provisioning state. Historical deployment evidence is insufficient.

`CustomDomainInUse` is a deterministic naming conflict. Select a new safe
`environmentName` in the ignored Bicep parameter file, then rerun validation
and what-if. Do not repeatedly retry the same unavailable name.

## 5. Linux Web App Deployment And Verification

The authoritative application boundaries are:

- `infra/main.bicep`
- `infra/modules/web-app.bicep`
- `scripts/deploy_web_app_infra.py`
- `scripts/verify_web_app_configuration.py`
- `scripts/package_web_app.py`
- `scripts/deploy_web_app_code.py`
- `scripts/verify_web_app_readiness.py`

Reuse an already verified Web App; do not redeploy it merely because this
runbook is being executed. If the app is absent, use this exact staged flow:

```text
Bicep compile
-> infrastructure check
-> infrastructure what-if
-> manual review
-> explicit infrastructure deployment
-> read-only configuration verification
-> deterministic package
-> explicit code deployment
-> read-only hosted readiness verification
```

Compile and run the offline check:

```bash
set -o pipefail

az bicep build --file infra/main.bicep --stdout > /dev/null

python scripts/deploy_web_app_infra.py \
  --check \
  --resource-group "$rg" \
  --location "$loc" \
  --environment-name demo \
  --project-name nurse-intake \
  --web-app-name "$web_app_name" \
  --json |
  python -m json.tool
```

Use the same arguments for separate `--what-if` and `--live` commands. Review
the sanitized preview before live deployment. Then verify configuration,
package deterministically, deploy code explicitly, and verify readiness:

```bash
set -o pipefail

python scripts/verify_web_app_configuration.py \
  --live \
  --json \
  --resource-group "$rg" \
  --web-app-name "$web_app_name" |
  python -m json.tool

python scripts/package_web_app.py --package --json |
  python -m json.tool

python scripts/deploy_web_app_code.py \
  --live \
  --json \
  --resource-group "$rg" \
  --web-app "$web_app_name" |
  python -m json.tool

python scripts/verify_web_app_readiness.py \
  --base-url "$base_url" \
  --live \
  --json |
  python -m json.tool
```

Current proof must cover an existing running Linux Web App, system-assigned
identity, expected Python runtime and startup command, remote build,
HTTPS/TLS/FTPS safety settings, mock-safe providers, suppressed hosted
notifications, and passing `/health`, `/version`, and `/demo/status`.

## 6. RBAC Project Scope And Preview Review

The assignment verifier must resolve the exact project with `az
cognitiveservices account project show`, project only its name and ID, accept
either the project leaf name or qualified `<account>/<project>` name, and use
Azure's returned nonblank ARM ID only internally. It must never concatenate a
project resource ID. A missing, malformed, differently named, or differently
scoped response stops before role-assignment reads.

The Bicep contract uses the authoritative Foundry API version, an existing
AIServices account, its existing child project with the account as parent and
the project leaf as name, and one deterministic Consumer assignment scoped to
that exact project symbol. Approval requires exactly one Create whose
subscription, resource group, account/project parent, project scope,
deterministic assignment name, principal, fixed role definition, multiplicity,
and repository boundary all match. Unsupported, missing identity fields,
duplicates, or any false exact-match flag stop without approval. After approval,
fresh read-only evidence must remain equivalent at every approved identity
boundary; otherwise `approval_evidence_stale` requires a fresh run. The Bicep
entry point accepts approved principal/project/assignment values, independently
resolves the current resources, and fails validation on mismatch.

Latest execution evidence: current Foundry, Web App configuration/identity, and
readiness verification each passed once. The offline RBAC check passed. One
fresh what-if reported ten ignored, one expected Unsupported role assignment,
and zero creates, modifies, deletes, deploys, no-changes, or unrelated changes.
After explicit approval, Azure accepted the project-scoped Foundry Agent
Consumer assignment deployment. A separate read-only verifier proved exactly
one direct assignment for the Web App system identity at the exact Foundry
project scope. No retry or polling occurred. Managed-identity token acquisition,
hosted Foundry metadata access, and agent invocation remain unproven.

## 7. Fail-Fast And Bounded Completion Policy

This runbook enforces fail-fast execution. Missing authentication or prerequisite
resources and deterministic configuration, naming, policy, quota, or
authorization failures are not transient application defects.

- Stop after the first failed prerequisite or deterministic failure. Do not retry
  it without an operator correction.
- A repository-owned live deployment command may block until Azure returns.
- After Azure accepts an asynchronous deployment, use at most one
  repository-approved bounded completion check, and only when this runbook
  explicitly requires it for that command.
- General-purpose shell polling loops, repeated sleeps, indefinite waits, and
  improvised repeated verifier calls are prohibited.
- Do not substitute portal-only resources, duplicate Bicep, historical
  evidence, alternate credentials, or ad hoc Azure provisioning.
- Begin a new attempt only after the operator corrects the stated prerequisite.
- Keep cleanup manual and explicit.

Read-only verification remains a distinct stage after deployment completion.
The required stage order is: check -> what-if -> manual review -> live
deployment -> optional explicitly required bounded completion check -> read-only
verification.

Reconciliation note: the previous execution used `az deployment group wait`,
shell loops, repeated status checks, `sleep`, and repeated readiness verification.
Those bounded polling actions occurred; they are not evidence of RBAC completion
and are prohibited as improvised completion handling in future slices.

## 8. Completion Checklist

- [ ] Azure login verified.
- [ ] Intended Azure account and complete slice parameter set manually confirmed.
- [ ] Foundry Bicep compiled.
- [ ] Foundry infrastructure currently verified.
- [ ] Linux Web App configuration currently verified.
- [ ] Web App system identity currently verified.
- [ ] Web App readiness currently verified.
- [ ] RBAC Bicep compiled.
- [ ] Fictional names and data only.
- [ ] No secrets or identifiers committed.
