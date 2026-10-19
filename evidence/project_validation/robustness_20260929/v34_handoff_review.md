# v34 actual contact-handoff audit

Actual attempt results only, no preview outcomes counted as episodes. Read-only; no source changes or new physics. Full structured inputs: runs/repair_20260929/v34_handoff_all.json; selected native trace samples: v34_handoff_trace.jsonl.

| Group | support loss | push postcondition | place release | Total |
|---|---:|---:|---:|---:|
| combined |4|2|1|7|
| lift |1|4|1|6|
| nominal |3|1|1|5|
| direct_combined |1|0|0|1|
| total |9|7|3|19|

The group numbers above are failed-attempt counts, not scene indices. All seven push-postcondition failures have tilted trays (6.17–8.43deg), table contacts1–2, and both hands exerting17–24.5N; these are physical unwanted bilateral contact, not purely task-position precision. The three place-release failures are separately addressed by v35 release replanning.

## Representative actual trace

Combined case7 a001 op3: push begins frame2767 with free-left0N, retained-right13.40N, table4, tilt.00017deg. Free command stays37.918mm. By frame2787 free-left3.55N/table0; frame2796 free-left12.38N, measured aperture50.297mm, tilt1.58deg. It fails at actual1.50s with350ms support loss, retained16.47N. Preview original/yaw fail identically; command-reference advances3.2s but then rejects a tray/tray collision during later motion. Exhausted previews execute the declared original fallback, not a verified candidate.

Combined case7 a002 same op3: starts free-left0N/table4. End free-left20.33N/right23.51N, tilt6.37deg/table1. Fixed free-opening37.923mm but measured58.17mm, consistent with the rim driving the partly open fingers apart. Both original/yaw previews reproduce failed postcondition; command-reference planning fails. This is not loss of retaining force.

Lift case6 a002 op3: place descent3.25s+release.8s+wait.95s exhausts5s. Free-left .7866N remains, retained14.03N, table4, level. Command37.001mm/measured37.717mm. v35 release proposal is relevant here; do not duplicate it.

v30b same-case comparison: case7 op3/right retained completed push2.85s through verified yaw-feedback preview; op4 original passed and episode completed. Case6 op3 completed push2.6s with verified yaw-feedback; episode later failed op4 IK. These later-attempt comparisons have different prior physical trajectories and seeds, so no single-control causal attribution is claimed.

## Small preventive candidate (not implemented or qualified)

Code gives every free_retreat a +.10m free TCP destination. However only withdraw_free (pickup lateral shift>.005m) opens the free jaw to the configured full opening and builds a clearance-first waypoint. Ordinary free_retreat keeps the roughly38mm placement-release aperture while the free arm rises concurrently with tray motion. The observed recontact has a concrete mechanism.

A completion-only candidate can continuously interpolate the free-jaw reference from its current target to the original full-open limit over the existing planned free-retreat points, preserving every arm/TCP waypoint and retained jaw closure. Replan the entire joint curve under the same deadline and original collision/camera/velocity/effort checks. Full opening can enlarge collision sweep or duration, so reject if infeasible; do not overwrite actual ctrl after planning. Existing withdraw_free already opens fully and needs no duplicate change. This candidate needs static qualification then actual local/full execution; no success is established here.

## Recovery boundary

Existing recover is not directly compatible with a retained handoff failure. The operation wrapper makes it nonrecoverable; simply flipping that flag leaves retained-contact closure/force guards active while recovery opens both jaws. Support0 with holding=None bypasses its airborne bilateral descent and rejects unsafe_recovery_without_support. A future recovery would need an explicit supported contact-state transition with observed support and collision/tilt eligibility, ordinary physical opening/retreat/regrasp, recovery_used=True and existing bounded retries. Do not clear support timers or release an unsupported tray merely to continue. Prevention is the smaller first experiment.
