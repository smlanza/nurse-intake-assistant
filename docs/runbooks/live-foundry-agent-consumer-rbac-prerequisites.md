# Live Foundry Agent Consumer RBAC

## 1. Authoritative Daily Workflow

Start with the daily coordinator:

```bash
set -o pipefail

.venv/bin/python scripts/rebuild_daily_azure_environment.py \
  --config .env.daily-azure.local \
  --live \
  --json |
python -m json.tool
```

Continue only when the coordinator reports `READY`. `READY` means the
coordinator has completed its application-hosting boundary and written the
matching readiness receipt. It does not mean that the coordinator deployed
Consumer RBAC, acquired a managed-identity token, ran the hosted WebJob, or
invoked the agent.

Run the one-command Consumer RBAC workflow immediately after `READY`:

```bash
set -o pipefail

.venv/bin/python scripts/deploy_foundry_agent_consumer_rbac.py \
  --config .env.daily-azure.local \
  --live \
  --json |
python -m json.tool
```

The RBAC command automatically loads the matching coordinator readiness
receipt and uses its effective Foundry account name. The requested account
name remains in the receipt for auditability when the coordinator recovered
from an account-name conflict. Do not manually export, copy, derive, or
reconstruct any of these values for the daily path:

- resource group;
- location;
- Web App name;
- Foundry account name;
- Foundry project name;
- Foundry project endpoint;
- principal ID;
- scope;
- role definition;
- assignment ID.

A missing, stale, configuration-mismatched, or account-mismatched receipt
fails closed. Regenerate the environment with the coordinator; do not repair
the handoff by editing the receipt or passing manually reconstructed values.
Starting any new coordinator live run atomically publishes a
configuration-bound revoked run epoch before cleanup or its first Azure read.
The older `READY` handoff is then unloadable even if physical receipt deletion
fails. Failed, blocked, declined, or interrupted runs leave it revoked; only
complete hosted readiness atomically publishes a matching `ready` epoch.

## 2. Completion Contract And Boundaries

The focused command performs an immediate read-only assignment check at the
exact Foundry project scope. It accepts only the Web App's current
system-assigned principal, the fixed Foundry Agent Consumer role, and the
repository's deterministic direct assignment.

Successful reuse has these decisive JSON fields:

```json
{
  "ok": true,
  "category": "success",
  "operation": "deploy_foundry_agent_consumer_rbac",
  "mode": "live",
  "rbac_handoff_validated": true,
  "assignment_reused": true,
  "assignment_verified": true,
  "azure_operation_attempted": true,
  "azure_mutation_made": false,
  "deployment_request_accepted": false
}
```

This result means exactly one matching direct assignment already exists and
was reused successfully. No deployment request was submitted.

When the exact assignment is missing, the command first runs a fresh sanitized
What-If. It accepts only either one exact Create, or the known ten exact Ignore
records plus one exact Unsupported assignment record whose identity, project
parent, scope, principal, fixed role, deterministic assignment name, and
multiplicity are all independently proved. It then prompts once. After
approval, it rereads the effective account, principal, scope, role, and
assignment evidence; any change fails with `approval_evidence_stale` before
deployment.

Successful creation has these decisive JSON fields:

```json
{
  "ok": true,
  "category": "success",
  "operation": "deploy_foundry_agent_consumer_rbac",
  "mode": "live",
  "rbac_handoff_validated": true,
  "assignment_reused": false,
  "assignment_verified": true,
  "azure_operation_attempted": true,
  "azure_mutation_made": true,
  "deployment_request_accepted": true
}
```

This result means the operator approved one exact assignment, the evidence was
still fresh, Azure accepted the repository-owned
`infra/foundry-agent-consumer-rbac.bicep` deployment, and the immediate
read-only verifier proved exactly one matching direct assignment. Azure
acceptance without final verification is returned as
`consumer_rbac_verification_failed`, never as success.

The focused command rejects inherited-only access, duplicate matching
assignments, mismatched principal/role/scope evidence, and stale coordinator
handoffs. Its handoff failures use the current categories
`invalid_configuration`, `rbac_handoff_invalid`,
`rbac_handoff_account_mismatch`, or
`rbac_handoff_azure_scope_mismatch`. The guarded creation transaction also
uses `consumer_rbac_preview_unsafe`, `consumer_rbac_operator_declined`,
`approval_evidence_stale`, and `consumer_rbac_verification_failed`.
Deployment-boundary failures retain implementation categories such as
`invalid_request`, `template_contract_invalid`, `azure_cli_unavailable`, and
`deployment_failed`; none is a successful outcome.

This command stops at direct project-scoped Consumer RBAC. It does not:

- invoke the agent or a model;
- acquire a managed-identity token;
- run the hosted WebJob;
- perform subsequent hosted managed-identity, metadata, or invocation
  validation;
- change providers, send notifications, or establish production clinical
  readiness.

