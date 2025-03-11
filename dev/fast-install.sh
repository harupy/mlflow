#!/usr/bin/env bash
TMPDIR=$(mktemp -d)
git clone --filter=blob:none --no-checkout https://github.com/mlflow/mlflow.git $TMPDIR
cd $TMPDIR
git sparse-checkout set --no-cone /mlflow /skinny /pyproject.toml
git fetch origin pull/$1/merge
git checkout FETCH_HEAD
if pip freeze | grep -q "mlflow.*dev"; then
  pip install --no-build-isolation --no-deps --force-reinstall ./skinny
else
  pip install --no-build-isolation ./skinny
fi
