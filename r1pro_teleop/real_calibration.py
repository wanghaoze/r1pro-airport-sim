"""Opt-in real-timing simulation; existing ideal simulation remains unchanged."""
from collections import deque
import json
from pathlib import Path

import mujoco
import numpy as np

from .airport_recording import AirportSimulation
from .core import CAMERAS,XR_TO_ROBOT


class RealCalibratedAirportSimulation(AirportSimulation):
    """Apply measured command/observation delays and native camera sizes."""
    def __init__(self, scene, calibration, *args, **kwargs):
        self.calibration_path=Path(calibration).resolve()
        self.calibration=json.loads(self.calibration_path.read_text())
        kwargs["render"]=False
        super().__init__(scene,*args,**kwargs)
        self._renderers={};self._render_data=mujoco.MjData(self.model)
        self.camera_shapes={"head":tuple(self.calibration["head_h264_resolution_verified_by_ffprobe"])[::-1],
          "left_wrist":(720,1280),"right_wrist":(720,1280)}
        cams=self.calibration["cameras"]
        self.camera_delay={"head":np.mean([cams["head_left"]["header_to_bag_ms"]["p50"],cams["head_right"]["header_to_bag_ms"]["p50"]])/1000,
          "left_wrist":cams["left_wrist"]["header_to_bag_ms"]["p50"]/1000,
          "right_wrist":cams["right_wrist"]["header_to_bag_ms"]["p50"]/1000}
        self.arm_delay=self.calibration["timing"]["arm_target_to_feedback_median_ms"]/1000
        grips=[]
        # The report is stored next to the profile in the server calibration run.
        report_path=Path(self.calibration["source_report"])
        if not report_path.is_absolute(): report_path=(self.calibration_path.parents[3]/report_path).resolve()
        if report_path.exists():
            report=json.loads(report_path.read_text())
            for side in ("left_gripper","right_gripper"):
                grips += [x["estimated_lag_ms"] for x in report["target_to_feedback_tracking"][side].values() if x.get("available")]
        self.gripper_delay=(np.median(grips)/1000 if grips else .2925)
        self._reset_latency_state()

    def _reset_latency_state(self):
        self._arm_queue=deque();self._gripper_queue=deque()
        self._applied=self.target.copy()
        self._history=deque([(float(self.data.time),self.data.qpos.copy(),self.data.qvel.copy())])

    def reset(self):
        super().reset()
        if hasattr(self,"calibration") and hasattr(self,"target"): self._reset_latency_state()

    def step(self):
        self._arm_queue.append((float(self.data.time)+self.arm_delay,self.target.copy()))
        self._gripper_queue.append((float(self.data.time)+self.gripper_delay,self.target.copy()))
        for _ in range(self.nstep):
            while self._arm_queue and self._arm_queue[0][0] <= self.data.time:
                _,command=self._arm_queue.popleft();self._applied[:7]=command[:7];self._applied[8:15]=command[8:15]
            while self._gripper_queue and self._gripper_queue[0][0] <= self.data.time:
                _,command=self._gripper_queue.popleft();self._applied[7]=command[7];self._applied[15]=command[15]
            for side,start in (("left",0),("right",8)):
                for i in range(7):self.data.ctrl[self.model.actuator(f"{side}_arm_joint{i+1}_target").id]=self._applied[start+i]
                self.data.ctrl[self.model.actuator(f"{side}_gripper_target").id]=self._applied[start+7]/2
            if self.base_control_available:
                for i,name in enumerate(("x","y","yaw")):
                    self.data.ctrl[self.model.actuator(f"agent_base_{name}_target").id]=self.base_target[i]
            mujoco.mj_step(self.model,self.data)
            self._history.append((float(self.data.time),self.data.qpos.copy(),self.data.qvel.copy()))
            while self._history and self._history[0][0] < self.data.time-1:self._history.popleft()
        if not np.isfinite(self.data.qpos).all():raise RuntimeError("nonfinite real-calibrated simulation state")
        self.workspace_rotation=self.data.body("base_link").xmat.reshape(3,3).copy();self.xr_to_world=self.workspace_rotation@XR_TO_ROBOT

    def image(self,name="overview"):
        if name not in CAMERAS:return super().image(name)
        height,width=self.camera_shapes[name]
        renderer=self._renderers.get(name)
        if renderer is None:
            renderer=self._renderers[name]=mujoco.Renderer(self.model,height=height,width=width)
        target_time=self.data.time-self.camera_delay[name]
        sample_time,qpos,qvel=min(self._history,key=lambda x:abs(x[0]-target_time))
        self._render_data.qpos[:]=qpos;self._render_data.qvel[:]=qvel;self._render_data.time=sample_time;mujoco.mj_forward(self.model,self._render_data)
        renderer.update_scene(self._render_data,camera=name,scene_option=self.options)
        renderer.scene.flags[mujoco.mjtRndFlag.mjRND_SHADOW]=False;renderer.scene.flags[mujoco.mjtRndFlag.mjRND_REFLECTION]=False
        return renderer.render().copy()

    def close(self):
        for renderer in getattr(self,"_renderers",{}).values():renderer.close()
        self._renderers={};super().close()
