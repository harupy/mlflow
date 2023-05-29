import tempfile
import contextlib
import pathlib
import hashlib
import os
import cProfile
import pstats
import io
import pstats
import textwrap
import psutil
import time
import uuid
import json

import mlflow


def print_header(name):
    print()
    print("*" * 50)
    print("*", name)
    print("*" * 50)
    print()


def show_machine_specs():
    print_header("MACHINE SPECS")
    print("Number of CPUs")
    print("Physical  :", psutil.cpu_count(logical=False))
    print("Total     :", psutil.cpu_count(logical=True))
    print("\n# Memory Information")
    svmem = psutil.virtual_memory()
    print(f"Total     : {svmem.total // (1024**3)} GB")
    print(f"Available : {svmem.available // (1024**3)} GB")
    print(f"Used      : {svmem.used // (1024**3)} GB")
    print(f"Percentage: {svmem.percent} %")


def md5_checksum(path):
    with open(path, "rb") as f:
        file_hash = hashlib.md5()
        while chunk := f.read(8192):
            file_hash.update(chunk)
    return file_hash.hexdigest()


@contextlib.contextmanager
def profile_and_print_stats(name, n=15):
    print_header(name)
    with cProfile.Profile() as pr:
        yield
        s = io.StringIO()
        sortby = pstats.SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats(n)
        print(textwrap.dedent(s.getvalue()).strip())


@contextlib.contextmanager
def timer() -> float:
    start = time.perf_counter()
    yield lambda: time.perf_counter() - start


def main():
    print(mlflow.__version__)

    KiB = 1000
    MiB = KiB * KiB
    GiB = MiB * KiB

    max_workers = [1, 2, 4, 8, 16, 32]
    chunk_sizes = [10 * MiB, 25 * MiB, 50 * MiB, 100 * MiB]
    download_times = [[0 for _ in max_workers] for _ in chunk_sizes]

    show_machine_specs()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = pathlib.Path(tmpdir)
        f = tmpdir.joinpath("large_file")
        file_size = 1 * GiB
        f.write_bytes(os.urandom(file_size))

        # Upload
        print("Uploading a file")
        with mlflow.start_run():
            mlflow.log_artifact(f)
            uri = mlflow.get_artifact_uri(f.name)

        for i, chunk_size in enumerate(chunk_sizes):
            for j, max_worker in enumerate(max_workers):
                print("Processing", i, j)
                dst_dir = tmpdir.joinpath(uuid.uuid4().hex)
                os.environ.update(
                    {
                        "MLFLOW_DOWNLOAD_CHUNK_SIZE": str(chunk_size),
                        "MLFLOW_MAX_WORKERS": str(max_worker),
                    }
                )

                # Download
                with timer() as t:
                    dst_path = mlflow.artifacts.download_artifacts(
                        artifact_uri=uri, dst_path=dst_dir
                    )
                    download_times[i][j] = t()

                # Verify that the file contents hasn't changed
                dst_path = pathlib.Path(dst_path)
                assert md5_checksum(f) == md5_checksum(dst_path), "File checksums do not match"

    data = {"max_worker": max_workers, "chunk_size": chunk_sizes, "download_time": download_times}
    print(json.dumps(data, indent=2))


if __name__ == "__main__":
    main()
