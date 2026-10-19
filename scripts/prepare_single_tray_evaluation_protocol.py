"""CPU prepare by default. New formal scenes require --generate and full success."""
import argparse,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from r1pro_teleop.single_tray_lab.evaluation_population import population,generate_protocol,workspace_scope

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--training-seeds',required=True,type=Path);p.add_argument('--success-case',type=Path);p.add_argument('--output',type=Path);p.add_argument('--generate',action='store_true');a=p.parse_args()
 seeds=json.loads(a.training_seeds.read_text());rows=population(seeds)
 if a.generate:
  if a.success_case is None or a.output is None:p.error('--generate requires --success-case and --output')
  print(json.dumps(generate_protocol(a.success_case,a.output,seeds)))
 else:print(json.dumps(dict(status='prepared_not_published',population=rows,workspace_scope=workspace_scope(),requires='complete_y0_t08_success_source_and_explicit_generate',strict_contact_report=dict(definition='task_complete_and_all_guarded_hard_le_3mm_soft_le_5mm',missing_evidence='unavailable_never_passed'),paired_strict_report='unavailable_separate_control_variant_not_defined')))
if __name__=='__main__':main()

