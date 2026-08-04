# Live Hosted Foundry Agent SSH Prerequisites

## Purpose And Current Status

This is the only operator procedure for a supervised connection to the exact
owned Linux App Service container. Direct App Service SSH transport is
live-proven: one owned tunnel reached readiness, both fixed `APP_PATH` probes
passed, the packaged non-invoking check passed, and shutdown/reaping completed.
SSH hosted managed-identity execution is unsupported because its process does
not run in the App Service application-worker identity environment. No hosted
managed-identity metadata access or hosted Agent invocation is proven through
this boundary, and no replacement hosted execution topology is selected.

The repository-owned transport service and wrapper separate transport from the
packaged Foundry proof. They do not own daily readiness, RBAC, Agent lifecycle,
metadata verification, invocation, application routes, persistence,
notifications, or urgency rules. The WebJob trigger-and-correlation mechanism
remains retired.

## Required Current-Session Evidence

Before starting a tunnel, require all of the following from one fresh session:

1. Canonical daily readiness with the current application artifact proven
   equal to the running Web App artifact.
2. Current Web App configuration and hosted-readiness proof.
3. Current immutable prompt-Agent identity, definition, Responses protocol,
   model, centralized instructions, and exclusive routing proof.
4. Current read-only proof of exactly one direct project-scoped Foundry Agent
   Consumer assignment for the Web App system identity.
5. Successful offline transport check:

   ```bash
   .venv/bin/python scripts/run_hosted_foundry_agent_ssh_transport.py \
     --check \
     --json
   ```

Historical evidence, a prior readiness receipt, deployment acceptance, or
resource existence cannot satisfy these gates. Stop for stale, missing,
ambiguous, or mismatched evidence.

The current wrapper modes are mutually exclusive:

- `--check` performs only the offline contract check shown above.
- `--live-tunnel` performs one tunnel, the two prerequisite probes, and one
  packaged non-invoking check.
- `--live-metadata-verification` is retired and returns one deterministic
  sanitized unsupported result before configuration or transport activity.

The supported live mode requires `--config .env.daily-azure.local`, the current matching
`--readiness-receipt`, and `--json`. Obtain READY through the canonical daily
runbook; do not duplicate or improvise the environment rebuild here.

For the already proven non-invoking transport acceptance, use only:

```bash
.venv/bin/python scripts/run_hosted_foundry_agent_ssh_transport.py \
  --live-tunnel \
  --config .env.daily-azure.local \
  --readiness-receipt .artifacts/daily-azure-rebuild/readiness-receipt.json \
  --json
```

Do not run another metadata-only SSH acceptance. Operators must not forward,
retrieve, inspect, synthesize, or override App Service runtime identity
markers. Do not substitute the retired WebJob trigger-and-correlation path or
improvise another remote command. Any future hosted metadata or invocation
proof requires a separately approved architecture decision.

## Selected Tunnel Mechanism

`az webapp create-remote-connection` is the only supported tunnel mechanism.
`az webapp ssh` is prohibited because it owns additional interactive behavior
outside this repository's exact remote-command contract.

The service constructs one argument list with the validated current
subscription, resource group, and Web App plus the repository-owned loopback
port, bounded timeout, and `--only-show-errors`. Operators cannot override the
host, port, timeout, slot, instance, command, module, or arguments. The
sanitized result never contains those values or raw command details.

## Terminal And Process Ownership

The repository wrapper owns the one tunnel process. Run the supervised wrapper
in the foreground; do not background an unmanaged Azure CLI process. The
wrapper captures tunnel stdout and stderr privately and continuously drains
both streams without retaining a raw line. The owned child's readiness evidence
is the repository-owned loopback boundary becoming usable before the absolute
deadline while that one process remains in a compatible state; CLI text alone
is never sufficient. The wrapper remains active until the result is final.

The wrapper owns the SSH subprocesses and their private current-run
`known_hosts` file. Authentication remains an explicit operator interaction;
the repository stores no password and uses no password helper or generated
credential file. The supported live mode runs exactly three fixed SSH commands:
two probes and its one approved non-invoking operation. This is not permission
for a general remote shell.

### Interactive SSH password

When the interactive SSH prompt displays:

```text
root@127.0.0.1's password:
```

enter:

```text
Docker!
```

This password is case-sensitive, and the exclamation mark is part of the
password. Password characters are not displayed while typing. The prompt can
appear separately for each fixed SSH command; in this workflow it may appear
for both prerequisite probes and the one approved remote operation. Type the
password only at the interactive SSH prompt.

Do not place this password in the Python command, `.env.daily-azure.local`, any
committed `.env` file, a CLI argument, subprocess stdin automation, source
code, test fixtures representing secrets, JSON output, or logs or screenshots
intended for publication. It is not an Azure account password, local computer
password, deployment credential, or application secret. Do not automate entry.

