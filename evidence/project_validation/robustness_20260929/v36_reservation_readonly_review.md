# Adaptive reservation integration review

Read-only current v36 working implementation; no source edits or physics. No high-severity false-completion or additive-tolerance issue found.

Scheduler.planning_destination returns an absolute candidate derived from the immutable original goal. Scheduler.choose uses it for returned pending Operation and blocker destination checks; release_prerequisite receives the same callback when a reservation exists. Future geometry checks use reserved positions only for unplaced trays; already accepted neighbours use measured poses.

Original g.goals and goal_yaw remain unchanged. verify_operation requires both tolerance around the commanded candidate and at_nominal against the original goal; slot_geometry_ready independently starts with original g.at_slot. Thus a4cm reservation offset cannot silently add another5cm final displacement. Final _profile_final_acceptance continues to use original goals and actual support/release/stability.

Proposal requires exactly one pending tray and two nominally accepted, released, supported, translationally stable measured trays over the existing verification window. The pending tray is not marked verified by the proposal. Only the current already physically settled operation is allowed to finish; the remaining pending Operation still runs ordinary grasp/navigation/place and verification. Protected trays are checked for pose changes before subsequent scheduling, and blocker handling refuses moving protected trays. Candidate count9, offsets absolute from nominal, at most one active reservation.

Identity/mapping/goal hash, candidate index/absolute destination, protected set and pose are checked on reservation use. Existing tests cover checkpoint invalid-save/restore and private preview copy, as well as cumulative tolerance rejection. These are not evidence of full physical success.

Nonblocking lifecycle note: the early final_acceptance_before_reschedule success return does not clear reservation_plan or emit adaptive_reservation_completed, whereas the later op-is-None success path does. Both perform real final acceptance, so no false success results; the former may leave stale reservation metadata in successful terminal context. Reported to root for owner consideration.