Those are separate later workflows. Mock-safe providers, suppressed hosted
notifications, and mandatory human nurse review remain unchanged.

## 3. Troubleshooting And Recovery

Everything below is recovery material, not a normal daily prerequisite after
the coordinator has reported `READY`. Use it only to diagnose the failure
category or restore a prerequisite. Do not combine these commands into an
alternate daily path.

### 3.1 Azure Authentication Recovery

If authentication is missing or expired, authenticate and inspect the active
account:

```bash
az login
az account show --output json
```

Manually confirm the intended subscription. Do not copy subscription or tenant
identifiers into documentation, logs, commits, or AI responses. Stop after an
authentication failure; do not try alternate credentials or repeat Azure
commands without an operator correction.

### 3.2 Recovery-Only Shell Values

Only a manual prerequisite recovery procedure may need shell values. Use
placeholders or fictional disposable values:

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
contact information. These variables are diagnostic inputs only; they do not
replace the coordinator receipt consumed by the focused RBAC command.

### 3.3 Foundry Prerequisite Recovery

The authoritative Foundry prerequisite boundaries are:

- `infra/foundry-only.bicep`;
- `infra/modules/foundry.bicep`;
- `infra/foundry-only.bicepparam`;
- `scripts/deploy_foundry_infra.py`;
- `scripts/verify_foundry_infra.py`.

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

Review the sanitized counts. Stop for deletes, unsupported or unknown changes,
destructive replacement, or unrelated changes. Only after a safe preview may
the operator request recovery deployment:

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

The deployment wrapper classifies `CustomDomainInUse` as a deterministic
naming conflict only from one structured Azure error whose target is the exact
configured `Microsoft.CognitiveServices/accounts` resource in the requested
resource group. Malformed, ambiguous, wrong-resource, wrong-name, or
human-readable substring-only errors remain ordinary preview or deployment
failures. For a proved conflict, select a new safe `environmentName` in the
ignored Bicep parameter file, then rerun validation and What-If. Do not
repeatedly retry the same unavailable name.

### 3.4 Linux Web App Prerequisite Recovery

The authoritative application boundaries are:

- `infra/main.bicep`;
- `infra/modules/web-app.bicep`;
- `scripts/deploy_web_app_infra.py`;
- `scripts/verify_web_app_configuration.py`;
- `scripts/package_web_app.py`;
- `scripts/deploy_web_app_code.py`;
- `scripts/verify_web_app_readiness.py`.

Reuse an already verified Web App; do not redeploy it merely because this
runbook is being executed. If the app is absent, preserve this stage order:

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

### 3.5 RBAC Scope Resolution And Preview Recovery

The assignment verifier resolves the exact project with `az
cognitiveservices account project show`, projects only its name and ID, accepts
either the project leaf name or qualified `<account>/<project>` name, and uses
Azure's returned nonblank ARM ID only internally. Never concatenate a project
resource ID. A missing, malformed, differently named, or differently scoped
response stops before role-assignment reads.

The Bicep contract uses an existing AIServices account, its existing child
project with the account as parent and the project leaf as name, and one
deterministic Consumer assignment scoped to that exact project symbol. A safe
preview must describe only the expected assignment boundary with the approved
principal, fixed role definition, deterministic assignment name, and exact
project scope. Deletes, unrelated changes, unsupported topology, missing
identity evidence, duplicates, or any false exact-match flag stop the recovery
procedure.

Fresh read-only identity and scope evidence must remain equivalent at every
approved boundary. Drift requires a new coordinator run and a new matching
receipt; never reuse historical evidence or manually patch the receipt.

### 3.6 Fail-Fast Recovery Policy

- Stop after the first failed prerequisite or deterministic failure.
- Do not retry missing authentication, naming, configuration, policy, quota,
  authorization, duplicate-assignment, inherited-only, or stale-handoff
  failures without an operator correction.
- Do not use general-purpose polling loops, repeated sleeps, indefinite waits,
  or improvised repeated verifier calls.
- Do not substitute portal-created assignments, duplicate Bicep, historical
  evidence, alternate credentials, or ad hoc Azure provisioning.
- Keep cleanup manual and explicit.
- After correcting the stated prerequisite, restart with the coordinator
  command in Section 1 and require a fresh `READY` receipt.

### 3.7 Recovery Checklist

- [ ] The first failure category was recorded without sensitive identifiers.
- [ ] Azure login and intended account were confirmed if authentication failed.
- [ ] Foundry infrastructure is currently verified if that prerequisite failed.
- [ ] Linux Web App configuration, system identity, and readiness are currently
      verified if that prerequisite failed.
- [ ] No inherited assignment, duplicate assignment, or mismatched role/scope
      was accepted as direct project-scoped access.
- [ ] The coordinator produced a new matching `READY` receipt after recovery.
- [ ] No secrets, real identifiers, real patient data, or real contact
      information were committed.
