import importlib.util
from pathlib import Path
from types import SimpleNamespace
import hashlib
import numpy as np
import pytest
from r1pro_teleop.vla.training_preview import host_preview_images, host_first_training_preview

class GPUArray:
    def __init__(self, data): self.data=data
    def __len__(self): return len(self.data)
    def __getitem__(self, index): raise AssertionError('GPU slice must never execute')


def batch():
    return (SimpleNamespace(images={key:GPUArray(np.full((8,2,3,3),value,dtype=np.float32))
        for key,value in [('head',1),('left',2),('right',3)]}), np.arange(8))


def cpu_get(images):return {key:value.data.copy() for key,value in images.items()}


def test_full_host_transfer_precedes_any_image_index():
    b=batch();before=[value.data.copy() for value in b[0].images.values()]
    images=host_preview_images(b,device_get=cpu_get,image_factory=lambda image:image)
    assert len(images)==5 and all(image.shape==(2,9,3) for image in images)
    assert np.array_equal(images[0],np.concatenate(before,axis=2)[0])
    assert all(np.array_equal(old,value.data) for old,value in zip(before,b[0].images.values()))


@pytest.fixture
def official(tmp_path):
    path=tmp_path/'train.py'
    path.write_text("""def main(config):
    batch=config
    images_to_log = [wandb.Image(np.concatenate([np.array(img[i]) for img in batch[0].images.values()], axis=1)) for i in range(min(5,len(next(iter(batch[0].images.values())))))]
    wandb.log({'images':images_to_log},step=0)
    return np.sum(batch[1] ** 2)
""")
    spec=importlib.util.spec_from_file_location('preview_official_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.np=np;module.jax=SimpleNamespace(device_get=cpu_get)
    module.wandb=SimpleNamespace(Image=lambda image:image,log=lambda *a,**k:None)
    return module,path


def test_in_memory_adapter_preserves_math_and_vendor_bytes(official):
    module,path=official;raw=path.read_bytes();original=module.main
    with pytest.raises(AssertionError,match='GPU slice'):original(batch())
    with host_first_training_preview(module,path,expected_source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()) as audit:
        assert module.main(batch())==140
        assert audit['model_math_changed'] is False and audit['scope']=='images_to_log_only'
    assert module.main is original and path.read_bytes()==raw


def test_restores_original_after_training_failure(official):
    module,path=official;original=module.main
    with pytest.raises(RuntimeError,match='training failed'):
        with host_first_training_preview(module,path,expected_source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()):raise RuntimeError('training failed')
    assert module.main is original


def test_wrong_official_source_path_rejects(official):
    module,path=official
    with pytest.raises(ValueError,match='path mismatch'):
        with host_first_training_preview(module,path.with_name('other.py')):pass


@pytest.mark.parametrize('code',[
    'def main(config):\n    images_to_log=[]\n',
    'def main(config):\n    images_to_log=[print(i) for i in range(5)]\n',
    'def main(config):\n    images_to_log=[wandb.Image(i) for i in range(5)]\n    images_to_log=[wandb.Image(i) for i in range(5)]\n'])
def test_unfamiliar_logger_fails_closed(official,code):
    module,path=official;path.write_text(code)
    spec=importlib.util.spec_from_file_location('preview_refused_fixture',path)
    replacement=importlib.util.module_from_spec(spec);spec.loader.exec_module(replacement)
    with pytest.raises(ValueError,match='adapter'):
        with host_first_training_preview(replacement,path,expected_source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()):pass


def test_empty_images_rejects():
    with pytest.raises(ValueError,match='requires model images'):
        host_preview_images((SimpleNamespace(images={}),),device_get=lambda x:x,image_factory=lambda x:x)


def test_actual_adapter_rejects_unknown_source_hash(official):
    module,path=official
    with pytest.raises(ValueError,match="source identity"):
        with host_first_training_preview(module,path):pass


class FakeKey:
    def __init__(self,bits,impl='threefry2x32'):
        self.bits=np.asarray(bits,dtype=np.uint32);self.impl=impl


def fake_jax(corrupt=False):
    def put(bits,sharding):
        return SimpleNamespace(addressable_shards=[SimpleNamespace(data=bits.copy()),
            SimpleNamespace(data=np.zeros_like(bits) if corrupt else bits.copy())])
    def get(value):
        if isinstance(value,dict):return {key:(item.data.copy() if isinstance(item,GPUArray) else item) for key,item in value.items()}
        return value
    return SimpleNamespace(device_get=get,device_put=put,
        random=SimpleNamespace(key_data=lambda key:key.bits,key_impl=lambda key:key.impl,
            wrap_key_data=lambda value,impl:SimpleNamespace(shards=value.addressable_shards,impl=impl)),
        sharding=SimpleNamespace(NamedSharding=lambda mesh,spec:'replicated',PartitionSpec=lambda:()))


def test_typed_rng_bridge_preserves_bits_and_impl():
    from r1pro_teleop.vla.training_preview import host_replicated_key
    key=FakeKey([0,1234567]);result=host_replicated_key(fake_jax(),key,'replicated')
    assert result.impl==key.impl
    assert all(np.array_equal(shard.data,key.bits) for shard in result.shards)


def test_rng_replica_corruption_rejects_before_training():
    from r1pro_teleop.vla.training_preview import host_replicated_key
    with pytest.raises(ValueError,match='RNG bits differ'):
        host_replicated_key(fake_jax(corrupt=True),FakeKey([0,1234567]),'replicated')


def test_input_bridge_retains_parameter_values_dtype_and_restores(official):
    module,path=official
    path.write_text("""def _load_weights_and_validate(loader,shape):
    return {'w':np.arange(4,dtype=np.float32).reshape(2,2)}
def init_train_state(config,init_rng,mesh):
    return _load_weights_and_validate(None,None)
def main(config):
    batch=config
    train_rng=key
    init_rng=key
    replicated_sharding=jax.sharding.NamedSharding(mesh,jax.sharding.PartitionSpec())
    images_to_log = [wandb.Image(np.concatenate([np.array(img[i]) for img in batch[0].images.values()], axis=1)) for i in range(min(5,len(next(iter(batch[0].images.values())))))]
    params=init_train_state(config,init_rng,mesh)
    return train_rng,init_rng,params
""")
    spec=importlib.util.spec_from_file_location('preview_input_fixture',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.GPUArray=GPUArray;module.np=np;module.jax=fake_jax();module.mesh='mesh';module.key=FakeKey([0,1234567]);module.wandb=SimpleNamespace(Image=lambda x:x)
    original_main=module.main;original_weights=module._load_weights_and_validate
    with host_first_training_preview(module,path,expected_source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bridge_inputs=True) as audit:
        train_rng,init_rng,params=module.main(batch())
        assert audit['replicated_input_bridge'] and len(audit['verification_receipts'])==2
        assert all(r['bits_verified'] and r['actual_replica_count']==2 for r in audit['verification_receipts'])
        assert np.array_equal(params['w'],np.arange(4,dtype=np.float32).reshape(2,2))
        assert params['w'].dtype==np.float32
        assert all(np.array_equal(shard.data,[0,1234567]) for shard in train_rng.shards+init_rng.shards)
    assert module.main is original_main and module._load_weights_and_validate is original_weights


def test_empty_rng_replicas_cannot_verify():
    from r1pro_teleop.vla.training_preview import host_replicated_key
    jax=fake_jax();jax.device_put=lambda *args:SimpleNamespace(addressable_shards=[])
    receipts=[]
    with pytest.raises(ValueError,match='actual device replicas'):
        host_replicated_key(jax,FakeKey([0,1234567]),'replicated',receipts)
    assert receipts==[]


def test_rng_receipt_persistence_runs_only_after_actual_verification():
    from r1pro_teleop.vla.training_preview import host_replicated_key
    receipts=[];snapshots=[]
    host_replicated_key(fake_jax(),FakeKey([0,1234567]),'replicated',receipts,
        lambda:snapshots.append(list(receipts)))
    assert len(snapshots)==1 and snapshots[0][0]['bits_verified'] is True
    with pytest.raises(ValueError):
        host_replicated_key(fake_jax(corrupt=True),FakeKey([0,1234567]),'replicated',receipts,
            lambda:snapshots.append(list(receipts)))
    assert len(snapshots)==1
