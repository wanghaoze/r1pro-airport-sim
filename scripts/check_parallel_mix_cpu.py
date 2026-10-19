"""CPU-only official transform and Observation contract; no model initialization."""
import os
os.environ['JAX_PLATFORMS']='cpu'
os.environ['CUDA_VISIBLE_DEVICES']=''
import argparse,json
from pathlib import Path
import numpy as np
import train_pi05_parallel_real_mix as trainer

def main():
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);a=p.parse_args()
    from openpi import transforms
    from openpi.shared import normalize
    from openpi.models import model
    from r1pro_teleop.vla.training import AirportInputs
    cfg,spec=trainer.config_for(a.run)
    norm={k:normalize.NormStats(**{f:np.asarray(v) for f,v in row.items()}) for k,row in json.loads((a.run/'norm.json').read_text()).items()}
    normalize.save(cfg.assets_dirs/spec.dataset_repo_id,norm)
    data=cfg.data.create(cfg.assets_dirs,cfg.model)
    transform=transforms.compose([AirportInputs('legacy'),transforms.Normalize(norm,use_quantiles=True),*data.model_transforms.inputs])
    cache=trainer.MixedCache(a.run);rows=[]
    schedule=np.load(a.run/'sample_indices.npy',mmap_mode='r')
    for index in sorted(set(map(int,schedule[:min(10,len(schedule))].ravel())))[::max(1,min(20,schedule.size)//3)]:
        transformed=transform(cache.get(index));actions=transformed.pop('actions')
        obs=model.Observation.from_dict({k:np.expand_dims(v,0) if isinstance(v,np.ndarray) else {n:np.expand_dims(x,0) for n,x in v.items()} if isinstance(v,dict) else v for k,v in transformed.items()})
        if actions.shape!=(20,32) or not np.isfinite(actions).all():raise ValueError('invalid_transformed_actions')
        rows.append(dict(index=index,actions_shape=list(actions.shape),state_shape=list(obs.state.shape),images={k:list(v.shape) for k,v in obs.images.items()}))
    trainer.write(a.run/'cpu_transform_smoke.json',dict(passed=True,device='cpu',model_initialized=False,gradient_updates=0,rows=rows))

if __name__=='__main__':main()
