# Recover Stale Hosted Foundry Agent WebJob State

## Purpose and authorization boundary

Use this offline procedure only when the normal daily coordinator stops on
stale, incompatible, or generation-mismatched immutable WebJob lifecycle
evidence, or when generation-bound deployment reports
`generation_handoff_invalid`, `generation_invalid`, `generation_changed`, or
`package_changed` and a replacement handoff is required. Recovery is a separate
manual evidence-retirement boundary. It does
not call Azure or HTTP, authorize or trigger a WebJob, convert prior evidence
into current evidence, or produce `daily_environment_ready=true`.

Never delete, overwrite, edit, reset, adopt, or ignore files beneath
`.artifacts/hosted-foundry-agent-webjob/`. Do not add a coordinator skip or
force flag.

The dedicated WebJob package and deployment boundary never edits or replaces
`generation-handoff.json`. A changed application package, WebJob source,
identity, project, agent version, readiness receipt, or environment fingerprint
invalidates prior approval. Do not manufacture a matching package, retry an
ambiguous upload, or prepare over existing state. Inspect first, preserve and
archive only through the default-no procedure below, then restart prerequisite
proofs from the current generation.

Build output belongs only beneath
`.artifacts/hosted-foundry-agent-webjob-package/`. The active
`.artifacts/hosted-foundry-agent-webjob/` directory is reserved for recognized
immutable lifecycle evidence. Normal recovery continues to reject `package/`,
ZIP files, arbitrary directories, unknown files, symlinks, devices, sockets,
and malformed evidence beneath the active lifecycle root.

## 1. Check the offline recovery contract

From the repository root, run:

```bash
.venv/bin/python scripts/recover_hosted_foundry_agent_webjob_state.py \
  --check \
  --source-root "$PWD" \
  --json |
  python -m json.tool
```

The check performs no Azure, HTTP, WebJob, identity, or invocation operation.

## 2. Transitional inspection and retirement of the exact legacy package conflict

The dedicated package slice briefly created one bounded legacy shape: a valid
0600 `generation-handoff.json` beside one 0700 `package/` directory containing
exactly one regular 0600 `verify-hosted-foundry-agent.zip`. Normal `--inspect`
must return `unsafe_path` for this shape. Do not move or delete either entry.

Use the explicit transitional flag to inspect only that exact conflict:

```bash
.venv/bin/python scripts/recover_hosted_foundry_agent_webjob_state.py \
  --inspect \
  --legacy-package-conflict \
  --source-root "$PWD" \
  --json |
  python -m json.tool
```

This mode uses descriptor-relative no-follow reads and requires the exact active
directory entries, exact directory and file modes, same owner, fixed filename,
one-file deterministic ZIP structure, valid prepared handoff, and no extra
content. The returned manifest binds the ZIP bytes internally, but the package
digest, package bytes, absolute paths, environment fingerprint, and artifact
bodies are never serialized.

After reviewing a successful `state=legacy-package-conflict` result, run a
separate default-no archive using its exact manifest digest:

```bash
.venv/bin/python scripts/recover_hosted_foundry_agent_webjob_state.py \
  --archive \
  --legacy-package-conflict \
  --source-root "$PWD" \
  --manifest-digest <exact-inspection-manifest-digest> \
  --reason stale_environment_evidence \
  --json |
  python -m json.tool
```

After approval, recovery atomically quarantines and reinspects the complete
unchanged legacy directory. Only the exact approved manifest can be renamed as
one generation into the normal archive root and receive an immutable external
retirement receipt. Mutation, replacement, permission drift, symlinks, added or
missing entries, ZIP-shape drift, collision, or concurrent active replacement
fails closed and preserves or restores the evidence through the existing
quarantine rules. This transitional flag never permits a second package shape
and is invalid in `--check` mode.

## 3. Inspect and preserve a normal lifecycle manifest

Obtain the current environment-generation fingerprint through the normal
coordinator's sanitized local handoff; do not commit or paste it into this
runbook. Inspect the active immutable state:

```bash
.venv/bin/python scripts/recover_hosted_foundry_agent_webjob_state.py \
  --inspect \
  --source-root "$PWD" \
  --expected-environment-fingerprint <current-fingerprint> \
  --json |
  python -m json.tool
```

Save the sanitized output in the operator's approved evidence location. Review
the state category, safe filenames, schema versions, file sizes, file digests,
fingerprint digest, and exact manifest digest. The utility never returns raw
artifact bodies, resource names, endpoints, prompts, credentials, patient data,
or raw identifiers.

Stop without archival for `malformed`, `conflicting`, `unsafe_path`, an active
reservation, an unexpected file, or any symlink. Investigate separately while
preserving the directory unchanged.

## 4. Explicit default-no retirement

For a valid accepted, blocked, terminal, or stale manifest, run a separate
archive command with the exact inspected digest:

```bash
.venv/bin/python scripts/recover_hosted_foundry_agent_webjob_state.py \
  --archive \
  --source-root "$PWD" \
  --expected-environment-fingerprint <current-fingerprint> \
  --manifest-digest <exact-inspection-manifest-digest> \
  --reason stale_environment_evidence \
  --json |
  python -m json.tool
```

The prompt defaults to no on EOF, empty, malformed, closed input, read error, or
decline. After approval the service acquires one exclusive local recovery
reservation, atomically moves the current active directory to a unique pending
quarantine, and reinspects that exact directory through descriptor-relative
no-follow reads. Only an exact match between the quarantined manifest and the
approved digest can continue.

On an exact match, the utility requires a same-filesystem sibling archive and an
unused deterministic destination. It atomically renames the pending quarantine
into `.artifacts/hosted-foundry-agent-webjob-archive/`, verifies the archived
directory identity, and reinspects the final evidence before creating an
immutable retirement-receipt sidecar outside the preserved evidence tree. The
receipt records the approved and archived manifest digests, safe file evidence,
archive-relative path, timestamp, and reason. The archived directory remains
byte-for-byte unchanged. Individual lifecycle files are never deleted or
edited, and copying is never a fallback.
The sidecar is named `<archive-name>.retirement-receipt.json` in the archive
parent; it is never added to the archived evidence directory.

If quarantined evidence does not match, the utility restores it atomically to
the active pathname only when that pathname is absent and the exact quarantined
directory identity is still proven. Otherwise it retains the directory under a
blocked quarantine path and emits a durable sanitized recovery-outcome sidecar
for manual investigation. It never overwrites a conflicting active path,
silently adopts replacement evidence, or creates a success retirement receipt.
An identity, record-persistence, or reservation-release ambiguity preserves the
recovery reservation and all evidence paths. Do not delete or bypass them.

The fixed reservation coordinates repository-owned recovery processes sharing
one local artifact filesystem. It has no automatic expiry and is not a
distributed lock or a defense against a hostile kernel. Caller-supplied source
roots and every parent are opened without following symlinks. Collision,
symlink, unsafe path, or cross-device behavior fails closed.

## 5. Verify and restart normally

Review the returned archive and retirement-receipt relative paths. Confirm the
original accepted, blocked, and terminal files are byte-for-byte present as
applicable, and confirm the external receipt's approved and archived manifest
digests both equal the inspected digest. The active state directory may now be
absent because it was moved intact.

Rerun `scripts/rebuild_daily_azure_environment.py` from its offline check and
then, only under a new explicit live authorization, from the beginning. The new
generation may create a new active lifecycle directory. The archive is audit
evidence only and must never be reused as a receipt or authorization.
