# Live Hosted Foundry Agent Verification Prerequisites

## 1. Purpose and scope

This runbook prepares only the future live proof that an already-deployed Linux
Web App, using only its system-assigned managed identity, can perform the
repository's existing read-only prompt-agent metadata verification against one
operator-approved Foundry project and exact immutable prompt-agent version.
Completing this runbook does not authorize or perform that proof.

The packaged operation reads prompt-agent metadata. It uses the Linux Web App
system-assigned managed identity and does not invoke the agent or model, submit
patient or fictional intake text, persist a case, or send or record
notifications. It does not alter infrastructure, RBAC, agent definitions,
application configuration, or hosted code. It does not prove inference,
application correctness beyond the metadata contract, or production readiness.

Metadata verification and invocation remain separate. The fixed-fictional-data
invocation is a later, independently reviewed and authorized slice.

## 2. Authentication and subscription gate

The operator begins the future prerequisite workflow by authenticating and
performing one current-account check:

```bash
az login

az account show \
  --query "{subscription:name,state:state,isDefault:isDefault}" \
  --output table
```

Confirm the intended subscription by name, confirm its state is `Enabled`, and
confirm it is the intended default selection. Stop if any of those checks fail
or are ambiguous. Do not try alternate credentials.

Do not record subscription IDs, tenant IDs, access tokens, credentials, or
complete resource IDs in this runbook, prompts, commits, or captured evidence.

## 3. Exact operator-approved inventory

Before any current prerequisite verification, the operator must record a
sanitized exact value for every item below:

- [ ] Resource group
- [ ] Foundry AIServices account
- [ ] Foundry child project
- [ ] Model deployment
- [ ] Prompt-agent name
- [ ] Exact immutable prompt-agent version
- [ ] Linux Web App
- [ ] Hosted application origin
- [ ] Expected Foundry project endpoint
- [ ] Expected stable per-agent endpoint or repository-owned equivalent

Every value must come from fresh repository-owned verification or an explicit
operator-approved parameter source. Historical output, portal screenshots,
truncated portal names, prior conversations, inferred resource groups or other
inferred resource names, and assumed defaults are insufficient. Resource
existence alone is not current usability proof.

The inventory and evidence must remain sanitized. Record names only where this
runbook asks for names; never capture identity values, tokens, credentials,
complete resource IDs, raw CLI or SDK output, or endpoints containing secrets.

## 4. Authoritative repository ownership

Use the existing repository boundaries below. Do not duplicate Bicep, create an
alternate provisioner, or substitute portal-only instructions.

| Concern | Authoritative repository boundary |
|---|---|
| Foundry infrastructure deployment and verification | `infra/foundry-only.bicep`, `infra/modules/foundry.bicep`, `scripts/deploy_foundry_infra.py`, and `scripts/verify_foundry_infra.py` |
| Prompt-agent lifecycle and immutable-version verification | `src/app/services/foundry_agent_deployment.py`, `scripts/deploy_foundry_agent.py`, `src/app/services/foundry_agent_verification.py`, and `scripts/verify_foundry_agent.py` |
| Linux Web App infrastructure | `infra/main.bicep`, `infra/modules/web-app.bicep`, `src/app/services/web_app_infra_deployment.py`, and `scripts/deploy_web_app_infra.py` |
| Hosted application configuration verification | `src/app/services/web_app_hosting_contract.py`, `src/app/services/web_app_configuration_verification.py`, and `scripts/verify_web_app_configuration.py` |
| Deterministic packaging and code deployment | `src/app/services/web_app_package.py`, `scripts/package_web_app.py`, and `scripts/deploy_web_app_code.py` |
| Hosted readiness verification | `src/app/services/web_app_readiness_verification.py` and `scripts/verify_web_app_readiness.py` |
| Project-scoped Consumer RBAC deployment and exact direct-assignment verification | `infra/foundry-agent-consumer-rbac.bicep`, `infra/modules/foundry-agent-consumer-rbac.bicep`, `src/app/services/foundry_agent_consumer_rbac_deployment.py`, `scripts/deploy_foundry_agent_consumer_rbac.py`, `src/app/services/foundry_agent_consumer_rbac_verification.py`, and `scripts/verify_foundry_agent_consumer_rbac.py` |
| Packaged hosted Foundry metadata verification | `src/app/services/hosted_foundry_agent_verification.py` and `src/app/operations/verify_hosted_foundry_agent.py` |

