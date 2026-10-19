"""Explicit task-completion tolerances, with strict evidence retained separately."""
from dataclasses import replace
from .geometry import placement_ok


def completion_criteria(cfg):
    if (getattr(cfg,'acceptance_profile','strict')=='strict' and
            not getattr(cfg,'approximate_completion_enabled',False)):return cfg.criteria
    return replace(cfg.criteria,position_m=max(cfg.criteria.position_m,cfg.completion_position_m),
                   yaw_deg=max(cfg.criteria.yaw_deg,cfg.completion_yaw_deg),
                   gap_max_m=max(cfg.criteria.gap_max_m,cfg.completion_gap_max_m))


def profile_placement_ok(rows,geometry,cfg):
    strict_ok,strict_report=placement_ok(rows,geometry,cfg.criteria,cfg.fps)
    if getattr(cfg,'approximate_completion_enabled',False):
        valid,report=placement_ok(rows,geometry,completion_criteria(cfg),cfg.fps,
            use_actual_gap=True,approximate=True,
            approximate_overlap_cap_m=min(cfg.completion_collision_penetration_m,.02))
        report.update(acceptance_profile='approximate_completion',
            strict_accepted=bool(strict_ok),strict_report=strict_report)
        return valid,report
    if getattr(cfg,'acceptance_profile','strict')=='strict':return strict_ok,strict_report
    valid,report=placement_ok(rows,geometry,completion_criteria(cfg),cfg.fps,use_actual_gap=True)
    # Physical support/release/stability remain mandatory. Completion measures
    # disjoint rotated boundaries; strict evidence retains belt-axis projection.
    report.update(acceptance_profile='completion_first',strict_accepted=bool(strict_ok),strict_report=strict_report)
    return valid,report


def predicate_with_strict_evidence(runtime, strict_predicate, task_predicate, code, detail):
    """The same observed sample must satisfy the explicitly selected predicate."""
    if getattr(runtime.cfg,'acceptance_profile','strict')=='strict':return strict_predicate
    def predicate(observation):
        strict=bool(strict_predicate(observation));accepted=bool(task_predicate(observation))
        if accepted and not strict:
            runtime.record_strict_deviation(code,detail(observation))
        return accepted
    return predicate
