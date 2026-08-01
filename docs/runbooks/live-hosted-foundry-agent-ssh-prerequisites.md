# Live Hosted Foundry Agent SSH Prerequisites

## Purpose And Boundary

Use this runbook only for a future operator-supervised proof inside the exact
owned, already-running Linux App Service container. The packaged operation
performs hosted-environment validation, existing managed-identity metadata
verification, exact proof validation, and at most one existing fixed-fictional
Agent invocation. It emits one sanitized JSON document synchronously.

The repository implementation and this runbook are offline-tested only. No SSH
connection, managed-identity token, metadata request, Foundry call, or hosted
Agent invocation has succeeded through this boundary.

## Required Current-Session Evidence

Before opening any tunnel, require all of the following:

1. Fresh current-session `daily_environment_ready=true` from the canonical
   daily operator procedure.
2. Current application artifact equality for the running Web App.
3. Exact current Web App configuration proof, including the hosted verifier
   settings contract.
4. Current verification of the direct project-scoped Foundry Agent Consumer
   assignment for the Web App system identity.
5. Current immutable Agent identity, definition, Responses protocol, model,
   centralized instructions, and exclusive-version routing verification.
6. Confirmation that the ordinary package contains the exact proof operation
   `src.app.operations.prove_hosted_foundry_agent`. Do not build or upload a
   separate package.
7. Confirmation that the exact owned Linux Web App is running and still serves
   the current application artifact.
8. Explicit operator approval before opening an authenticated App Service SSH
   tunnel to that exact owned Web App.

Stop if any evidence is missing, stale, ambiguous, or belongs to another
environment generation. Historical output and prior-session readiness do not
satisfy this gate.

## Fixed Non-Invoking Remote Check

After the approved tunnel is established, use the application-container
interpreter selected by the running site. Do not assume or freeze an absolute
interpreter path, Oryx environment, virtual environment, Kudu path, temporary
deployment path, or working directory.

Run this exact non-invoking remote check once:

```bash
python -m src.app.operations.prove_hosted_foundry_agent --check --json
```

This establishes that the selected interpreter can import the packaged module
and that its local verification, fixed-fictional request, invocation contract,
SDK visibility, result schema, and execution boundary remain valid. Check mode
constructs no credential or Azure client, reads no hosted identity marker,
makes no metadata or Agent request, and performs no persistence or notification
work.

Require exactly one newline-terminated JSON document with `ok=true`,
`category=check_passed`, `mode=check`, and every live-attempt or side-effect
field false. Stop on any other output. Do not proceed merely because the module
imports or the Web App is healthy.

## Single Supervised Live Proof

After the check succeeds, obtain separate explicit operator approval for
exactly this one command:

```bash
python -m src.app.operations.prove_hosted_foundry_agent --live --json
```

Permit exactly one synchronous execution. Do not change configuration, identity,
Agent, model, endpoint, project, version, prompt, fixture, interpreter, or
working directory between the approved check and live command.

Accept only one newline-terminated sanitized JSON document. Success requires
the exact combined proof booleans: hosted environment present, managed identity
attempted, metadata verification attempted and proven, one Agent invocation
attempted, valid application-contract output, fictional data only, an Azure
call made, no route, persistence, notification, deterministic-rule execution,
or Azure mutation.

Stop immediately after success, failure, ambiguity, disconnect, timeout, or
malformed output. Do not issue the command again. Preserve only the sanitized
JSON proof under the separately approved evidence procedure; do not expose or
copy raw SSH output or application-generated content.

## Prohibited Work

This procedure must not use or add:

- WebJob upload, discovery, trigger, reconciliation, status, history, package,
  or lifecycle artifacts
- Kudu `/api/command` or another command-execution API
- A new HTTP route, public proof endpoint, or private application endpoint
- Container Apps Jobs, Function Apps, queues, workers, or additional compute
- Arbitrary shell commands beyond the fixed non-invoking check and one approved
  proof operation
- A command retry, polling loop, fallback credential, or alternate transport
- Agent configuration, version, routing, RBAC, or infrastructure changes
- Persistence, notifications, case processing, urgency rules, or patient data
- Prompts, fictional request text, generated clinical content, raw SDK output,
  identity markers, credentials, tokens, endpoints, identifiers, hostnames, or
  filesystem paths in retained evidence

No patient data may be used. Human nurse review remains mandatory for all
application-generated output, and this proof does not establish clinical or
production readiness.
