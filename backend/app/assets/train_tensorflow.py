"""TensorFlow single/multi-GPU example with per-epoch checkpoint and resume."""

import argparse
import atexit
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

import numpy as np
import tensorflow as tf


BATCH_SIZE = 32
STEPS_PER_EPOCH = 16


def variables_digest(variables):
    digest = hashlib.sha256()
    for variable in variables:
        digest.update(variable.numpy().tobytes())
    return digest.hexdigest()


def weights_digest(model):
    return variables_digest(model.weights)


def verify_replica_state(strategy, model, optimizer):
    for variable in [*model.weights, *optimizer.variables]:
        values = []
        for item in strategy.experimental_local_results(variable.value):
            # Read on the owning GPU before copying to the host. A default-GPU
            # read would itself introduce the peer copy this check must avoid.
            with tf.device(item.device):
                values.append(item.numpy())
        if not all(np.isfinite(value).all() for value in values):
            raise RuntimeError(f"Invalid model/optimizer state: {variable.name}")
        if any(not np.array_equal(values[0], value) for value in values[1:]):
            difference = max(float(np.max(np.abs(values[0] - value))) for value in values[1:])
            raise RuntimeError(f"Replica state differs: {variable.name}, maximum difference={difference}")


def launch_workers(count):
    """One GPU per process avoids intra-process peer copies on this platform."""
    if len(tf.config.list_physical_devices("GPU")) < count:
        raise RuntimeError(f"This instance does not expose the requested {count} GPUs")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "").split(",")
    if visible == [""]:
        visible = [str(index) for index in range(count)]
    sockets = []
    processes = []
    with tempfile.TemporaryDirectory(prefix="tensorflow-workers-") as directory:
        try:
            for _ in range(count):
                listener = socket.socket()
                listener.bind(("127.0.0.1", 0))
                sockets.append(listener)
            addresses = [f"127.0.0.1:{listener.getsockname()[1]}" for listener in sockets]
            for listener in sockets:
                listener.close()
            for index in range(count):
                environment = os.environ.copy()
                environment.update(
                    CUDA_VISIBLE_DEVICES=visible[index],
                    CPCLOUD_TF_WORKER_INDEX=str(index),
                    CPCLOUD_TF_WORKER_STATE=directory,
                    TF_CONFIG=json.dumps({"cluster": {"worker": addresses}, "task": {"type": "worker", "index": index}}),
                )
                processes.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]], env=environment))
            while any(process.poll() is None for process in processes):
                if any(process.poll() not in (None, 0) for process in processes):
                    raise RuntimeError("A TensorFlow worker failed; stopping the remaining workers")
                time.sleep(0.1)
            if any(process.returncode != 0 for process in processes):
                raise RuntimeError("TensorFlow distributed training failed")
            states = [json.loads((Path(directory) / f"worker-{index}.json").read_text()) for index in range(count)]
            for key in ("epoch", "optimizer_iterations", "weights_sha256", "optimizer_sha256"):
                if any(state[key] != states[0][key] for state in states[1:]):
                    raise RuntimeError(f"Distributed workers disagree on {key}")
            print(f"Verified {count} GPU workers: identical model, optimizer and training progress", flush=True)
        finally:
            for listener in sockets:
                listener.close()
            for process in processes:
                if process.poll() is None:
                    process.terminate()
            for process in processes:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


