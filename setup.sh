#!/usr/bin/env bash
# garden_core one-click setup (Linux / macOS)
set -e

echo "============================================"
echo " garden_core setup"
echo "============================================"

# Check prerequisites
command -v python3 >/dev/null 2>&1 || { echo "Error: python3 not found"; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "Warning: ffmpeg not found. Install it: brew install ffmpeg / apt install ffmpeg"; }

# Choose setup method
if command -v conda >/dev/null 2>&1; then
    echo ""
    echo "[conda] Creating garden environment..."
    conda env create -f environment.yml
    echo ""
    echo "Done. Activate with: conda activate garden"
else
    echo ""
    echo "[pip] Installing garden_core with GPU support..."
    pip install -e '.[gpu]'
    echo ""
    echo "Done. garden_core is now importable."
fi

echo ""
echo "Verify: python -c 'from garden_core.stage_asr import FunASRLocal; print(\"OK\")'"
