"""Host-first preview logging for sharded OpenPI batches; no model math changes."""
from __future__ import annotations
import ast
from contextlib import contextmanager
import hashlib
import inspect
from pathlib import Path
import textwrap


OFFICIAL_TRAIN_SHA256 = 'a550a26b9171b96cc7324f0febd5e48ca0b650693d3066d4e3afcb0687df2005'


def host_preview_images(batch, *, device_get, image_factory):
    import numpy as np
    # Transfer full arrays before CPU indexing. GPU sharded __getitem__ is never
    # invoked for the informational WandB thumbnail path.
    host_images = device_get(dict(batch[0].images))
    arrays = [np.asarray(value) for value in host_images.values()]
    if not arrays:
        raise ValueError('Training preview requires model images')
    return [image_factory(np.concatenate([array[i] for array in arrays], axis=1))
            for i in range(min(5, len(arrays[0])))]


def host_replicated_key(jax, key, sharding, verification_receipts=None, on_verification=None):
    import numpy as np
    host_bits = np.asarray(jax.device_get(jax.random.key_data(key))).copy()
    if host_bits.dtype != np.uint32 or host_bits.ndim != 1 or not host_bits.size:
        raise ValueError('Host-first RNG key bits must be nonempty uint32 vector')
    impl = jax.random.key_impl(key)
    replicated_bits = jax.device_put(host_bits, sharding)
    shards = list(replicated_bits.addressable_shards)
    if len(shards) < 2:
        raise ValueError('Host-first RNG requires at least two actual device replicas')
    expected_devices = getattr(sharding, 'device_set', None)
    if expected_devices is not None and {shard.device for shard in shards} != set(expected_devices):
        raise ValueError('Host-first RNG actual replica devices differ from the mesh')
    for shard in shards:
        if not np.array_equal(np.asarray(jax.device_get(shard.data)), host_bits):
            raise ValueError('Host-first replicated RNG bits differ on a GPU')
    result = jax.random.wrap_key_data(replicated_bits, impl=impl)
    if verification_receipts is not None:
        verification_receipts.append(dict(host_key_sha256=hashlib.sha256(host_bits.tobytes()).hexdigest(),
            key_shape=list(host_bits.shape),key_dtype=str(host_bits.dtype),key_impl=str(impl),
            actual_replica_count=len(shards),actual_devices=[str(getattr(shard,'device','fixture_device')) for shard in shards],
            bits_verified=True))
        if on_verification is not None: on_verification()
    return result


@contextmanager
def host_first_training_preview(module, source_path, *, expected_source_sha256=OFFICIAL_TRAIN_SHA256, bridge_inputs=False, on_verification=None):
    """Replace one known logger assignment in memory and restore on every exit."""
    path = Path(source_path).resolve()
    if Path(module.__file__).resolve() != path:
        raise ValueError('Preview adapter official script path mismatch')
    source_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    if source_sha256 != expected_source_sha256:
        raise ValueError("Preview adapter official source identity mismatch")
    original = module.main
    if original.__code__.co_freevars:
        raise ValueError('Preview adapter requires a standalone official main')
    source, first_line = inspect.getsourcelines(original)
    tree = ast.parse(textwrap.dedent(''.join(source)))
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == 'images_to_log'
                           for target in node.targets)]
    if len(assignments) != 1 or not isinstance(assignments[0].value, ast.ListComp):
        raise ValueError('Preview adapter expected one official images_to_log comprehension')
    expression = assignments[0].value
    if not (isinstance(expression.elt, ast.Call)
            and isinstance(expression.elt.func, ast.Attribute)
            and isinstance(expression.elt.func.value, ast.Name)
            and expression.elt.func.value.id == 'wandb' and expression.elt.func.attr == 'Image'):
        raise ValueError('Preview adapter refused unfamiliar logger expression')
    expected_expression = ast.parse(
        "[wandb.Image(np.concatenate([np.array(img[i]) for img in batch[0].images.values()], axis=1)) "
        "for i in range(min(5, len(next(iter(batch[0].images.values())))))]", mode='eval').body
    if ast.dump(expression, include_attributes=False) != ast.dump(expected_expression, include_attributes=False):
        raise ValueError('Preview adapter refused unfamiliar logger inner expression')
    function = tree.body[0]
    if not isinstance(function, ast.FunctionDef) or function.name != 'main' or function.decorator_list:
        raise ValueError('Preview adapter refused unfamiliar official main')
    assignments[0].value = ast.copy_location(
        ast.Call(func=ast.Name(id='_airport_host_preview_images', ctx=ast.Load()),
                 args=[ast.Name(id='batch', ctx=ast.Load())], keywords=[]), expression)
    if bridge_inputs:
        assignments_mesh = [node for node in function.body if isinstance(node, ast.Assign)
                            and any(isinstance(target, ast.Name) and target.id == 'replicated_sharding'
                                    for target in node.targets)]
        expected_mesh = ast.parse('jax.sharding.NamedSharding(mesh, jax.sharding.PartitionSpec())', mode='eval').body
        if (len(assignments_mesh) != 1
                or ast.dump(assignments_mesh[0].value, include_attributes=False) != ast.dump(expected_mesh, include_attributes=False)
                or not callable(getattr(module, '_load_weights_and_validate', None))):
            raise ValueError('Host-first adapter refused unfamiliar replicated initialization')
        insert_at = function.body.index(assignments_mesh[0]) + 1
        inserted = ast.parse('train_rng = _airport_host_replicated_key(train_rng, replicated_sharding)\n'
                             'init_rng = _airport_host_replicated_key(init_rng, replicated_sharding)').body
        for node in inserted: ast.copy_location(node, assignments_mesh[0])
        function.body[insert_at:insert_at] = inserted
    ast.fix_missing_locations(tree)
    ast.increment_lineno(tree, first_line - 1)
    namespace = dict(original.__globals__)
    namespace['_airport_host_preview_images'] = lambda batch: host_preview_images(
        batch, device_get=module.jax.device_get, image_factory=module.wandb.Image)
    verification_receipts = []
    namespace['_airport_host_replicated_key'] = lambda key, sharding: host_replicated_key(module.jax, key, sharding, verification_receipts, on_verification)
    exec(compile(tree, str(path), 'exec'), namespace)
    module.main = namespace['main']
    audit = dict(adapter='host_first_sharded_preview_logging/1', scope='preview_logging_and_initial_rng_transfer' if bridge_inputs else 'images_to_log_only',
                 scopes=['preview_logging','initial_rng_transfer'] if bridge_inputs else ['preview_logging'],
                 official_source_sha256=source_sha256,
                 device_indexing='CPU_after_complete_batch_host_transfer', model_math_changed=False,
                 replicated_input_bridge=bool(bridge_inputs),
                 rng_bit_verification='required_for_each_initialization_key' if bridge_inputs else 'not_applicable',
                 verification_receipts=verification_receipts,
                 weight_transfer='unchanged_official_numpy_checkpoint_loader')
    try:
        yield audit
    finally:
        module.main = original
