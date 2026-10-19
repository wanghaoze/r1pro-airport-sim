# Completion-only held IK residual policy proposal

Design only; no production or frozen release changed and no new physics run.

## Field and boundary

Propose `completion_held_ik_position_tolerance_m = .030`, active only with `acceptance_profile == completion_first` and `holding is not None`. Validate finite explicit range22–40mm. Keep the original global `ik_position_tolerance_m` cap, so effective held position bound is `min(cfg.ik_position_tolerance_m, completion_held_ik_position_tolerance_m)`. Strict stays `min(cfg.ik_position_tolerance_m, .022)`. Empty-arm original40mm is unaffected. Existing retained-side12mm and supported-push vertical.25mm constraints remain and take precedence. A40mm future setting is an explicit separate experiment, not an automatic fallback.

Absolute TCP target residual is a planning precision threshold, not measured tray goal acceptance. Case9 coupled IK has left25.646/right25.665mm absolute residual, with rigid relative position2.852mm and small orientation errors. The30mm policy admits this numeric candidate while retaining all other checks; it does not establish that the full Cartesian path, physical lift/place or episode will pass. Case2 best existing candidate22.295mm would also become eligible for subsequent checks. Smoke6 terminal39.599mm does not pass30mm.

## Complete call chain

`Runtime._ik_tolerances(side)` is used only by `Runtime.solve_pair`; there is no competing override in current source. All approach/lift/object_points/cartesian/placement shadow probes enter that solver. Independent-arm fitting uses the bound for its score, accepted early break and post-fit rejection. Coupled refinement then rechecks absolute TCP errors, rigid relative position15mm/rotation.10rad and joint branch limit. Both independent and coupled position gates must follow the explicit policy. Merely changing the coupled final check leaves independent IK able to reject first.

Orientation still uses the original held.05rad cap. Joint limits, branch radius, complete path/camera/collision/rigid validation, measured bilateral forces and loss timers, table contacts, penetration, primitive3s budget, and final5cm/10deg stable released task validation do not change. Private planning copies already carry cfg; none should be assigned extra live state or weakened physical guards.

## Original feasible solution preservation

Changing `_ik_tolerances` directly also changes normalized candidate score and early termination: it can choose a different, less precise seed even where the old solve was possible. Thus a one-line threshold edit is not guaranteed to preserve old successful trajectories.

Recommended bounded implementation: keep original22mm score/search/early-break first. Only if no old-valid independent solution exists, consider the best already-evaluated seed meeting the explicit30mm position bound and all unchanged non-position criteria. Coupled refinement first uses the exact original candidate and optimization; only its absolute-position rejection may use the30mm policy if rigid/orientation/branch checks pass. No extra physical attempts, solver iterations or seed budget are required. Record original/effective per-side residuals and that this is a planning-policy relaxation. If a simpler direct-bound implementation is chosen instead, report its candidate-order effect and revalidate original successes.

For strict reporting, preserve evidence that an accepted reference exceeded the old22mm policy. A geometry-preview acceptance is not physical task success; speculative rejected probes should remain planning diagnostics. Any executed selected path using the relaxed reference must make strict_success false with structured deviation evidence. Runtime-owned physical preview logs remain isolated from actual-episode deviations.

## Minimal tests and subsequent evidence

Test strict default/empty/retained unchanged; held completion25.6mm accepted at30 while30.001mm rejected; orientation, rigid relative15mm, branch and collision still reject;40mm never implicit; original strict-valid seed remains selected; private planning cfg propagates without live mutation. Then two fresh complete representative episodes (case2 and9), original vs new frozen configuration in separate directories with max_attempts1, preserving all failures and actual final metrics. No result from this proposed test is currently available.
