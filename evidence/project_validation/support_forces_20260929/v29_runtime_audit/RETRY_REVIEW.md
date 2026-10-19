# Bounded fresh-Episode retry review

Read-only review of current source. No production edits, collection changes, or additional physical tasks.

## Current behavior

- Config.max_attempts_per_scene defaults to 6; deployed evaluations can override it. generate iterates attempt=0..budget-1 and uses new subprocesses. run_attempt constructs a new Runtime and Machine from the frozen scene each time. This is a new episode, never a rewind within an exported trajectory.
- seed_for hashes scene_id:scene.seed:attempt with SHA256 and interprets the first eight bytes as a big-endian integer. Attempt 0 uses historical nominal candidates where available; attempts 1 and 2 use reproducibly randomized candidate headings/distances/lateral/rim offsets. Static source geometry, split, and physics remain unchanged.
- Current batch stopping counts physics_success AND NOT recovery_used. Resume additionally excludes export_rejected; new results do not apply that export filter. This is incompatible with completion-first stopping after a completed recovered episode and mixes physics generation with export quality.
- outcome_counts already uses unique scene IDs, excludes diagnostic_only, counts task completion with recovery, and separately exposes first-attempt/strict-clean counts. It does not validate duplicate attempt identities or budget bounds.
- control_regression uses the registered source denominator for task_completion_rate. Its complete flag means each source scene has any result, not that every scene's retry budget has closed. Some legacy attempted/clean counters include broader result inputs, so a final retry-aware report must filter actual identities consistently.

## Proposed contract

Create a new frozen source/config and wholly new collection. Set max_attempts_per_scene=3, successes_per_scene=1. Keep every other controller/profile/physics field unchanged for an interpretable comparison. Do not retrofit the running single-attempt collection or transfer old attempts as if generated in the new run.

For completion_first, stop a scene after the first non-diagnostic task_completed result (legacy fallback physics_success), including recovery. Keep strict stopping behavior unchanged. Do not rerun a completed physical task solely because media export failed; report/retry export separately. Every interrupted/crashed attempt consumes one of the three slots and retains evidence. Enforce unique (scene_id, attempt), attempt in [0,2], and provenance/config equality.

A scene is budget-closed only if it has completed, or all three allowed attempts have terminal results. A preflight-rejected scene remains in the fixed 400 denominator and is explicitly accounted as no episode generated. Runner completion and per-scene closure must agree before final reporting; partially running attempts never count as success.

Report separately: attempt-0 completed scenes / 400; completed within at most three attempts / 400; strict-clean equivalents; counts with recovery; total attempted episodes; success-at-attempt histogram; physical simulated time and wall cost. Preserve the original strict labels and do not describe this statistical generation strategy as stronger per-episode control. Bounds: at most 1200 actual Episodes, and at most three existing per-attempt wall/physical budgets per scene; no guarantee that extra random seeds overcome structural failures.

## Failure video monitoring

The current v30b watcher waits for 400 UNIQUE scene IDs with any result, then captures the failure inventory once. That is correct for its existing one-attempt run but would finish inventory too early for retries. The collector itself supports all a*/result.json and uses scene/attempt identities.

Use a separate watcher for the new collection: incrementally collect completed failed attempts, continue until the runner is finished AND retry budgets are closed, then perform a final inventory reconciliation. Preserve a000/a001 failures even when a002 succeeds. Keep bounded render/download concurrency and original dual-head evidence. Do not modify the current v30b watcher or collection.
