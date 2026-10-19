"""Generate a new single-tray photo-reference scene without touching old collections."""
from pathlib import Path
import argparse, json, sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_lab.scene import generate_scene,LabSceneConfig

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seed',type=int,default=20261005)
    parser.add_argument('--split',choices=('train','val','test'),default='train')
    parser.add_argument('--robot-x',type=float,default=.1)
    parser.add_argument('--tray-y',type=float,default=-.24)
    parser.add_argument('--loaded',action='store_true')
    parser.add_argument('--payloads',nargs='+',choices=('backpack','coat','laptop'),default=['laptop','backpack','coat'])
    parser.add_argument('--physics-only',action='store_true',help='Explicit development fixture without final Blender assets')
    args=parser.parse_args()
    result=generate_scene(args.output,LabSceneConfig(seed=args.seed,split=args.split,robot_x=args.robot_x,
        tray_y=args.tray_y,payloads=tuple(args.payloads)),loaded=args.loaded,require_blender=not args.physics_only)
    print(json.dumps(dict(scene_id=result['scene_id'],xml=result['xml'],source=result['source'],
                         blender_assets_present=result['blender_assets_present'],task_rollouts_validated=0)))

if __name__=='__main__':main()
