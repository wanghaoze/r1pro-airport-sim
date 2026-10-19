# Exact original replay: contact-point normal velocity and rocking

Source: frozen `robust_v11_20260929/runs/regression`, case5 finalpush, frame2463. One independent process with BLAS/OMP thread counts1; no controller, physical parameter, guard or budget change. Wall time5.922s. Original failure exactly recurs at2.70s: `retained_contact_lost`, table0, retained force10.2310642007N, close command0. Recorded prefix maximum qpos/qvel/action errors are all **0**. Terminal post-step state is not independently recorded by raw1, so exactness is limited to the recorded prefix and matching failure diagnostics.

## Measurements and conventions

`forces.csv` contains1350 samples at2ms, aligned with real signed table/hand force measurements. Each row includes:

- Tray COM world linear/angular velocity at `body.xipos`, and retained wrist TCP world linear/angular velocity. These use `mj_jac` evaluated at the actual world point, multiplied by real `qvel`.
- Per contact, actual `contact.pos`, geom names, signed force on the tray, COM moment, gap, and `(v_tray(contact.pos)-v_table(contact.pos)) dot table_world_normal`. Positive normal velocity means separation; negative means approach. Both front tables and rear table are explicitly handled by body ID; only true tray/table pairs count. Finger pairs are recorded separately with world-Z relative velocity.
- Command-minus-measured TCP world translation and rotation-vector error from the original target's private forward kinematics. This does not mutate the live model/data. The same-step signed table and hand forces use MuJoCo contact-force extraction, the contact frame transpose and geom1/geom2 action-reaction sign.
- Exact velocity of the current lowest geometry vertex, alongside its index. This replaces the previous finite-difference proxy. Contact velocity remains the authoritative impact measurement.

A local analytic free-body test gives point velocity `[1,4,3]` for translation `[1,2,3]`, angular velocity `[0,0,2]`, point `[1,0,0]`; qpos/qvel/warmstart/ctrl remain unchanged. **1 test passed.** Full replay's zero trajectory error independently confirms that diagnostic queries did not perturb execution.

## Evidence

First physical table-contact absence appears at1.184s, after the early fully supported interval. At19 table-force peaks>30N, **89.4% of qualifying contact-point samples have negative relative normal velocity**, consistent with approach/recontact impacts.

| Interval | Support fraction | COM vertical velocity RMS | Contact-point normal velocity RMS | Contact rotational component RMS | Wrist TCP vertical velocity RMS |
|---|---:|---:|---:|---:|---:|
| 0–.5s |100%|.0000197m/s|.0000298m/s|.0000222m/s|.000369m/s|
| .5–1.5s |93%|.00411m/s|.00810m/s|.00616m/s|.00272m/s|
| 1.5–2.7s |60.7%|.01168m/s|.03335m/s|.02550m/s|.00427m/s|

The rotational component is point normal velocity minus COM vertical velocity; tables are stationary and their normals vertical here. It is an RMS diagnostic, not an additive variance decomposition. In the last interval tray angular-velocity RMS is .0655/.0719rad/s about worldX/Y, while corresponding wrist angular RMS is .0215/.0132rad/s. Thus corner rocking is substantial compared with COM translation and wrist motion; a scalar mean table force hides it.

At the first>30N impact sequence:1.314s has no table contact and upward COM velocity+.00350m/s;1.316s table force32.10N appears with COM velocity-.01207m/s and qualifying contact normal velocities about-.00479 to-.01805m/s; by1.318s COM velocity is+.00614m/s and table force11.77N. Distinct corners can approach and separate simultaneously because of rotation; force and velocity can coexist on soft penetrating contacts. The force peaks occur across many substeps of the20Hz interval, not exclusively at a target update boundary.

## What can and cannot be inferred about excitation

A sustained loaded orientation mismatch accompanies movement: command-minus-measured wrist roll-axis error increases from mean.00589rad during0–.5s to.03018rad after1.5s; pitch-axis error remains approximately-.02584→-.02111rad. Normal position error stays about10–12mm. Mean hand moment about tray COM changes from worldX-.394Nm initially to+.324Nm in.5–1.5s and then-1.087Nm after1.5s; instantaneous magnitudes reach approximately2.07Nm. This is compatible with a retained six-degree-of-freedom clamp imposing changing contact moments against a table-supported tray, followed by angular rocking and corner impacts. It is materially more specific than assuming steady excessive vertical force.

