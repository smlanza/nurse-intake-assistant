# Immutable Hosted WebJob Evidence Recovery Reference

> **Canonical procedure moved:** Follow “Exceptional immutable WebJob evidence
> recovery” in
> [`daily-azure-operator-runbook.md`](daily-azure-operator-runbook.md). It is
> the only operator sequence. This file retains implementation guarantees and
> historical compatibility details.

## Purpose and authorization boundary

The recovery boundary is offline and exceptional. It does not call Azure or
HTTP, trigger a WebJob, authorize a retired WebJob operation, turn prior
evidence into current evidence, or produce
`daily_environment_ready=true`.

The implementation rule is: never delete, overwrite, edit, reset, adopt, or
ignore files beneath
`.artifacts/hosted-foundry-agent-webjob/`. The WebJob package/deployment code
never edits or replaces `generation-handoff.json`. Do not manufacture a
matching package.

The canonical procedure preserves the required sequence: Inspect first, record
the expected environment fingerprint and exact manifest digest privately,
inspect again with the same expected fingerprint when necessary, archive only
with the exact matching digest, verify the archive and external receipt, then
restart normal work at Step 1.

## Recovery CLI contract

`scripts/recover_hosted_foundry_agent_webjob_state.py` recognizes exactly
`--check`, `--inspect`, and `--archive`. Every mode requires `--source-root`
and `--json`. Normal inspection and archive may use
`--expected-environment-fingerprint`; archive additionally requires the exact
manifest digest and a supported reason.

The archive prompt defaults to no. After approval, recovery acquires its
exclusive local reservation, atomically quarantines the active directory,
reinspects it, and continues only when the evidence still matches the approved
exact manifest digest. It atomically renames the unchanged directory into the
sibling archive and creates an external
`retirement-receipt.json`.

The receipt records matching approved and archived manifest digests and safe
file evidence. Individual lifecycle files remain byte-for-byte unchanged.
Copying is never a fallback. A collision, symlink, unsafe path, changed
evidence, cross-device condition, identity ambiguity, record-persistence
failure, or reservation-release ambiguity fails closed and preserves evidence.

## Transitional legacy package conflict

The explicit `--legacy-package-conflict` compatibility flag recognizes only
the exact historical shape: valid `generation-handoff.json` beside one
restricted `package/` directory containing one regular restricted
`verify-hosted-foundry-agent.zip`.

Normal `--inspect` must return `unsafe_path` for that directory shape. The
legacy inspection validates the complete one-file ZIP and binds its package
digest without returning package digest, package bytes, absolute paths, the
environment fingerprint, or artifact bodies. Archival preserves the complete
unchanged legacy directory. The flag does not accept any second package shape
and cannot be used with check mode.

## Failure policy

Stop without archival for malformed or conflicting state, `unsafe_path`, an
active reservation, unknown entries, permission drift, or any symlink. Never
manually repair immutable evidence.

If quarantined evidence changes, recovery restores it only when the active path
is absent and the exact directory identity remains proven. Otherwise it keeps a
blocked quarantine and durable sanitized outcome for investigation. It never
overwrites replacement state or reports successful retirement without a
verified external receipt.
