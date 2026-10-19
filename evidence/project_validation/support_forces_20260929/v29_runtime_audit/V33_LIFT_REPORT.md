# v33 lift postcondition read-only audit

Two complete failed actual attempts were examined; no replay, physics step, or source change.

| Variant/case/attempt | Lift seconds | Actual terminal lift | Terminal tilt | Bilateral forces | Support |
|---|---:|---:|---:|---|---|
| ik80/9/a000 | 3.1 | 141.056 mm | 3.414 deg | [13.72592573394595, 13.516181230169334] N | raw tail support/table zero |
| direct_ik80/7/a001 | 3.2 | 127.761 mm | 3.157 deg | [13.946132931420008, 13.506078410253224] N | raw tail support/table zero |

Both fail the original intermediate lift lower bound of 150 mm. Measured tilt remains below 5 degrees; both hands retain force above 13 N. Last eight recorded observations have no support or table contact. This is not evidence of released grip or failure to leave the support surface. The terminal detail lacks support_contact specifically, so terminal table_contact=0 is distinguished from the preceding raw support_contact=0.

A completion-only intermediate-height acceptance range can allow continuation while preserving the commanded lift target, existing trajectory checks, bilateral force, zero support, carried tilt below20 degrees, and final released placement tilt below5 degrees. The proposed80–250 mm/15-degree profile would be an explicit acceptance policy change, not controller improvement. These two cases justify investigating a lower height cutoff but do not themselves establish safe transport at80 mm or a need for15-degree tilt tolerance; future live transport checks remain mandatory and may still reject.

Evidence: v33_lift_postcondition.json. Original failure details and strict-duration exceedance flags are retained. Neither case is a completed task.
