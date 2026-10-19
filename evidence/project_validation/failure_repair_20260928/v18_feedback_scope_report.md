# v18 yaw-feedback scope audit

Read-only event/result audit of completed cases 4, 5, 8 and 16 in `robust_v18_20260929/runs/ablation`. The independent script reads no HDF5 and does not change labels. Full structured events, operation targets and rejection details are in `v18_feedback_scope_audit.json`.

Branch definitions are reconstructed from actual events: **S** is source separation (`free_retreat=False`, `withdraw_free=False`); **R** reuses retained contact (`free_retreat=True`, `withdraw_free=False`); **W** combines free-arm withdrawal (`free_retreat=True` and the preceding measured lift escape exceeds 5 mm). This matches the frozen controller branch, not a case-number classification.

Each sequence entry below is `start frame / operation / branch / feedback result`. Every rejected feedback candidate listed here was rejected by the unchanged `supported_normal_reference_excursion` guard and continued the original suffix.

| Run | Case | All pushes in order | Full case outcome |
|---|---:|---|---|
| feedback | 4 | 473/op1/S/reject; 1524/op2/S/reject; 2010/op2/R/reject; 2861/op3/W/reject | Success, 158.25 s |
| feedback | 5 | 403/op1/S/reject; 2463/op3/W/**accepted**; 3285/op4/W/not reached | op4 push planning fails before motion, 164.25 s |
| feedback | 8 | 412/op1/S/reject; 1459/op2/S/reject; 1945/op2/R/reject | op2 physical table support loss, 99.05 s |
| feedback | 16 | 422/op1/S/reject; 1467/op2/S/reject; 1953/op2/R/reject | op2 physical table support loss, 99.45 s |
| command_feedback | 4 | 473/op1/S/**accepted** | Source push loses real table support, 25.75 s |
| command_feedback | 5 | 403/op1/S/**accepted**; 2463/op3/W/**accepted**; 3283/op4/W/not reached | op4 push planning fails before motion, 164.15 s |
| command_feedback | 8 | 412/op1/S/**accepted**; 1439/op2/S/**accepted**; 1924/op2/R/reject; 2777/op3/W/reject | Success, 154.20 s |
| command_feedback | 16 | 422/op1/S/**accepted**; 1447/op2/S/**accepted**; 1932/op2/R/reject | op2 physical table support loss, 98.65 s |

The unmodified baseline succeeds only on case 4 in this four-case subset. The `feedback` group also succeeds only on case 4; the `command_feedback` group succeeds only on case 8. These are 1/4 outcomes for each group, not a 400-scene success-rate estimate.

## What the stage evidence does and does not support

Without command-reference changes, all seven S candidates and all three R candidates were rejected. The sole accepted update was case 5's op3 W push; it completed, and the episode progressed to another tray (op4, tray 0). That later push required at least 3.0 s against 2.9 s available, before any feedback could run. Its failure is not a feedback suffix rejection and does not show that the successful op3 correction was ineffective.

With command-reference changes, all six S updates were accepted. Case 4 then fails during its first S push, but case 8 succeeds after two accepted S updates. Case 8's subsequent R and W feedback attempts were both rejected, so the only accepted feedback changes on that successful trajectory are the two early S updates. Removing all non-W feedback would remove these changes too. These runs do not isolate command-reference changes from the feedback intervention; a same-source command-only control is needed for causal attribution.

A general `withdraw_free_only` scope is therefore a reasonable **bounded A/B hypothesis** that confines intervention to the branch where the original private success was demonstrated. It is not yet an evidence-backed improvement in complete success rate, nor can all non-W updates be called harmful. In the `feedback` group it would mostly avoid unnecessary rejected planning work, since non-W updates did not execute anyway. In the `command_feedback` group it could preserve the old case 4 behavior but could also remove the trajectory changes associated with case 8's success. Do not hard-code case exceptions or loosen the normal guard to force the rejected candidates through.

No production code or frozen v18/v19 file was edited for this audit.
