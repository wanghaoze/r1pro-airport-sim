"""Explicit experimental strategy seam; the production FSM is unchanged."""
import numpy as np
import json

from ..airport_fsm.machine import Machine
from ..airport_fsm.contracts import Fault, atomic_json
from .common import candidate


class ExperimentMachine(Machine):
    def __init__(self, *args, experiment, **kwargs):
        self.experiment = candidate(experiment)
        self.experiment_origin = "fresh"
        super().__init__(*args, **kwargs)
        metadata = json.loads(self.log.file.attrs["metadata_json"])
        metadata.update(diagnostic_only=True, training_candidate=False,
                        experiment=self.experiment, origin="fresh")
        self.log.file.attrs["metadata_json"] = json.dumps(metadata)

    def _candidate_list(self, tray):
        values = super()._candidate_list(tray)
        params = self.experiment["params"]
        out = []
        for base, face, rim in values:
            base = base.copy()
            heading = base[2]
            base[:2] -= params.get("base_distance_delta_m", 0.) * np.array([np.cos(heading), np.sin(heading)])
            base[:2] += params.get("base_lateral_delta_m", 0.) * np.array([-np.sin(heading), np.cos(heading)])
            base[2] += params.get("base_yaw_delta_rad", 0.)
            out.append((base, face, rim + params.get("rim_x_delta_m", 0.)))
        if self.experiment["strategy"] == "reverse_candidates":
            out.reverse()
        return out

    def align(self, tray, slot, *, forward_offset=0., allow_reach_pull=False, allow_alternate=True):
        if self.experiment["strategy"] != "full_approach_preview":
            return super().align(tray, slot, forward_offset=forward_offset, allow_reach_pull=allow_reach_pull,
                                 allow_alternate=allow_alternate)
        # Evaluate the descent and closure before accepting each pregrasp candidate.
        # Independent experiment; does not claim the earlier v5 regression is fixed.
        original = self.r.cartesian
        had_instance_override = 'cartesian' in vars(self.r)
        original_instance_override = vars(self.r).get('cartesian')

        def checked(goals, **kwargs):
            result = original(goals, **kwargs)
            if self.r.phase == "pregrasp" and not kwargs.get("preview_only", False):
                # Infer the chosen rim template from the submitted pregrasp goals.
                descended = {side: (p - np.array([0., 0., self.c.pregrasp_clearance_m]), R)
                             for side, (p, R) in goals.items()}
                path = original(descended, opening=self.c.gripper_open_m, wrist=True, preview_only=True)
                for opening in np.linspace(self.c.gripper_open_m, self.c.gripper_close_m, 21):
                    q = path[-1].copy()
                    q[[7, 15]] = opening
                    if not self.r._target_valid(q, wrist=True):
                        raise Fault("experiment_closure_preview_rejected", recoverable=True)
            return result

        self.r.cartesian = checked
        try:
            return super().align(tray, slot, forward_offset=forward_offset, allow_reach_pull=allow_reach_pull,
                                 allow_alternate=allow_alternate)
        finally:
            if had_instance_override:
                self.r.cartesian = original_instance_override
            else:
                # Restore descriptor lookup rather than retaining a bound
                # callback which captures this live Runtime in its instance dict.
                vars(self.r).pop('cartesian', None)

    def finish(self, success, acceptance=None, error=None):
        # Experimental traces live outside collection/attempts. Mark the result and
        # all segment records before the worker publishes its completion.
        result = super().finish(success, acceptance, error)
        result.update(experiment=self.experiment, origin=self.experiment_origin,
                      diagnostic_only=True, training_candidate=False,
                      complete_episode_verified=bool(success and self.experiment_origin == "fresh"))
        atomic_json(self.directory / "result.json", result)
        from .common import read
        path = self.directory / "segments.json"
        if path.exists():
            rows = read(path)
            for row in rows:
                row.update(training_candidate=False, diagnostic_only=True)
            atomic_json(path, rows)
        return result
