import importlib.util,json,sys
from pathlib import Path
import pytest


def module():
    directory=Path(__file__).resolve().parents[1]/'runs/vla_deploy_20261001'
    sys.path.insert(0,str(directory))
    spec=importlib.util.spec_from_file_location('v21grasp_supervisor',directory/'supervise_grasp_escape_measured_tracking_v21.py')
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod


def test_new600tick_command_is_explicit_private_candidate_and_never_launches_on_import():
    m=module();cmd=m.command()
    assert '--private-oracle-contact-escape' in cmd and '--private-oracle-measured-tracking' in cmd
    assert cmd[cmd.index('--max-skill-steps')+1]=='600'
    assert 'v21' in str(m.RELEASE) and 'measured_tracking_v21' in str(m.OUTPUT)


def test_oracle_rejections_derived_from_authoritative_events_even_legacy_topkey_missing(tmp_path):
    m=module();path=tmp_path/'events.jsonl'
    path.write_text('\n'.join(json.dumps({'status':s}) for s in ['oracle_label_collected','oracle_rejected','oracle_rejected']))
    report=dict(oracle_queries=3,oracle_labels=1,results=[dict(oracle_queries=3,oracle_labels=1,oracle_rejected=2)])
    assert m.oracle_counts(report,path)['rejected']==2
    report['oracle_rejected']=0
    with pytest.raises(ValueError,match='disagree'):m.oracle_counts(report,path)
