import time
import os
import ast
import importlib_metadata
from contextlib import contextmanager

import multiprocessing


def read_file(path):
    with open(path) as f:
        return f.read()


def get_top_module(full_module_name):
    return full_module_name.split(".")[0]


class ImportVisitor(ast.NodeVisitor):
    def __init__(self):
        super().__init__()
        self.modules = set()

    def visit_Import(self, node: ast.Import):
        for name in node.names:
            self.modules.add(get_top_module(name.name))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level == 0:
            self.modules.add(get_top_module(node.module))


def parse_imported_modules(path):
    src = read_file(path)
    visitor = ImportVisitor()
    visitor.visit(ast.parse(src))
    return visitor.modules


def iter_python_scripts(directory):
    for root, _, files in os.walk(directory):

        for f in files:
            if not f.endswith(".py"):
                continue

            yield os.path.join(root, f)


_PACKAGES_DISTRIBUTIONS = importlib_metadata.packages_distributions()


def get_true_dependencies_multiprocessing(module):
    module_dir = os.path.dirname(module.__file__)
    with multiprocessing.Pool(multiprocessing.cpu_count()) as pool:
        res = pool.map(parse_imported_modules, iter_python_scripts(module_dir))
        return set().union(*res).intersection(set(_PACKAGES_DISTRIBUTIONS.keys()))


def get_true_dependencies(module):
    module_dir = os.path.dirname(module.__file__)
    res = set()
    for python_script in iter_python_scripts(module_dir):
        res.update(parse_imported_modules(python_script))
    return res.intersection(set(_PACKAGES_DISTRIBUTIONS.keys()))


@contextmanager
def timer():
    start = time.time()
    yield
    print(f"Took {time.time() - start} sec.")


def benchmark(module):
    print(f"\n===== {module.__name__} ======")
    with timer():
        a = get_true_dependencies(module)
        print(a)

    with timer():
        b = get_true_dependencies_multiprocessing(module)
        print(b)

    assert a == b


import sklearn
import xgboost
import pandas
import lightgbm
import torch

benchmark(sklearn)
benchmark(xgboost)
benchmark(pandas)
benchmark(lightgbm)
benchmark(torch)
