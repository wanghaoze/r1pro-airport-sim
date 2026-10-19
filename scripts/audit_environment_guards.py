import pathlib,json,ast,hashlib
B=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/releases');release=[B/'coverage_v4_20260928',B/'robust_v24b_20260929'];collections=[release[0]/'runs/firstpass',release[1]/'runs/fresh_verification/baseline'];out=pathlib.Path('/home/michelle/haoze/r1pro-airport-sim/diagnostictools/support_forces_20260929_v1/v4_v24b_regression_audit')
r={};codes={}
for name,root,c in zip(('v4','v24b'),release,collections):
 dep=json.loads((c/'dependencies.json').read_text());r[name]={'physics_environment':dep.get('physics_environment'),'source_hash_checks':{}}
 for f in ('runtime.py','primitives.py','machine.py','geometry.py','trajectory.py','camera_guard.py'):
  p=root/'r1pro_teleop/airport_fsm'/f;sha=hashlib.sha256(p.read_bytes()).hexdigest();r[name]['source_hash_checks'][f]={'actual':sha,'recorded':dep['code'].get('airport_fsm/'+f),'matches':sha==dep['code'].get('airport_fsm/'+f)}
 source=(root/'r1pro_teleop/airport_fsm/runtime.py').read_text();tree=ast.parse(source);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='Runtime')
 codes[name]={f.name:ast.dump(f,include_attributes=False) for f in cls.body if isinstance(f,ast.FunctionDef)}
r['runtime_methods_ast_equal']={method:codes['v4'].get(method)==codes['v24b'].get(method) for method in ('guard','check_retained_contact','camera_guard','_ik_tolerances','cartesian','solve_pair')}
(out/'environment_and_guards.json').write_text(json.dumps(r,indent=2));print(json.dumps(r))
