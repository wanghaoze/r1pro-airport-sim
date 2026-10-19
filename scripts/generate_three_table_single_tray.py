"""Generate a fresh registered three-table/one-tray variant; no success claim."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_lab.three_table_scene import generate_three_table_scene

def main():
    root=Path(__file__).resolve().parents[1]
    registry=root/'resources/single_tray_three_table_v1/source_registry'
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--seed',required=True,type=int)
    p.add_argument('--parent-scene',type=Path,default=registry/'ordinary/airport_0004_20270920/scene.json')
    p.add_argument('--parent-manifest',type=Path,default=registry/'parent_manifest.json')
    p.add_argument('--split-registry',type=Path,default=registry/'canonical_split_registry.json')
    p.add_argument('--source-base-distance',type=float,default=.65)
    p.add_argument('--target-base-standoff',type=float,default=.25)
    p.add_argument('--target-tray-x',type=float)
    p.add_argument('--target-base-yaw',type=float,default=0.)
    p.add_argument('--target-yaw-offset',type=float,default=0.,help='Declared approximate alignment offset in radians, at most 15 degrees')
    a=p.parse_args()
    scene=generate_three_table_scene(a.output,a.parent_scene,a.parent_manifest,a.seed,split_registry=a.split_registry,
        source_base_distance_m=a.source_base_distance,target_base_standoff_m=a.target_base_standoff,
        target_tray_x=a.target_tray_x,target_base_yaw=a.target_base_yaw,target_yaw_offset_rad=a.target_yaw_offset)
    print(json.dumps(dict(status='generated_not_physics_verified',scene_id=scene['scene_id'],split=scene['split'],
        parent_scene_id=scene['parent_scene_id'],initial_tray_pose=scene['initial_tray_pose'],
        source_table=scene['source_table'],target_table=scene['target_table'],xml=scene['xml'],
        physical_demo_completed=False,training_started=False)))
if __name__=='__main__':main()
