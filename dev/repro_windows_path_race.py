"""
Probe for the spurious "resolved path is outside the artifact directory" rejection seen on the
Windows CI runners (tests/tracking/test_log_image.py::test_async_log_image_flush dropped 1 of 200
artifact writes).

The suspected mechanism is that pathlib.Path.resolve() queries the filesystem and, in its default
non-strict mode, silently returns a partially resolved path when a query fails instead of raising:
ntpath._getfinalpathname_nonstrict swallows a list of winerrors that includes transient ones such
as ERROR_SHARING_VIOLATION. Two calls can then disagree about a shared path prefix, and that
disagreement is exactly what the artifact path check compares. On the CI runners the temp
directory is handed out in 8.3 short-name form (C:\\Users\\RUNNER~1\\...), so a partially resolved
path is directly observable: the short name survives instead of expanding to "runneradmin".

This runs the workload that would trigger it. Writer threads copy what LocalArtifactRepository
does for every artifact (tempfile.mkstemp() in the destination directory, write, os.replace onto
the final name), while prober threads resolve paths in that same directory. It measures:

  1. how often resolve() raises, bucketed by winerror,
  2. how often two resolve() calls on the same input disagree, or come back partially resolved
     (an unexpanded 8.3 short name, or a retained \\\\?\\ extended-length prefix), and
  3. how often validate_path_within_directory() rejects a path that is genuinely inside the base
     directory.

Every path built here is inside the base directory, so any rejection is by definition spurious.
"""

import argparse
import os
import pathlib
import shutil
import sys
import tempfile
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from mlflow.exceptions import MlflowException
from mlflow.utils.uri import validate_path_within_directory

_PAYLOAD = os.urandom(4096)
_MAX_SAMPLES = 5


def _write_artifact(images_dir: str, index: int) -> None:
    destination = os.path.join(images_dir, f"dog+step+{index}+timestamp+{index}+{uuid.uuid4()}.png")
    file_descriptor, temp_path = tempfile.mkstemp(dir=images_dir, prefix=".mlflow-tmp")
    try:
        with os.fdopen(file_descriptor, "wb") as temp_file:
            temp_file.write(_PAYLOAD)
        os.replace(temp_path, destination)
    except BaseException:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        raise


def _writer(images_dir: str, iterations: int) -> Counter:
    stats = Counter()
    for index in range(iterations):
        try:
            _write_artifact(images_dir, index)
            stats["writes"] += 1
        except OSError as e:
            stats["write_errors"] += 1
            stats[f"write_winerror_{getattr(e, 'winerror', None)}"] += 1
    return stats


def _record(stats: Counter, samples: list[str], key: str, detail: str) -> None:
    stats[key] += 1
    if len(samples) < _MAX_SAMPLES:
        samples.append(f"[{key}] {detail}")


def _prober(base_dir: str, images_dir: str, iterations: int, samples: list[str]) -> Counter:
    stats = Counter()
    for index in range(iterations):
        destination = os.path.join(images_dir, f"probe+{index}+{uuid.uuid4()}.png")
        stats["probes"] += 1

        # Question 1: does resolve() raise while the directory is being written to?
        for label, path in (("base", base_dir), ("dir", images_dir)):
            try:
                first = pathlib.Path(path).resolve()
                second = pathlib.Path(path).resolve()
            except OSError as e:
                _record(
                    stats,
                    samples,
                    f"resolve_error_{label}",
                    f"winerror={getattr(e, 'winerror', None)} errno={e.errno} path={path}",
                )
                continue
            # Question 2: is resolve() stable, and does it fully resolve? The runner hands out
            # the temp directory in 8.3 form, so a surviving "~" means resolution stopped early,
            # and a leading \\?\ means the extended-length prefix was not stripped.
            if str(first) != str(second):
                _record(stats, samples, f"unstable_resolve_{label}", f"{first} != {second}")
            if "~" in str(first):
                _record(stats, samples, f"short_name_kept_{label}", f"{path} -> {first}")
            if str(first).startswith("\\\\?\\"):
                _record(stats, samples, f"extended_prefix_kept_{label}", f"{path} -> {first}")

        # Question 3: does the path check reject a path that is inside the base directory?
        try:
            validate_path_within_directory(base_dir, destination)
        except MlflowException as e:
            _record(stats, samples, "rejected", str(e))
        except OSError as e:
            _record(stats, samples, "oserror", f"{type(e).__name__}: {e}")
    return stats


def _run_round(writers: int, probers: int, iterations: int, samples: list[str]) -> Counter:
    root = tempfile.mkdtemp()
    try:
        # Mirror the layout the failing test uses: <root>/artifacts/0/<run_id>/artifacts/images
        base_dir = os.path.join(root, "artifacts", "0", uuid.uuid4().hex, "artifacts")
        images_dir = os.path.join(base_dir, "images")
        os.makedirs(images_dir)

        stats = Counter()
        with ThreadPoolExecutor(max_workers=writers + probers) as pool:
            futures = [pool.submit(_writer, images_dir, iterations) for _ in range(writers)]
            futures += [
                pool.submit(_prober, base_dir, images_dir, iterations, samples)
                for _ in range(probers)
            ]
            for future in futures:
                stats.update(future.result())
        return stats
    finally:
        shutil.rmtree(root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=200)
    # The async artifact logging queue writes through a 5 worker thread pool.
    parser.add_argument("--writers", type=int, default=5)
    parser.add_argument("--probers", type=int, default=5)
    args = parser.parse_args()

    print(f"python:   {sys.version}")
    print(f"platform: {sys.platform}")
    print(f"tempdir:  {tempfile.gettempdir()}")
    print(f"config:   {vars(args)}")

    samples: list[str] = []
    totals = Counter()
    for round_index in range(args.rounds):
        stats = _run_round(args.writers, args.probers, args.iterations, samples)
        totals.update(stats)
        print(f"round {round_index + 1}/{args.rounds}: {dict(stats)}", flush=True)

    print("\n=== totals ===")
    for key, value in sorted(totals.items()):
        print(f"{key}: {value}")

    if samples:
        print("\n=== samples ===")
        for sample in samples:
            print(sample)

    reproduced = totals["rejected"]
    print(f"\nspurious rejections: {reproduced}")
    print("REPRODUCED" if reproduced else "NOT REPRODUCED")

    # Reproducing is the goal here, so a rejection is reported without failing the job.
    return 0


if __name__ == "__main__":
    sys.exit(main())