Infrastructure deployment, prompt-agent lifecycle, Web App deployment,
configuration verification, packaging, code deployment, readiness, RBAC,
hosted metadata verification, and invocation are distinct approval boundaries.

## 5. Required current proof

Before the future hosted operation may run, obtain fresh, successful, sanitized
evidence for every applicable prerequisite:

1. `scripts/verify_foundry_infra.py` proves the approved AIServices account,
   child project, project-endpoint contract, model deployment, and successful
   states.
2. `scripts/verify_foundry_agent.py` proves the exact prompt-agent immutable
   version through a read-only live verification.
3. The same agent metadata proof shows the Responses protocol and routing that
   resolves exclusively to the approved immutable version.
4. The exact model deployment and repository-centralized instructions match
   the immutable version definition.
5. `scripts/verify_web_app_configuration.py` proves the approved Linux Web App,
   complete Bicep-owned safe configuration, and system-assigned identity.
6. The current deterministic package is the package used by the most recent
   separately approved code deployment; request acceptance alone is not proof.
7. `scripts/verify_web_app_readiness.py` freshly proves `/health`, `/version`,
   and `/demo/status` for the approved hosted application origin.
8. The system-assigned identity is present and usable as the intended identity;
   no user-assigned identity may substitute for it.
9. `scripts/verify_foundry_agent_consumer_rbac.py` freshly proves exactly one
   direct Foundry Agent Consumer assignment for that Web App identity at the
   exact Foundry child-project scope.
10. Every non-secret setting required by the packaged hosted verifier is
    available through a repository-owned deployment/configuration path.

All proof must describe current usability, not merely resource existence,
deployment acceptance, RBAC existence, token construction, or client
construction. Missing, stale, or historical evidence fails the gate.

## 6. Hosted execution mechanism and configuration gates

The package allowlist currently includes the hosted verification service and
operation. The deployed Web App startup command, however, starts only the
FastAPI application through uvicorn. The repository currently provides no
repository-owned execution mechanism that launches the packaged operation
inside the Linux Web App as one bounded operator-reviewed execution. The
operation is not an HTTP route, startup task, WebJob, or other deployed control
surface. This is a blocking prerequisite and requires a separate implementation
slice before live hosted metadata verification can be authorized.

Do not fill that gap with interactive Kudu manipulation, improvised SSH or
shell commands, a portal console, a temporary startup-command change, an ad hoc
HTTP endpoint, a new WebJob, local execution masquerading as hosted proof, or
any Azure CLI command that mutates application configuration.

The operation also requires these five non-secret values:

- `AZURE_AI_FOUNDRY_AGENT_PROJECT_ENDPOINT`
- `AZURE_AI_FOUNDRY_AGENT_ENDPOINT`
- `AZURE_AI_FOUNDRY_AGENT_NAME`
- `AZURE_AI_FOUNDRY_AGENT_VERSION`
- `AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT_NAME`

The current Web App Bicep and shared hosted-configuration contract supply only
the seven mock-safe provider/notification settings plus the remote-build
setting. They do not supply these five verifier values through a
repository-owned configuration boundary. This is a second blocking prerequisite
and requires a separate implementation slice. Do not use manual environment-
variable injection or ad hoc App Service setting changes as a substitute.

These blockers mean the repository is not currently ready for the future live
hosted metadata-verification execution. The packaged command and offline tests
remain valid, but packaging alone does not prove hosted executability or
configuration availability.

## 7. Approved stage sequence

The future workflow must preserve this order, with fresh sanitized evidence and
manual review between stages:

```text
Operator authentication/current account
-> exact approved inventory
-> current Foundry infrastructure verification
-> exact immutable prompt-agent version verification
-> current Web App configuration verification
-> current hosted readiness verification
-> current exact direct RBAC verification
-> offline hosted-verifier check
-> manual review of all sanitized evidence
-> one explicitly authorized hosted metadata-verification execution
-> review of the sanitized result
```

The final hosted execution belongs to a future slice. It must not run while
preparing or reviewing this runbook, and it remains separate from every agent
invocation or model-inference operation.

## 8. Success contract for the future live slice

Success requires the existing sanitized application-owned result to prove all
of the following without exposing identifiers or raw SDK output:

