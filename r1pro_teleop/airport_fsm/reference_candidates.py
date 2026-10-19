"""One alignment-reference alternative after a zero-motion planning rejection."""
import numpy as np
from .contracts import Fault
from .arrival_replanning import PLANNING_FAILURES


def plan_reference_candidate(runtime, planner, saved_relation, *, enabled,
                             check_command, actual_alignment=True):
    """Never catch execution; keep original successful reference preparation."""
    if not enabled or saved_relation is None:
        return planner()
    start_step = runtime.steps
    start_time = float(runtime.d.time)
    held_tray = runtime.holding
    deadline = getattr(runtime, 'primitive_deadline_step', None)
    rebuilt = {side: value.copy() for side, value in runtime.grasp_rel.items()}
    try:
        return planner()
    except Fault as original:
        if (original.code not in PLANNING_FAILURES or runtime.steps != start_step or
                float(runtime.d.time) != start_time or held_tray is None or runtime.holding != held_tray or
                runtime.retained_contact is not None or
                getattr(runtime, 'primitive_deadline_step', None) != deadline):
            raise
        if actual_alignment:
            forces = runtime.observation()['gripper_contact_force'][runtime.holding]
            if not np.all(np.isfinite(forces)) or np.any(forces <= runtime.cfg.criteria.contact_n):
                raise
        # Compliance faults are not alternative-planning failures and must escape.
        check_command(runtime)
        runtime.grasp_rel = {side: value.copy() for side, value in saved_relation.items()}
        runtime.trace.event('placement_command_reference_candidate', stage='started',
            original_reason=original.code, original_detail=original.detail,
            source='completed_actual_alignment' if actual_alignment else 'private_predicted_alignment',
            primitive_deadline_step=deadline, start_step=start_step, physical_start=start_time)
        try:
            result = planner()
        except Fault as alternative:
            runtime.grasp_rel = rebuilt
            if (alternative.code not in PLANNING_FAILURES or runtime.steps != start_step or
                    float(runtime.d.time) != start_time or
                    getattr(runtime, 'primitive_deadline_step', None) != deadline):
                raise
            runtime.trace.event('placement_command_reference_candidate', stage='rejected',
                original_reason=original.code, alternative_reason=alternative.code,
                alternative_detail=alternative.detail, selected=False,
                elapsed_steps=runtime.steps-start_step, physical_elapsed_s=float(runtime.d.time)-start_time)
            raise original from alternative
        if (runtime.steps != start_step or float(runtime.d.time) != start_time or
                getattr(runtime, 'primitive_deadline_step', None) != deadline):
            raise Fault('placement_reference_planner_changed_execution')
        runtime.trace.event('placement_command_reference_candidate', stage='selected',
            original_reason=original.code, selected=True,
            elapsed_steps=runtime.steps-start_step, physical_elapsed_s=float(runtime.d.time)-start_time,
            primitive_deadline_step=runtime.primitive_deadline_step if hasattr(runtime,'primitive_deadline_step') else None,
            qualification='planning_candidate_only_original_deadline_and_physics_guards')
        return result
