#!/usr/bin/env bash
set -euo pipefail

COMFY_DIR="/opt/ComfyUI"
USER_DIR="${COMFY_DIR}/user"
CUSTOM_NODES_DIR="${COMFY_DIR}/custom_nodes"

mkdir -p "${USER_DIR}"

AUTO_PIP_INSTALL_CUSTOM_NODE_DEPS="${AUTO_PIP_INSTALL_CUSTOM_NODE_DEPS:-1}"
PIP_CACHE_DIR="${PIP_CACHE_DIR:-${USER_DIR}/pip_cache}"
export PIP_CACHE_DIR

CONSTRAINTS_FILE="${USER_DIR}/pip-constraints.txt"

cat > "${CONSTRAINTS_FILE}" << 'EOF'
numpy<2
opencv-python-headless<4.12
EOF

cd "${COMFY_DIR}"

calc_deps_hash() {
  {
    cat "$0" 2>/dev/null || true
    find "${CUSTOM_NODES_DIR}" -maxdepth 3 -type f -name 'requirements.txt' -print0 2>/dev/null | sort -z | xargs -0 -r cat
    find "${CUSTOM_NODES_DIR}" -maxdepth 3 -type f -name 'pyproject.toml' -print0 2>/dev/null | sort -z | xargs -0 -r cat
  } | sha256sum | awk '{print $1}'
}

install_requirements_files() {
  local req
  while IFS= read -r -d '' req; do
    local tmp_req
    tmp_req="${USER_DIR}/.tmp_requirements.$(basename "$(dirname "$req")").txt"

    python - << 'PY' "$req" "$tmp_req"
import sys

src = sys.argv[1]
dst = sys.argv[2]

out = []
with open(src, 'r', encoding='utf-8', errors='ignore') as f:
    for raw in f:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue

        low = line.lower()
        # Avoid numpy churn; we pin it via constraints.
        if low.startswith('numpy'):
            continue

        # Avoid CPU onnxruntime overwriting onnxruntime-gpu.
        if low.startswith('onnxruntime') and 'gpu' not in low:
            continue

        # Prefer headless OpenCV to avoid pulling GUI deps and numpy>=2 wheels.
        if low.startswith('opencv-python'):
            out.append('opencv-python-headless<4.12')
            continue

        out.append(line)

with open(dst, 'w', encoding='utf-8') as f:
    for l in out:
        f.write(l + '\n')
PY

    echo "[entrypoint] pip install -r ${req} (sanitized)"
    python -m pip install --prefer-binary -c "${CONSTRAINTS_FILE}" -r "${tmp_req}" || true
  done < <(find "${CUSTOM_NODES_DIR}" -maxdepth 3 -type f -name 'requirements.txt' -print0 2>/dev/null)
}

install_pyproject_deps() {
  python - << 'PY'
import os
import sys
from pathlib import Path

try:
    import tomllib  # py311+
except Exception:
    tomllib = None

custom_nodes = Path('/opt/ComfyUI/custom_nodes')
if not custom_nodes.exists() or tomllib is None:
    sys.exit(0)

deps = []
for p in custom_nodes.rglob('pyproject.toml'):
    try:
        data = tomllib.loads(p.read_text(encoding='utf-8'))
        d = data.get('project', {}).get('dependencies', [])
        if isinstance(d, list):
            deps.extend(d)
    except Exception:
        continue

# de-dupe while preserving order
seen = set()
out = []
for d in deps:
    if not isinstance(d, str):
        continue
    if d in seen:
        continue
    seen.add(d)
    out.append(d)

for d in out:
    print(d)
PY
}

install_pyproject_deps_to_file() {
  local dst="$1"
  python - << 'PY' "$dst"
import sys
from pathlib import Path

try:
    import tomllib
except Exception:
    tomllib = None

dst = Path(sys.argv[1])
custom_nodes = Path('/opt/ComfyUI/custom_nodes')
dst.parent.mkdir(parents=True, exist_ok=True)

if not custom_nodes.exists() or tomllib is None:
    dst.write_text('', encoding='utf-8')
    sys.exit(0)

deps = []
for p in custom_nodes.rglob('pyproject.toml'):
    try:
        data = tomllib.loads(p.read_text(encoding='utf-8'))
        d = data.get('project', {}).get('dependencies', [])
        if isinstance(d, list):
            deps.extend([x for x in d if isinstance(x, str)])
    except Exception:
        continue

seen = set()
out = []
for d in deps:
    if d in seen:
        continue
    seen.add(d)
    out.append(d)

sanitized = []
for d in out:
    low = d.strip().lower()
    if not low:
        continue
    if low.startswith('numpy'):
        continue
    if low.startswith('onnxruntime') and 'gpu' not in low:
        continue
    if low.startswith('opencv-python'):
        sanitized.append('opencv-python-headless<4.12')
        continue
    sanitized.append(d.strip())

dst.write_text('\n'.join(sanitized) + ('\n' if sanitized else ''), encoding='utf-8')
PY
}

if [ "${AUTO_PIP_INSTALL_CUSTOM_NODE_DEPS}" = "1" ] && [ -d "${CUSTOM_NODES_DIR}" ]; then
  NEW_HASH="$(calc_deps_hash || true)"
  HASH_FILE="${USER_DIR}/.custom_node_deps_hash"
  OLD_HASH=""
  if [ -f "${HASH_FILE}" ]; then
    OLD_HASH="$(cat "${HASH_FILE}" 2>/dev/null || true)"
  fi

  if [ -n "${NEW_HASH}" ] && [ "${NEW_HASH}" != "${OLD_HASH}" ]; then
    echo "[entrypoint] Custom node deps changed -> installing python deps (best-effort)"
    python -m pip install --upgrade pip setuptools wheel || true

    install_requirements_files

    PYPROJECT_REQS_FILE="${USER_DIR}/.tmp_pyproject_deps.txt"
    install_pyproject_deps_to_file "${PYPROJECT_REQS_FILE}" || true
    if [ -s "${PYPROJECT_REQS_FILE}" ]; then
      echo "[entrypoint] pip install pyproject.toml deps (requirements file)"
      python -m pip install --prefer-binary -c "${CONSTRAINTS_FILE}" -r "${PYPROJECT_REQS_FILE}" || true
    fi

    # Enforce our desired stack after custom node installs.
    python -m pip install --prefer-binary --upgrade --force-reinstall -c "${CONSTRAINTS_FILE}" "numpy<2" "opencv-python-headless<4.12" || true
    python -m pip uninstall -y opencv-python || true
    python -m pip uninstall -y onnxruntime || true
    python -m pip install --prefer-binary --force-reinstall onnxruntime-gpu || python -m pip install --prefer-binary onnxruntime || true

    echo "${NEW_HASH}" > "${HASH_FILE}" || true
  else
    echo "[entrypoint] Custom node deps unchanged -> skipping pip install"
  fi
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

exec python main.py --listen 0.0.0.0 --port 8188
