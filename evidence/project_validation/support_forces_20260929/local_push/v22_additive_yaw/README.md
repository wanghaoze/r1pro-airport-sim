# v22 case5 op4: sole additive yaw correction candidate

Source/controller frozen `robust_v22_20260929`, `runs/ablation/feedback_placement`; actual recorded push-entry state frame3443. Feedback boundary3473 is1.50s into the original2.90s movement, leaving1.40s. No Z change, yaw-scale scan, new time, changed target acceptance or production edit.

## Original comparison

Unmodified local continuation exactly reproduces every available recorded qpos/qvel/action row (maximum errors0). Original feedback observes yaw error+1.492287deg and requests-1.5deg. The existing newly fitted quintic is rejected at suffix fraction.40: commandedZ .8890208771m is6.858397micrometers below unchanged lower band .8890277355m. It falls back, then actual retained-contact guard fails with table0, force11.2292438N. Completed20Hz duration is2.15s; including the failed final control interval physical elapsed time is2.20s. These describe the same event, not different failure times. Raw1 lacks an independently recorded post-failure endpoint.

## Additive candidate

`q_candidate(u)=q_original(start+(1-start)u)+delta_q*h(u)`, with `h(u)=10u^3-15u^4+6u^5`. Delta is the same feedback IK endpoint minus the original endpoint. Original curve geometry remains the base; the correction has zero initial q/v/a and endpoint delta/0/0. Original58 movement frames and.10s verification reserve remain unchanged.

Derivative bounds use the original full-path certified bounds, scaled by `(native_duration/actual_duration)^order`, plus each correction derivative's analytic extrema bound via triangle inequality. Position bounds use exact roots of the original suffix's piecewise polynomial derivatives on each remaining segment, plus the monotone correction interval. No dense sample is used as a substitute for these bounds. Existing camera/collision/normal/ID checks remain ordered after the bound checks. One test verifies C2 endpoints, zero-correction identity and consistency of analytic bounds against independent samples.

The sole full-1.5deg candidate is rejected by the **conservative derivative upper bounds**:

| Quantity | Upper-bound / original limit |
|---|---:|
| Velocity |1.00241154|
| Acceleration |.91948867|
| Jerk |1.02188528|

Boundary q/v/a errors are exactly0. Terminal errors are numerical roundoff. Planning cost.0312s. The reused event reason is `exact_derivative_limit`; here that reason means failure to certify the requested conservative bound, **not proof that the actual composite curve necessarily exceeds a limit**. No sharper-bound retry or amplitude scan is run. Normal/camera/ID checks for the candidate are not reached because the earlier bound check fails.

Fallback executes the original validated suffix. The complete force CSV is byte-identical to the original comparison:85.2727% support across2.20s, peak41.8925N, longest real gap4ms. It fails at the same physical event, so release, retreat and stable operation acceptance are not reached. Neither run is a local success or complete Episode success.

Both directories preserve summaries/events/forces; private code is `scripts/diagnostic_additive_suffix.py`, `diagnostic_yaw_additive.py`, `diagnose_additive_yaw.py`; test `scripts/test_diagnostic_additive_suffix.py` passes. `yaw_backtrack_once=true` in the reused runner identifies the private injection hook; this implementation has exactly one full-amplitude trial and no backtracking scale. Direction stopped, production/frozen release unchanged.


## Same candidate, tighter joint certificate (authorized follow-up)

The candidate itself is unchanged. Each remaining original PPoly piece and the additive quintic are composed into a shared local variable using exact rational arithmetic on the stored IEEE coefficients. Combined derivatives receive exact Bernstein convex-hull/de Casteljau subdivision bounds (maximum depth 18, unresolved intervals reject), an L1-scaled floating evaluation reserve, and outward-rounded float endpoints. Joint position uses an exact Bernstein hull. No grid certifies derivatives or joint bounds. Three tests pass, including unchanged evaluation and C2 boundaries.

The new certificate passes: velocity/acceleration/jerk upper-limit ratios 0.9807123143 / 0.9764969797 / 0.9809697547. Three pieces, 170 nodes, largest numerical reserve 2.92489205e-8; full feedback planning including original geometry/normal/ID checks costs 0.6383 wall seconds. Initial q/v/a errors are zero; final errors are roundoff. Same full -1.5 degree request and endpoint, no Z modification.

The local operation now completes original 2.9 second push plus 0.1 second verification, release, retreat, and final verification. Existing retreat endpoint fallback and unloaded tuck timing are used. Whole local operation lasts 18.70 simulation seconds (23.15 wall seconds). Final position error 9.6136 mm, yaw 1.5140 degrees, slot geometry ready, both hand forces zero, eight table contacts. This is not a complete Episode.

Before feedback, all first 750 two-millisecond force/contact/height rows exactly match the original. The runner's whole recorded-prefix qpos mismatch after intervention is expected; it must not be reported as zero for this candidate. Original unmodified comparison separately matched all recorded qpos/qvel/action rows exactly.

Contact stability does NOT uniformly improve. Over the common first 2.20 seconds, support fraction is 85.2727% original versus 84.5455% candidate, peak is identically 41.8925 N, and longest absence grows from 4 to 6 ms. Across candidate's full 3 seconds it is 79.6%, peak 55.4459 N, absence 8 ms. The local 20 Hz guards pass, but true microbounce remains. Detailed statistics: certified_comparison.json. Original full-refit rejection and conservative-certificate rejection remain preserved. This follow-up establishes feasibility and local acceptance for one curve, not a general stability fix.


## Frozen v24b production implementation revalidation

Frozen release `robust_v24b_20260929`, SHA `087da0fd94958ae329a348c09631b96f046d92b36455736cf2f2dd29bdd7ed7c`, was used without source injection; only the default-off additive fallback config was enabled on the original v22 case 5 last-push source. The original production quintic is rejected at the same normal-band excursion, then the production additive candidate is accepted. Strengthened separate-term L1 reserve is 2.98233790e-8; 170 of 8192 total nodes; v/a/j upper ratios 0.98071231433 / 0.97649697974 / 0.98096975474. Additive planning costs 0.67447 wall seconds. Same 2.90-second movement plus 0.10-second verification, full local release/retreat/verify succeeds in 18.70 simulation seconds (24.505 wall seconds). Final pose, force and support values match the prior diagnostic.

All 9350 rows of forces.csv are byte-identical to the prior certified additive positive case. Strengthening the certificate and adding a production fallback after original rejection did not change the selected physical curve. The new before_feedback_errors reports qpos/qvel zero. Its action-error field includes the first changed command at boundary frame 3473 and is 3.8743e-5; it is not an exclusively pre-feedback command window and must not be quoted as a prefix control mismatch. The earlier 750-row contact/force/height prefix identity remains valid. This remains a local diagnostic, not a full Episode success; unchanged microbounce limitations above still apply. Production source was not edited.