However these measurements are coupled responses, not a causal isolation. They do not identify whether the initial disturbance is dominated by grip contact geometry/friction, position-servo tracking, joint-space path curvature or solver/contact dynamics. Correlation does not prove that subtracting a wrist rotation or changing damping will stabilize the episode. Previous dt/Kv/normal-force-feedback trials remain negative and are not overridden by these observations. No new physical parameter or guard change is justified from this replay alone, and no candidate was added.

Files: `summary.json`, `events.json`, `forces.csv` with full per-contact JSON in each row, and `analysis.json` with windows and an impact sequence. Diagnostic implementation: `scripts/diagnostic_contact_kinematics.py`, runner `scripts/diagnose_original_contact_kinematics.py`, analytic test `scripts/test_diagnostic_contact_kinematics.py`. No H5 was downloaded. This is failure-mechanism evidence, not a successful Episode or proof of a shared cause across all56 baseline cases.

## Supplement: original planned orientation path and tracking phase

A second **planning-only** private process restored the same entry, produced the unmodified original55-frame push reference, sampled its private FK/Jacobian at2ms intervals and stopped before any physical tick. Its endpoint qpos matches the recorded entry exactly; this is not a control candidate. `v11case5_original_reference.csv` preserves1375 planned samples through2.75s. Angular reference velocity is the smooth curve's `J_rotation(q) qdot`; it is not a finite difference across20Hz held commands.

The desired endpoint differs from the initial retained-wrist command only by world yaw-.143410 degrees. Nevertheless the interpolated joint path has a maximum world roll/pitch swing of **.224391 degrees at2.316s**, almost entirely about worldX. Swing is measured after removing the relative world-Z yaw from `R(t) R(0)^T`; this avoids confusing desired yaw with unwanted tilt or Euler-axis singularities. The existing `supported_normal_path_rejection` constrains only TCPZ and cannot detect this rotation excursion. This is a diagnostic observation, not a new guard or threshold.

| Time | Reference swing | Command-minus-measured wrist rotation error X/Y |
|---|---:|---:|
| .50s |.04971deg|+.420/-1.482deg|
| 1.00s |.11654deg|+1.192/-1.431deg|
| First no-support1.184s |.09044deg|+1.631/-1.392deg|
| 1.50s |.14005deg|+1.758/-1.272deg|
| 2.00s |.08006deg|+1.710/-1.215deg|
| Failure2.70s |.00184deg|+1.612/-1.127deg|

These errors are world rotation-vector components, not independently additive Euler angles. The substantial loaded tracking discrepancy persists when the reference swing has nearly returned to zero. At1.5–2.7s, angular velocity RMS aboutX/Y is respectively reference .01433/.00198rad/s, wrist .02149/.01322rad/s, tray .06549/.07187rad/s; reference-minus-wrist angular velocity error RMS is .02012/.01328rad/s. Wrist/tray same-step angular correlations are -.330/-.643, consistent with coupled relative motion, not a rigid tray simply following the reference.

A demeaned unwindowed FFT of the same1.2s interval places95.6%/97.6% of trayX/Y angular-velocity power above50Hz, with largest bins114.17/82.5Hz. The smooth referenceX/Y fractions above50Hz are .0418%/.0000457%. These finite-window spectra are descriptive, not identification of a resonant mode. In particular the actual source uses20Hz held commands: the smooth-reference audit does **not** include their update discontinuities, so it cannot exclude those updates as an excitation source. Existing substep-control negative results likewise prevent claiming command hold is the sole cause.

Conclusion: the joint interpolator does introduce a small unwanted tilt arc; more substantial pose-tracking offsets and high-frequency contact rocking coexist. The evidence does not isolate the arc as the dominant trigger or support adding a new rotation rejection guard that would merely increase planning failures. A targeted alternative would need to preserve the original endpoints/budget and compare actual full-contact behavior after reducing orientation arc; no such candidate is proposed as established or executed here. No production code, camera transform, threshold, physics setting or trajectory label changed.
