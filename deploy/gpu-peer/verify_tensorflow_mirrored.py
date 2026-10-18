"""Validate single-process MirroredStrategy, native NCCL and checkpoint restart."""
import argparse
import json
import os
from pathlib import Path
import time

import numpy as np
import tensorflow as tf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gpus', type=int, required=True)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--steps', type=int, default=12)
    parser.add_argument('--stress-iterations', type=int, default=100)
    parser.add_argument('--stress-seconds', type=float, default=0)
    args = parser.parse_args()
    if os.environ.get('NCCL_P2P_DISABLE', '0') != '0':
        raise RuntimeError('Native NCCL acceptance requires P2P enabled')
    if args.gpus < 2 or args.steps < 1 or args.stress_iterations < 1:
        raise RuntimeError('At least two GPUs and positive iteration counts required')
    tf.config.threading.set_intra_op_parallelism_threads(2)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    # Match the NumPy FP32 oracle without A100 TF32 input rounding. This changes
    # the acceptance process only; public image defaults are not modified.
    tf.config.experimental.enable_tensor_float_32_execution(False)
    devices = tf.config.list_physical_devices('GPU')
    if len(devices) != args.gpus:
        raise RuntimeError(f'Expected {args.gpus} GPUs, found {len(devices)}')
    for device in devices:
        tf.config.experimental.set_memory_growth(device, True)
    tf.config.set_soft_device_placement(False)
    strategy = tf.distribute.MirroredStrategy(
        devices=[f'/GPU:{i}' for i in range(args.gpus)],
        cross_device_ops=tf.distribute.NcclAllReduce(),
    )
    with strategy.scope():
        weight = tf.Variable(tf.ones([16, 4]) * 0.1, name='weight')
        optimizer = tf.keras.optimizers.SGD(learning_rate=0.01, momentum=0.9)
        optimizer.build([weight])
        completed = tf.Variable(0, dtype=tf.int64, trainable=False, name='completed')
    checkpoint = tf.train.Checkpoint(weight=weight, optimizer=optimizer, completed=completed)
    manager = tf.train.CheckpointManager(checkpoint, str(args.checkpoint), max_to_keep=1)
    if args.resume:
        if not manager.latest_checkpoint:
            raise RuntimeError('No checkpoint found for restart validation')
        checkpoint.restore(manager.latest_checkpoint).assert_consumed()
    expected_weight = weight.numpy().copy()
    # Keras momentum slot is already restored before the reference is built.
    momentum = optimizer.variables[-1].numpy().copy()
    start = int(completed.numpy())

    @tf.function
    def train(inputs, targets):
        def replica_step(x, y):
            with tf.GradientTape() as tape:
                predictions = tf.matmul(x, weight)
                # The batch size is a validated positive Python constant.
                # Avoid compute_average_loss's string assertion constants in
                # the strict GPU device scope; retain identical normalization.
                loss = tf.reduce_sum(tf.reduce_mean(tf.square(predictions-y), axis=1)) / (args.gpus*8)
            gradient = tape.gradient(loss, weight)
            tf.debugging.assert_all_finite(gradient, 'Invalid local gradient')
            optimizer.apply_gradients([(gradient, weight)])
            return gradient
        gradients = strategy.run(replica_step, args=(inputs, targets))
        return strategy.reduce(tf.distribute.ReduceOp.SUM, gradients, axis=None)

    def check_replicas(variable):
        underlying = getattr(variable, 'value', variable)
        if callable(underlying):
            underlying = variable
        values = strategy.experimental_local_results(underlying)
        if len(values) != args.gpus:
            raise RuntimeError('Variable is not mirrored across all GPUs')
        for value in values[1:]:
            np.testing.assert_array_equal(values[0].numpy(), value.numpy())

    for step in range(start, start + args.steps):
        x = ((np.arange(args.gpus*8*16,dtype=np.float32).reshape(-1,16) + step*13) % 97) / 97
        y = x[:, :4] * 0.75 + 0.1
        def distribute(array):
            def value(context):
                rank = int(context.replica_id_in_sync_group)
                with tf.device(f'/GPU:{rank}'):
                    return tf.constant(array[rank*8:(rank+1)*8])
            return strategy.experimental_distribute_values_from_function(value)
        expected_gradient = x.T @ (x @ expected_weight-y) * (2/(args.gpus*8*4))
        gradient = train(distribute(x), distribute(y)).numpy()
        np.testing.assert_allclose(gradient, expected_gradient, rtol=3e-4, atol=2e-6)
        momentum = 0.9*momentum - 0.01*expected_gradient
        expected_weight += momentum
        np.testing.assert_allclose(weight.numpy(), expected_weight, rtol=3e-4, atol=2e-6)
        for variable in (weight, *optimizer.variables):
            check_replicas(variable)
        completed.assign_add(1)

    @tf.function
    def stress(iteration):
        def replica():
            context = tf.distribute.get_replica_context()
            rank = tf.cast(context.replica_id_in_sync_group, tf.float32)
            base = tf.math.floormod(tf.cast(tf.range(2*1024*1024), tf.float32), 31.)
            result = context.all_reduce(tf.distribute.ReduceOp.SUM, base + rank + tf.cast(iteration % 7, tf.float32))
            expected = base*args.gpus + tf.cast(args.gpus*(args.gpus-1)//2 + (iteration % 7)*args.gpus, tf.float32)
            equal = tf.reduce_all(tf.equal(result, expected))
            # Assert diagnostics include strings, which have no CUDA kernel.
            # Only transfer the scalar verdict; the full comparison stays GPU.
            with tf.device('/CPU:0'):
                tf.debugging.assert_equal(equal, True)
            return tf.reduce_sum(result)
        return strategy.run(replica)
    stress_started = time.monotonic()
    iteration = 0
    while iteration < args.stress_iterations or time.monotonic()-stress_started < args.stress_seconds:
        for result in strategy.experimental_local_results(stress(tf.constant(iteration))):
            result.numpy()
        iteration += 1
        if iteration % 1000 == 0:
            print(json.dumps({'progress':'stress', 'iterations':iteration,
                              'elapsed_seconds':round(time.monotonic()-stress_started, 2)}), flush=True)
    args.checkpoint.mkdir(parents=True, exist_ok=True)
    manager.save(checkpoint_number=int(completed.numpy()))
    print(json.dumps({'framework':'tensorflow', 'version':tf.__version__,
                      'gpu_count':args.gpus, 'single_process_mirrored_strategy':True,
                      'native_nccl':True, 'gradient_reference_match':True,
                      'tensor_float32_enabled':tf.config.experimental.tensor_float_32_execution_enabled(),
                      'replicas_and_optimizer_identical':True,
                      'completed_steps':int(completed.numpy()), 'resumed':args.resume,
                      'stress_iterations':iteration,
                      'stress_seconds':round(time.monotonic()-stress_started, 2)}), flush=True)


if __name__ == '__main__':
    main()
