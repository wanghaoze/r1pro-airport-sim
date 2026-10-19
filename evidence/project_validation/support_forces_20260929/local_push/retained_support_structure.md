# Retained-support structure: evidence and one falsifiable candidate

This audit reads existing evidence only. No frozen v21/production changes, new physics process, material changes, relaxed contact rules or modified collection labels.

## What is established

The baseline400 nested audit identifies 56 actual `retained_contact_lost` outcomes with table contact zero while retained right-hand grip remains 9.815–15.419 N. That establishes continued hand contact, not a universal dynamic cause. Existing detailed 2 ms force data cover representative cases, not all 56; do not generalize their measured frequencies to every failed scene.

Exact v11 replay case4 third push contains 6–8 ms real contact gaps despite an otherwise successful episode. Case5's failing push has a longest 6 ms physical gap before its 20 Hz retained-contact timer aborts at 2.70 s. A 20 Hz endpoint sequence can repeatedly sample gaps separated by real substep contacts, making the apparent continuous missing-support interval longer than an individual real gap. This is phase-sensitive failure detection, but the underlying support loss is real. Changing sampling/reset/grace logic would change the contract and is explicitly excluded.

Two exact local force traces show a shared transition:

| Case/window | Support fraction | Mean hand vertical force on tray | Peak table force |
|---|---:|---:|---:|
| 4 third push, 0–.5 s | 100% | -2.405 N | 19.217 N |
| 4, .5–1.5 s | 78.8% | -3.055 N | 61.927 N |
| 4, after1.5 s | 71.4% | +2.745 N | 51.835 N |
| 5 failure, 0–.5 s | 100% | +1.629 N | 15.806 N |
| 5, .5–1.5 s | 93.0% | -4.146 N | 36.465 N |
| 5, 1.5–2.7 s | 60.7% | +2.139 N | 45.415 N |

Positive means upward force on the tray. Early near-static table/hand forces anticorrelate nearly perfectly, then contact impacts and inertia dominate: the same-step anticorrelation weakens substantially. The tray bottom spans roughly 0.14–0.29 mm during moving windows. The observation supports investigating moving-load/unloading transients rather than assuming initial tray tilt alone or assuming grip is lost. It does not identify a proven actuator or contact-model defect.

Existing negative controls matter: v14 smooth substep control still has 6–8 ms gaps and peaks around 50–59 N; uniform full-budget retiming changes success phase and regresses case4; smaller dt, greater arm Kv, and repeated small normal-force compensation did not establish a robust improvement. The ten-update zero-gain C2 refit passed the same abort point without force feedback and still failed final placement. Thus passing a single handoff is not proof of causal stabilization.

## Sole proposed structural candidate: preserve prefix, stretch only the late C2 suffix

Use the already exactly reproduced v11 case5 failed push. Keep its original first 1.50 s reference exactly. At that fixed time, form **one** quintic suffix from the original reference q/v/a to the original q-end/zero-v/zero-a, assigning only the unused original push motion reserve to that suffix. Original motion is 2.75 s plus .10 s verification; candidate may use at most 2.90 s motion plus the same .10 s verification. The remaining suffix is thus 1.40 s rather than 1.25 s. No new wait, endpoint compensation, force gain, path-phase restart or extra feedback update is allowed.

This differs from the rejected uniform-retiming experiment: the first 1.50 s, including establishment of contact and free-arm clearance, is unchanged; reserve is assigned to the interval where measured hand force turns upward. It differs from the ten-update zero-gain control: one exact-C2 continuation, with extra time drawn solely from already available motion budget. It does alter the joint-space suffix geometry, so all checks must be rerun rather than treating it as a certified time scaling.

Required implementation checks before execution: exact polynomial position/velocity/acceleration/jerk extrema, joint bounds, original collision/camera/rigid-grasp path checks, inverse-dynamics effort/power bounds, and the existing retained-hand normal-band constraint at the same boundaries. Any rejection records the reason and leaves the original validated suffix unchanged; no parameter scan. The original physical support/grip guards remain active during execution. Complete push, release, retreat and stable operation acceptance are required.

Falsification: reject this direction if candidate cannot fit all checks; if handoff still fails; if common-window support fraction does not improve or force peaks/longest physical gap worsen; or if local final operation acceptance fails. Report original versus candidate on the same 0–2.70 s window plus each complete push, not averages inflated by stationary verification. A passed local operation would still require full-episode regression, including original success cases4/16, before adoption.

The force-direction evidence is sufficient to formulate this bounded hypothesis but does not yet justify claiming a remedy for all56 cases. No new physics run was started while the32-CPU v21 regression and16-CPU video work are active. The independent analysis script and `retained_support_structure.json` preserve the measured evidence for review before spending another worker.

## Follow-up: measured normal-velocity evidence limits

Read-only analysis of existing2ms minimum-height records finds table-force peaks>30N in19 samples each for case4's third push and case5's failing push. Backward height differences are negative in18/19 (94.7%) and16/19 (84.2%) of these samples. Median height rate during those peaks is respectively-.0601 and-.0324m/s; nonpeak medians are near zero. This supports an impact/recontact interpretation of force peaks, rather than using their mean as a static-load target.

However minimum-vertex height finite difference is not rigid-body COM `qvel` or the active contact's exact normal relative velocity; the selected lowest vertex can change with orientation. Contact force and this velocity proxy are also dynamically coupled, so their association does not identify which servo/path error excites the motion. Existing exported CSVs lack per-contact point velocity and wrist/COM angular velocity. These data are insufficient to claim a new causal control repair or justify another parameter intervention. `retained_support_velocity_proxy.json` records the qualified proxy measurements. No additional physics run is proposed from this evidence alone.
