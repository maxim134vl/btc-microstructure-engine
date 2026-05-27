#!/bin/sh
# =====================================================================
# Bridges /app (source, baked into image) with /data (persistent
# named volume). Existing scripts use bare filenames for parquet I/O
# and `os.system("python3 X.py")` for sibling scripts — both rely on
# cwd containing the .py file and being writable. We symlink code
# into /data on each container start so:
#   - parquet writes land in the persisted /data volume
#   - sibling-script invocations resolve via the symlinks
#   - rebuilding the image always picks up new code (symlinks point
#     to /app, which is replaced on rebuild)
# =====================================================================

set -e

DATA_DIR="${DATA_DIR:-/data}"
CODE_DIR="${CODE_DIR:-/app}"

mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

# ---------------------------------------------------------------------
# top-level .py files and registry yaml
# ---------------------------------------------------------------------
for f in "$CODE_DIR"/*.py "$CODE_DIR"/*.yaml; do
    [ -e "$f" ] || continue
    name=$(basename "$f")
    target="$DATA_DIR/$name"
    # only create the symlink if there isn't already a real file there
    if [ ! -e "$target" ] || [ -L "$target" ]; then
        ln -sfn "$f" "$target"
    fi
done

# ---------------------------------------------------------------------
# subdirectories — symlink whole directories (read-only source trees)
# ---------------------------------------------------------------------
for d in engines collectors runtime models tools research; do
    src="$CODE_DIR/$d"
    dst="$DATA_DIR/$d"
    [ -d "$src" ] || continue
    if [ ! -e "$dst" ] || [ -L "$dst" ]; then
        ln -sfn "$src" "$dst"
    fi
done

# ---------------------------------------------------------------------
# autonomous_runtime_v2.py hardcodes PYTHON = "venv/bin/python3".
# Provide a shim so the orchestrator works without code changes.
# ---------------------------------------------------------------------
if [ ! -e "$DATA_DIR/venv/bin/python3" ]; then
    mkdir -p "$DATA_DIR/venv/bin"
    ln -sfn "$(command -v python3)" "$DATA_DIR/venv/bin/python3"
fi

exec "$@"
