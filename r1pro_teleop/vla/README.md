# VLA servo action contract

The policy predicts absolute mobile19 servo commands at 20 Hz. Arm commands
use joint coordinates. Channels 7 and 15 are declared gripper opening commands
in metres; zero means close. They are not a promise that measured finger
separation reaches zero. The existing servo submits opening/2 to each finger;
MuJoCo retains its actuator limits and contact dynamics. A positive finger
joint minimum must not be substituted for the command's zero lower limit.
Training labels and DAgger raw actions keep this original command meaning.

The optional rate limiter starts continuously at measured robot state. Arm
measurements inside mechanical limits may initially lie outside the network
target's conservative joint margin, and enter that margin over finite steps.
Its intermediate reference bounds combine arm mechanical limits, declared
gripper command limits, and the explicit base workspace envelope. The legacy
`physical_bounds` parameter and `physical_lower/upper` artifact fields describe
that reference domain; `reference_bounds_semantics` identifies the distinction.
Reference speed and acceleration statistics use submitted commands; actual
MuJoCo guards remain separate. No live qpos correction or solver is used.

Projection defaults to `bounded`: raw actions outside the declared small
prediction envelope reject the whole chunk. The explicit `actuator_saturation`
mode instead clips every finite action to command limits and requires the
reference rate limiter. Select it with `--actuator-saturation
--reference-rate-limit`; it is mutually exclusive with `--servo-projection`.
Shape and nonfinite failures remain hard errors. Artifacts retain raw actions,
clipped references, masks, normalized severity, and hashes; result fractions
describe how often predictions changed. These are controller interventions,
not changes to task acceptance, and do not establish that clipped chunks were
fully executed. Only completed physical ticks count as executed actions.
