"""Run fresh pi05 MuJoCo evaluations or train-only private expert DAgger queries."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.vla.rollout import verified_server_metadata,run_rollouts


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--collection',required=True);p.add_argument('--output',required=True)
    group=p.add_mutually_exclusive_group(required=True)
    group.add_argument('--scene-ids',nargs='+');group.add_argument('--indices',nargs='+',type=int)
    p.add_argument('--host',default='127.0.0.1');p.add_argument('--port',type=int,default=8000)
    p.add_argument('--record-substep-controls',action='store_true',help='Journal actual held VLA actuator controls without substep target interpolation')
    p.add_argument('--checkpoint-id');p.add_argument('--training-status')
    p.add_argument('--collect-dagger',action='store_true');p.add_argument('--round-index',type=int,default=0)
    p.add_argument('--query-interval',type=int,default=2);p.add_argument('--max-queries',type=int,default=2)
    p.add_argument('--execute-steps',type=int,default=5);p.add_argument('--max-skill-steps',type=int,default=6000)
    projection=p.add_mutually_exclusive_group()
    projection.add_argument('--servo-projection',action='store_true',help='Explicitly enable bounded actuator projection with raw/projected evidence')
    projection.add_argument('--actuator-saturation',action='store_true',help='Clip all finite predictions to servo command limits; requires --reference-rate-limit')
    p.add_argument('--reference-rate-limit',action='store_true')
    p.add_argument('--rate-fraction',type=float,default=.5)
    p.add_argument('--model-render-max-dim',type=int,default=0,help='Optional same-aspect policy RGB bound; 0 preserves native rendering')
    p.add_argument('--init-arm-tolerance',type=float,default=.06,help='Initialization phase readiness; original strict error audit is retained')
    p.add_argument('--init-gripper-tolerance',type=float,default=.005)
    p.add_argument('--initializer-base-hold',action='store_true',help='Initialization only measured base reference constraint; requires rate limiter')
    p.add_argument('--grasp-base-hold',action='store_true',help='Grasp node only measured base reference constraint; requires rate limiter')
    p.add_argument('--private-oracle-contact-escape',action='store_true',help='Private expert only; requires --collect-dagger')
    p.add_argument('--private-oracle-measured-tracking',action='store_true',help='Private escape qualification only; requires DAgger and contact escape')
    p.add_argument('--navigation-readiness',choices=('legacy','wide_target_cone'),default='legacy',help='Optional navigate-to-tray termination gate; no motion correction or policy input changes')
    p.add_argument('--navigation-bearing-max',type=float,default=.55)
    p.add_argument('--navigation-lateral-max',type=float,default=.28)
    p.add_argument('--navigation-forward-min',type=float,default=.4)
    p.add_argument('--navigation-stable-frames',type=int,default=4)
    args=p.parse_args(argv)
    if args.private_oracle_measured_tracking and not (args.collect_dagger and args.private_oracle_contact_escape):
        p.error('--private-oracle-measured-tracking requires --collect-dagger and --private-oracle-contact-escape')
    if args.private_oracle_contact_escape and not args.collect_dagger:p.error('--private-oracle-contact-escape requires --collect-dagger')
    if args.actuator_saturation and not args.reference_rate_limit:
        p.error('--actuator-saturation requires --reference-rate-limit')
    if args.initializer_base_hold and not args.reference_rate_limit:p.error('--initializer-base-hold requires --reference-rate-limit')
    if args.grasp_base_hold and not args.reference_rate_limit:p.error('--grasp-base-hold requires --reference-rate-limit')
    expected=args.checkpoint_id;checkpoint=None
    if args.training_status:
        from scripts.serve_pi05_airport import verify_training_checkpoint
        _,checkpoint,identity=verify_training_checkpoint(args.training_status)
        if expected and expected!=identity['checkpoint_id']:p.error('Requested checkpoint ID disagrees with local trained weights')
        expected=identity['checkpoint_id']
    if args.collect_dagger and checkpoint is None:p.error('DAgger requires --training-status from the actual learner fine-tune')
    metadata=verified_server_metadata(args.host,args.port,expected_checkpoint_id=expected)
    if args.training_status and identity.get('prompt_mode','legacy') != metadata.get('prompt_mode','legacy'):
        p.error('Local trained checkpoint prompt mode disagrees with loaded server')
    report=run_rollouts(args.collection,args.output,metadata,host=args.host,port=args.port,
        scene_ids=args.scene_ids,indices=args.indices,collect_dagger=args.collect_dagger,private_oracle_contact_escape=args.private_oracle_contact_escape,
        learner_checkpoint=checkpoint,round_index=args.round_index,query_interval=args.query_interval,
        max_queries=args.max_queries,execute_steps=args.execute_steps,max_skill_steps=args.max_skill_steps,
        servo_projection=args.servo_projection,actuator_saturation=args.actuator_saturation,
        reference_rate_limit=args.reference_rate_limit,rate_fraction=args.rate_fraction,model_render_max_dim=args.model_render_max_dim,
        init_arm_tolerance=args.init_arm_tolerance,init_gripper_tolerance=args.init_gripper_tolerance,
        initializer_base_hold=args.initializer_base_hold,grasp_base_hold=args.grasp_base_hold,
        navigation_readiness=args.navigation_readiness,navigation_bearing_max=args.navigation_bearing_max,
        navigation_lateral_max=args.navigation_lateral_max,navigation_forward_min=args.navigation_forward_min,
        navigation_stable_frames=args.navigation_stable_frames,private_oracle_measured_tracking=args.private_oracle_measured_tracking,record_substep_controls=args.record_substep_controls)
    print(json.dumps(report,indent=2),flush=True)
    return 0 if report['status']=='completed' else 2


if __name__=='__main__':raise SystemExit(main())
