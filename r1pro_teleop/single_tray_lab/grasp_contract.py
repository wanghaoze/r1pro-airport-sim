"""Allowed tray rims are independent of the fixed table-front base position.

This declares permissions, not measured contact qualification. Missing legacy
metadata is retained as legacy provenance rather than retroactively relabeled.
"""
ALLOWED_LONG_RIMS=('local_y_positive','local_y_negative')
FORBIDDEN_SHORT_RIMS=('local_x_positive','local_x_negative')


def long_rim_contract():
    return dict(schema='airport_single_tray_long_rim_contract/1',coordinate_frame='tray_local',
        allowed_long_rims=list(ALLOWED_LONG_RIMS),forbidden_short_rims=list(FORBIDDEN_SHORT_RIMS),
        same_rim_required=False,handover_rim_change_allowed=True,
        base_placement='table_front_only',base_actuated=False,
        declaration_is_actual_contact_evidence=False)


def validate_long_rim_contract(value):
    if not isinstance(value,dict) or value!=long_rim_contract():
        raise ValueError('single_tray_invalid_long_rim_permission_contract')
    return value


def validate_rim_assignments(assignments):
    """Validate explicit proposed per-arm rim labels; never infer them from force."""
    if not isinstance(assignments,dict) or not assignments or not set(assignments)<= {'left','right'}:
        raise ValueError('single_tray_invalid_arm_rim_assignment')
    if any(rim not in ALLOWED_LONG_RIMS for rim in assignments.values()):
        raise ValueError('single_tray_short_or_unknown_rim_forbidden')
    return assignments