- Execution occurred inside the approved hosted App Service environment.
- Only the Linux Web App system-assigned managed identity was used.
- Managed-identity authentication succeeded.
- The expected Foundry project and prompt-agent metadata were readable.
- The configured prompt agent and exact immutable version were present.
- Responses protocol support was present.
- Routing resolved exclusively to the approved immutable version.
- The model and centralized instructions matched the approved definition.
- No inference, invocation, or Azure mutation was attempted.
- The result contained only the verifier's existing sanitized application-owned
  fields.

RBAC existence alone, token acquisition alone, credential or client
construction, resource existence, and successful hosted readiness are not
sufficient proof.

## 9. Fail-fast stop conditions

Stop before the hosted operation when any prerequisite is missing, stale,
ambiguous, malformed, mismatched, unauthorized, not currently usable, or based
only on historical evidence. Also stop when:

- The immutable agent version cannot be freshly verified.
- Hosted code provenance or `/health`, `/version`, and `/demo/status` readiness
  cannot be freshly verified.
- The exact direct Consumer assignment cannot be freshly verified.
- The hosted operation has no repository-owned execution mechanism.
- A required non-secret setting lacks a repository-owned configuration boundary.
- A command would require credential fallback, mutation, retry, polling, manual
  environment injection, or an inferred resource name.
- The repository's current implementation differs materially from this runbook.

Do not retry with alternate credentials or scopes. Stop for operator correction
and, where required, a separately scoped implementation or deployment slice.

## 10. Prohibited behavior

The prerequisite and future metadata-verification workflows prohibit the
following ad hoc Azure changes and unsafe operations:

- Ad hoc Azure changes during prerequisite verification.
- Agent invocation or model inference.
- Prompt-agent creation or version creation.
- RBAC repair.
- Infrastructure deployment unless separately authorized before the future
  metadata-verification slice.
- Application code deployment during the metadata-verification execution.
- Credential fallback to Azure CLI, developer, environment-secret, browser,
  workload, cached, user-assigned, or interactive credentials.
- General-purpose shell polling loops, repeated sleeps, repeated verifier calls,
  indefinite waiting, or retrying against alternate names, scopes, or
  credentials.
- Portal-only substitutes, inferred names, historical evidence, interactive
  Kudu or SSH manipulation, temporary startup changes, new WebJobs, ad hoc HTTP
  endpoints, and manual environment-variable injection.
- Raw CLI or SDK output in documentation.
- Secrets, identity values, tokens, endpoints with embedded secrets, real
  patient data, or real contact information.

At most one repository-approved bounded completion check is permitted, and
only when an authoritative operation explicitly requires it. It never permits
general polling, repeated calls, or indefinite waiting.

## 11. Operator completion checklist

- [ ] Operator login and one current-account check are complete.
- [ ] Intended subscription name, `Enabled` state, and default selection are
  confirmed without recording subscription or tenant IDs.
- [ ] Every exact inventory value is current, sanitized, operator-approved, and
  matched to repository-owned evidence.
- [ ] Foundry account, project, endpoint contract, and model deployment are
  freshly verified and usable.
- [ ] Prompt-agent name, exact immutable version, Responses protocol, exclusive
  routing, model, and centralized instructions are freshly verified.
- [ ] Linux Web App configuration and system-assigned identity are freshly
  verified against the complete Bicep-owned safe contract.
- [ ] Current package/code provenance is reviewed and `/health`, `/version`, and
  `/demo/status` are freshly verified.
- [ ] Exactly one direct Consumer assignment is freshly verified for the exact
  identity and exact Foundry child-project scope.
- [ ] Every required non-secret verifier setting has a repository-owned
  deployment/configuration path and is currently available to the Web App.
- [ ] A repository-owned bounded hosted execution mechanism exists and has been
  separately implemented and reviewed.
- [ ] Offline hosted-verifier check passed without a credential, client, Azure
  call, metadata read, inference, invocation, or mutation.
- [ ] All sanitized evidence has been manually reviewed; no raw output, secret,
  identity value, complete resource ID, patient data, or real contact data was
  captured.
- [ ] No stop condition remains.
- [ ] The operator explicitly authorizes exactly one hosted metadata-verification
  execution. This authorization applies only to that metadata read and not to
  agent invocation, model inference, deployment, RBAC change, or retry.
