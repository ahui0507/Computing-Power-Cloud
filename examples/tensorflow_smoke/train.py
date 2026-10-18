"""Two-GPU TensorFlow training with verified checkpoint restoration across processes."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import tensorflow as tf


def weights_digest(model):
    result = hashlib.sha256()
    for variable in model.weights:
        result.update(variable.numpy().tobytes())
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--steps", type=int, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    tf.config.threading.set_intra_op_parallelism_threads(2)
    tf.config.threading.set_inter_op_parallelism_threads(2)
    tf.config.set_soft_device_placement(False)
    devices = tf.config.list_physical_devices("GPU")
    if len(devices) != 2:
        raise RuntimeError(f"Expected two allocated GPUs, found {len(devices)}")
    for device in devices:
        tf.config.experimental.set_memory_growth(device, True)
    strategy = tf.distribute.MirroredStrategy(
        devices=["/GPU:0", "/GPU:1"], cross_device_ops=tf.distribute.NcclAllReduce(),
    )
    with strategy.scope():
        model = tf.keras.Sequential([
            tf.keras.layers.Input((4,)),
            tf.keras.layers.Dense(1, kernel_initializer=tf.keras.initializers.Constant(0.1)),
        ])
        optimizer = tf.keras.optimizers.SGD(0.01)
        optimizer.build(model.trainable_variables)
        step = tf.Variable(0, dtype=tf.int64, trainable=False)
        checkpoint = tf.train.Checkpoint(model=model, optimizer=optimizer, step=step)
        # Create the lazy counter before strict restoration in the next process.
        _ = checkpoint.save_counter
        manager = tf.train.CheckpointManager(checkpoint, str(args.checkpoint), max_to_keep=2)
    state_file = args.checkpoint / "acceptance-state.json"
    restored = False
    if args.resume:
        previous = json.loads(state_file.read_text())
        if not manager.latest_checkpoint:
            raise RuntimeError("Missing checkpoint")
        checkpoint.restore(manager.latest_checkpoint).assert_consumed()
        if weights_digest(model) != previous["weights_sha256"]:
            raise RuntimeError("Restored model weights differ from the saved model")
        if int(step.numpy()) != previous["step"] or int(optimizer.iterations.numpy()) != previous["step"]:
            raise RuntimeError("Training/optimizer progress was not restored")
        restored = True
        print(f"Restored step {step.numpy()}; target {args.steps}", flush=True)

    @tf.function
    def train_step():
        def per_replica():
            x = tf.ones((8, 4))
            with tf.GradientTape() as tape:
                prediction = model(x, training=True)
                # Fixed batch size: avoid host-only assertion constants inside a GPU replica.
                loss = tf.reduce_sum(tf.square(prediction)) / 16.0
            gradients = tape.gradient(loss, model.trainable_variables)
            for gradient in gradients:
                tf.debugging.assert_all_finite(gradient, "Invalid training gradient")
            optimizer.apply_gradients(zip(gradients, model.trainable_variables))
            return loss
        values = strategy.run(per_replica)
        return strategy.reduce(tf.distribute.ReduceOp.SUM, values, axis=None)

    while int(step.numpy()) < args.steps:
        before = weights_digest(model)
        loss = float(train_step().numpy())
        if not np.isfinite(loss) or weights_digest(model) == before:
            raise RuntimeError("Training did not update finite model weights")
        step.assign_add(1)
        for variable in model.weights:
            if not np.isfinite(variable.numpy()).all():
                raise RuntimeError("Invalid model weights")
        manager.save(checkpoint_number=int(step.numpy()))
        state = {
            "step": int(step.numpy()), "replicas": strategy.num_replicas_in_sync,
            "optimizer_iterations": int(optimizer.iterations.numpy()),
            "weights_sha256": weights_digest(model), "restored": restored, "loss": loss,
        }
        state_file.write_text(json.dumps(state, indent=2))
        print(json.dumps(state), flush=True)


if __name__ == "__main__":
    main()