def save_metadata(path, state):
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(state, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--epochs", type=int, default=3, help="Target total completed epochs")
    parser.add_argument("--gpus", type=int, default=1, help="Number of allocated GPUs to use")
    parser.add_argument("--device", choices=("cuda", "cpu"), default="cuda")
    parser.add_argument(
        "--checkpoint", type=Path,
        default=Path(__file__).resolve().parent / "checkpoint-tensorflow",
    )
    parser.add_argument("--resume", action="store_true", help="Restore the latest complete checkpoint")
    args = parser.parse_args()
    if args.epochs < 1 or args.gpus < 1:
        parser.error("--epochs and --gpus must be positive")
    if args.device == "cpu" and args.gpus != 1:
        parser.error("CPU functional checks use --gpus 1")
    worker = os.environ.get("CPCLOUD_TF_WORKER_INDEX")
    compatible = os.environ.get("NCCL_P2P_DISABLE", "0").lower() in {"1", "true", "yes"}
    if args.gpus > 1 and worker is None and compatible:
        launch_workers(args.gpus)
        return
    chief = worker in (None, "0")

    tf.config.threading.set_intra_op_parallelism_threads(2)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    tf.config.set_soft_device_placement(False)
    if args.device == "cuda":
        devices = tf.config.list_physical_devices("GPU")
        local_count = 1 if worker is not None else args.gpus
        if len(devices) < local_count:
            raise RuntimeError(
                f"Requested {args.gpus} GPUs, but this instance exposes {len(devices)}. "
                "Use the TensorFlow GPU image and your allocated GPU count."
            )
        selected = devices[:local_count]
        tf.config.set_visible_devices(selected, "GPU")
        for device in selected:
            tf.config.experimental.set_memory_growth(device, True)
        names = [f"/GPU:{index}" for index in range(local_count)]
    else:
        tf.config.set_visible_devices([], "GPU")
        names = ["/CPU:0"]
    strategy = (
        tf.distribute.MultiWorkerMirroredStrategy(
            communication_options=tf.distribute.experimental.CommunicationOptions(
                implementation=tf.distribute.experimental.CommunicationImplementation.RING,
            ),
        )
        if worker is not None else (
            tf.distribute.MirroredStrategy(devices=names, cross_device_ops=tf.distribute.NcclAllReduce())
            if args.gpus > 1 else tf.distribute.OneDeviceStrategy(names[0])
        )
    )
    replicas = strategy.num_replicas_in_sync
    if replicas != args.gpus:
        raise RuntimeError("Distributed GPU count does not match the requested count")
    checkpoint_directory = args.checkpoint
    if not chief:
        temporary = tempfile.TemporaryDirectory(prefix="tensorflow-worker-checkpoint-")
        atexit.register(temporary.cleanup)
        checkpoint_directory = Path(temporary.name)
    with strategy.scope():
        model = tf.keras.Sequential([
            tf.keras.layers.Input((4,)),
            tf.keras.layers.Dense(
                8, activation="relu", kernel_initializer=tf.keras.initializers.GlorotUniform(42),
            ),
            tf.keras.layers.Dense(1, kernel_initializer=tf.keras.initializers.GlorotUniform(43)),
        ])
        optimizer = tf.keras.optimizers.Adam(0.001)
        optimizer.build(model.trainable_variables)
        epoch = tf.Variable(0, dtype=tf.int64, trainable=False)
        saved_replicas = tf.Variable(replicas, dtype=tf.int64, trainable=False)
        checkpoint = tf.train.Checkpoint(
            model=model, optimizer=optimizer, epoch=epoch, saved_replicas=saved_replicas,
        )
        _ = checkpoint.save_counter
        manager = tf.train.CheckpointManager(checkpoint, str(checkpoint_directory), max_to_keep=2)
    state_path = args.checkpoint / "training-state.json"
    restored = False
    if args.resume:
        latest_checkpoint = tf.train.latest_checkpoint(str(args.checkpoint))
        if not latest_checkpoint:
            raise RuntimeError(f"No complete checkpoint in {args.checkpoint}")
        # Restore in the distribution scope so every mirrored variable and Adam
        # slot is assigned on all replicas, including the optimizer iteration.
        with strategy.scope():
            checkpoint.restore(latest_checkpoint).assert_consumed()
        verify_replica_state(strategy, model, optimizer)
        start = int(epoch.numpy())
        if int(optimizer.iterations.numpy()) != start * STEPS_PER_EPOCH:
            raise RuntimeError("Checkpoint optimizer progress does not match the training epoch")
        if state_path.is_file():
            previous = json.loads(state_path.read_text(encoding="utf-8"))
            if previous.get("epoch") == start and previous.get("weights_sha256") != weights_digest(model):
                raise RuntimeError("Restored weights differ from the saved model")
            if previous.get("epoch") == start and previous.get("optimizer_sha256") not in (None, variables_digest(optimizer.variables)):
                raise RuntimeError("Restored optimizer differs from the saved state")
        if int(saved_replicas.numpy()) != replicas:
            print("GPU count changed; the numerical training trajectory may differ.", flush=True)
        saved_replicas.assign(replicas)
        restored = True
        print(f"Restored epoch {start}; target total epochs={args.epochs}", flush=True)

    @tf.function
    def train_step(batch):
        def per_replica(inputs):
            features, target = inputs
            with tf.GradientTape() as tape:
                prediction = model(features, training=True)
                # Fixed batch: host-only assertion constants stay out of GPU replicas.
                loss = tf.reduce_sum(tf.square(prediction - target)) / float(BATCH_SIZE * replicas)
            gradients = tape.gradient(loss, model.trainable_variables)
            for gradient in gradients:
                tf.debugging.assert_all_finite(gradient, "Invalid training gradient")
            optimizer.apply_gradients(zip(gradients, model.trainable_variables))
            return loss
        values = strategy.run(per_replica, args=(batch,))
        return strategy.reduce(tf.distribute.ReduceOp.SUM, values, axis=None)

    for current_epoch in range(int(epoch.numpy()), args.epochs):
        before = weights_digest(model)
        losses = []
        for batch_index in range(STEPS_PER_EPOCH):
            def make_batch(context):
                seed = 42 + (current_epoch * STEPS_PER_EPOCH + batch_index) * replicas
                generator = np.random.default_rng(seed + context.replica_id_in_sync_group)
                features = generator.standard_normal((BATCH_SIZE, 4), dtype=np.float32)
                target = np.sum(features * np.array([1, 2, -1, 0.5], np.float32), axis=1, keepdims=True)
                with tf.device("/CPU:0"):
                    return tf.constant(features), tf.constant(target)
            batch = strategy.experimental_distribute_values_from_function(make_batch)
            losses.append(float(train_step(batch).numpy()))
        if not np.isfinite(losses).all() or before == weights_digest(model):
            raise RuntimeError("Training did not produce finite updates")
        verify_replica_state(strategy, model, optimizer)
        epoch.assign(current_epoch + 1)
        state = {
            "communication": "ring-workers" if worker is not None else "nccl" if args.gpus > 1 else "single-device",
            "epoch": int(epoch.numpy()), "replicas": replicas, "device": args.device,
            "optimizer_iterations": int(optimizer.iterations.numpy()),
            "weights_sha256": weights_digest(model), "restored": restored,
            "optimizer_sha256": variables_digest(optimizer.variables),
            "mean_loss": float(np.mean(losses)),
        }
        try:
            manager.save(checkpoint_number=int(epoch.numpy()))
            if chief:
                save_metadata(state_path, state)
        except (OSError, tf.errors.OpError) as error:
            raise RuntimeError(
                "Checkpoint save failed; check persistent storage capacity and permissions."
            ) from error
        if chief:
            print(json.dumps(state), flush=True)
            print(f"Saved epoch {epoch.numpy()} to {args.checkpoint}", flush=True)
    if worker is not None:
        # This also handles resuming a checkpoint already at the target epoch.
        save_metadata(Path(os.environ["CPCLOUD_TF_WORKER_STATE"]) / f"worker-{worker}.json", {
            "epoch": int(epoch.numpy()), "optimizer_iterations": int(optimizer.iterations.numpy()),
            "weights_sha256": weights_digest(model),
            "optimizer_sha256": variables_digest(optimizer.variables),
        })


if __name__ == "__main__":
    main()