Success is impossible until the wrapper confirms that it terminated and reaped
the tunnel process and removed the private current-run host-key file.

## Three Separate Approval Gates

The supervised wrapper requires three default-no approvals, in order:

1. Start exactly one owned tunnel process.
2. Execute the two fixed prerequisite probes.
3. Execute exactly one packaged non-invoking `--check --json` operation.

No approval authorizes identity execution, metadata access, invocation, another
tunnel, another remote command, mutation, or automatic retry.

## Exact Supported Remote Commands

The supported live mode permits the same two probes and exactly one packaged
non-invoking check. These commands are exceptions to the general prohibition on
remote shell commands. Their complete strings are immutable constants in the
transport service; the operator cannot provide command text or a module name.

### 1. Interpreter/runtime-root probe

The fixed `python -c` probe reads only `APP_PATH`. It confirms that `APP_PATH`
is present and absolute and that the container's `python` interpreter is
usable. It emits exactly one application-owned boolean JSON document:

```json
{"app_path_valid":true,"interpreter_valid":true}
```

It never prints `APP_PATH`, `sys.executable`, or another filesystem path; it
does not enumerate environment variables or search the filesystem. No fixed
Oryx or deployment directory is assumed.

### 2. Packaged-module probe

The second fixed `python -c` probe validates the same `APP_PATH`, adds only that
value to the import context, imports exactly
`src.app.operations.prove_hosted_foundry_agent`, and verifies its owned entry
point. Both the resolved module and entry-point origins must remain beneath the
canonical validated `APP_PATH`; an import fallback elsewhere fails closed. It
emits exactly:

```json
{"packaged_module_valid":true}
```

It never prints a module path or accepts a module override.

### 3. Packaged non-invoking check

After the separate third approval, the fixed command uses only `APP_PATH` and
runs:

```bash
python -m src.app.operations.prove_hosted_foundry_agent --check --json
```

The wrapper accepts exactly one newline-terminated JSON document with
`ok=true`, `category=check_passed`, `mode=check`, and every live-attempt or
side-effect field false. It rejects extra stdout, malformed JSON, unknown
fields, nonexact booleans, a nonzero exit, or any indication of `--live`,
identity, metadata, or Agent activity.

This third command is permitted only in `--live-tunnel` mode. That mode retains
its live-proven non-invoking semantics and never selects metadata verification.

### Retired compatibility mode

`--live-metadata-verification` constructs no remote command. Its deterministic
unsupported result occurs before configuration proof, approval callbacks,
service or runner construction, tunnel startup, password prompts, probes,
credentials, metadata access, or Agent invocation. Historical lower-level
parsers and packaged operations remain technical evidence, not operator
authorization.

No other command is permitted. In particular, do not run a login shell,
filesystem listing, environment listing, diagnostic command, package install,
route request, WebJob command, Kudu command, or the packaged `--live` mode.

## Retry And Bounded Observation Semantics

No retry means the repository starts at most one Azure CLI tunnel process and
never restarts it. Bounded readiness observations of that same process and the
Azure CLI command's internal connection protocol are not separate
operator-level tunnel attempts.

The durable rules are:

- one tunnel subprocess invocation;
- no tunnel restart and no second tunnel;
- one absolute monotonic deadline;
- bounded readiness observations of the original process only;
- no repeat of a failed probe;
- no repeat of the packaged check; and
- interrupt/terminate/kill cleanup escalation is permitted and is not a retry.

## Stop, Shutdown, And Reaping

Stop immediately after success, failure, approval denial, early child exit,
timeout, disconnect, malformed output, ambiguous state, exception,
`KeyboardInterrupt`, `SIGINT`, or `SIGTERM`.

Cleanup always targets the original process:

1. Send the graceful interrupt corresponding to the tunnel's documented
   Ctrl+C shutdown behavior when it is still active.
2. Wait for the bounded cleanup interval.
3. If still active, terminate it and wait again.
4. If still active, kill it, wait, and reap it.
5. Remove the private current-run host-key file.
6. Suppress cleanup exceptions without replacing the primary failure.

Do not claim success unless termination and reaping are confirmed. Never retain
raw Azure or SSH output, credentials, connection text, identifiers, ports,
hostnames, instance information, endpoints, filesystem paths, prompts, or
clinical content.

The wrapper installs its interruption boundary before process construction,
defers any construction-time or cleanup-time `SIGINT`/`SIGTERM` until cleanup
owns the child, and does not return after kill until the child has been reaped.

For transport acceptance, stop after the packaged non-invoking check. Do not
attempt metadata verification or invoke the Agent. Every failure or denial is
a stop condition, and the supported live mode permits no retry within the
attempt.
