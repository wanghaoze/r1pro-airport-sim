# v37 bounded two-stage orientation design (not implemented)

## Smallest first implementation: lift only

Keep live completion_held_ik_orientation_tolerance_rad=.05. Add an independent default-off lift fallback policy; the fallback ceiling can use a dedicated declared .12 value. Do not make Runtime automatically widen every failing query. Existing strict/empty/retained behavior stays unchanged.

Build the seven inward targets once from the actual lift-boundary observation after continue_loaded_reference. First run the entire existing select_lift_path logic on a loaded_planning_copy with its own dataclasses.replace configuration at .05 orientation: original geometric order, nominal budget, then existing extended-budget retries only for cached pure-duration failures. A path passing this full original search wins immediately. It must have the same points, curve, frames and tie order as the old policy.

Only if this complete original search returns its known planning failure without steps/time/integration/targets changing, create another fresh private planning copy of the SAME boundary and rerun the same bounded target list with .12. No retained/holding reset, no tick, no deadline restart. A failed Cartesian query does not yield reusable complete points, so orientation failures require re-solving, unlike cached duration-only retries. Worst case14 geometric candidate solves instead of7; each solve keeps the original seed/iteration limits. Report phase probe counts and wall CPU cost; do not hide it under original7.

Use private cfg objects, not mutation of Runtime.cfg or Machine.c: replace the copy's cfg and, if an API consults sim.cfg, replace that copy's reference too. The live config and original physical state remain untouched. Keep private shadow/inverse/evidence/controller buffers as loaded_planning_copy already does. RNG is per-query fixed default_rng, so there is no global RNG stream to rewind.

Buffer probe events privately. Do not transfer failed candidate strict flags, counters, last-step dedup maps or events into the live runtime. Return a proposal containing the path/frames, source boundary digest, selected geometric target, original-search failure summary and policy evidence. If the selected returned path required the relaxed phase, explicitly commit a planning-only policy event to live before execution. This is not an executed motion violation. Conservative query evidence from the selected geometric candidate may still include IK knots omitted by a final shortcut; record this uncertainty rather than claiming every query was executed. If exact selected-path orientation maxima are needed, they require explicit target provenance per curve, not averaging accepted query errors.

The live caller validates source digest and performs normal execution, guards and lift postcondition. The final task result remains actual completion. Proposal objects must contain copied numeric curves only, no bound methods into the private runtime.

## Why transport/place needs a larger boundary design

Current place interleaves planning and actual action: optional combined-descent alignment proposal, actual transport_align, then descent with original/saved-alignment reference alternatives. An original alignment can physically complete before descent fails, and Machine may then invoke arrival rescreen. A wrapper catching any place Fault and retrying .12 would silently retry executed motion and is invalid.

A safe first later scope is an explicitly extracted zero-motion planner for a single actual boundary (alignment OR descent/release), exhausting its existing reference/geometry alternatives first. It may relax only that boundary, not undo or rerun an alignment that already executed. To guarantee preference over all original arrival alternatives as well, Machine must own the broader selection: preserve the current zero-motion fault, exhaust original18-base screening before permitting orientation fallback. This is a higher-level policy change and should not be bundled with the small lift fix.

## Placement rescreen policy

Materialize the finite original candidate list once (max18, no generator reuse). Phase1 privately screens all originally allowed bases at.05, preserving nominal ordering and existing first-qualified choice. If none qualify, phase2 may screen the SAME18 at.12. This is at most36 qualification calls, not18; declare and bound that CPU cost. Each base uses a fresh clone of the same actual boundary. No base from the orientation phase can precede a phase1 qualified base.

The returned base proposal must carry the selected orientation policy explicitly. Actual navigate is always real, followed by force checks and remember_grasp. Actual arrival planning should try .05 first then the selected .12 only on zero-motion failure at its defined boundary. A geometric prediction is never a promise that the actual navigation/arrival will qualify. A candidate selected under.12 without carrying policy to real replanning either fails pointlessly or invites global cfg mutation; both should be avoided.

## Required tests before any physical comparison

1. Case4-shaped mock: first candidate requires orientation relaxation, later original candidate fits. Original later path wins and output curve/frames match legacy exactly.
2. Original all-fail then bounded relaxed phase, max14 geometry calls; per-query seed limits unchanged. No recursion/retry after execution.
3. Successful old path causes no relaxed solves and no new warning; failed private probes never change live strict flags/counters/config/integration/targets.
4. If no candidate qualifies, preserve original failure as primary with secondary diagnostic evidence, not a fabricated success.
5. Selected relaxed proposal logs planning-only evidence and actual execute still can fail contact/tilt/collision.
6. Screen-phase1 qualified candidate wins over phase2 nominal; materialized candidates identical across phases and total36 explicit.

Recommendation: freeze/test lift-only first using .05 live baseline. Keep placement and arrival globally .05 until their extracted planning boundaries and policy-carrying proposal contracts are implemented. No production changes or physics were performed for this design.
