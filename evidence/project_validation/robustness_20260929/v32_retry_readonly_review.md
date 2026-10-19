# Frozen v32 retry runner review

Reviewed only runs/control_deploy_20260929/v32_retry_timing_frozen/source. No production edits, tests or physics runs. Scope: control_regression.py, batch.py and their registry/result/export consumers.

## P2: preflight interruption cannot resume when only the log survives

batch.preflight.job skips a completed preflight.json, otherwise calls run_child with the fixed preflight.log name. run_child opens that log with exclusive x mode. A hard interruption/crash after opening the log but before writing preflight.json leaves exactly this state. Subsequent control_regression successfully matches prepare fingerprint but fails preflight with FileExistsError before spawning any worker. The original log is preserved, but progress cannot resume. The attempt path already uses a unique resume log when its old log exists; apply the same bounded policy to preflight in a later release. Do not delete the old log or fabricate a valid preflight report. Fresh v32 startup is unaffected.

## P2: hard parent death is not fenced against surviving attempt workers

run_child starts every worker in its own POSIX session. The main process cleans them through stop_children for Python KeyboardInterrupt/Exception, and timeout explicitly kills the worker process group. There is no SIGTERM handler, parent-death signal, active-worker lease or scene lock. SIGTERM/SIGKILL of only the batch/controller parent can leave attempt children alive. A later generate run classifies every existing directory without result as interrupted immediately; it cannot distinguish a surviving writer. That creates a race where the old worker may overwrite the newly synthesized failure result and a new attempt can run concurrently. This is conditional on unclean parent termination, not an observed failure in the current fresh run. Before any crash resume, operationally establish that prior attempt workers have stopped; a robust later release should fence ownership and wait/reap before finalizing interruption evidence. Merely adding SIGTERM handling does not solve SIGKILL or host/process ownership races.

## Failure preservation and identity

Normal failed attempts retain separate aNNN directories, trace/exception and atomic result; new attempts advance indices. Existing directories with no result are retained and receive interrupted_attempt_retained, consuming budget. Worker timeout/crash receives its own result, including exit code. Existing log files get uniquely named resume logs. Attempt indices must be contiguous and within max_attempts; result identity is validated. The summary additionally rejects duplicate scene/attempt identities and gaps. No in-place retry of an existing physical episode is performed.

Interrupted/worker fallback result records omit acceptance_profile, task_completed and duration fields. Their false physics_success prevents completion inflation, and missing cost counters expose absent timing; nevertheless outcome_counts labels missing profile as strict, producing a misleading mixed-profile list for a completion collection with a crashed worker. Add explicit profile/task=false/strict=false/provenance and available elapsed-cost evidence in a later release. This is reporting quality, not a success-count bug.

## Source denominator and selected closure

prepare fingerprints the complete400 registered source/config and split; changed resources/config refuse mixed resume. generate requires preflight evidence for each selected scene; unselected cases are never marked verified. A preflight-rejected scene returns without attempts and remains pending in attempt closure, so it does not falsely close a400 denominator. summary derives source ids from collection index and uses that denominator; selected closure/rate is separately labeled. Diagnostic-only results are excluded. Partial-source coverage is explicitly not a population estimate. The runner can be complete while selected_budget_closed is false for preflight-rejected scenes; consumers should use closure, not runner_complete alone, for a completed-attempt-budget claim.

## Completion, strictness and export remain separate

Completion mode stops at the first actual task_completed even with recovery, independent of export rejection. Strict mode retains legacy clean-success stopping. Results separately retain task/strict/final-placement metrics. Export choose_attempts still rejects recovery_used and diagnostic_only and requires trace.h5 plus non-rejected export quality. Thus stopping after a recovered completion does not incorrectly export that episode; it may legitimately leave the collection without an exportable sample for that scene. This is the declared completion-first stopping objective, not evidence loss. strict and completion stopping_budget_closed fields are available separately from task-completion budget closure.

## Recommendation

No ordinary fresh-run retry/success-inflation defect found that requires aborting the v32 fresh diagnostic. Preserve its frozen version. Fix preflight log resume and hard-crash worker ownership before promising reliable arbitrary interrupt/crash resume. Keep new-source runs and separate task/export gates.
