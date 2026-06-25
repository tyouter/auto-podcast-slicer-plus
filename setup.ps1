# garden_core one-click setup (Windows)
Write-Host "============================================"
Write-Host " garden_core setup"
Write-Host "============================================"

$hasConda = Get-Command conda -ErrorAction SilentlyContinue
$hasFfmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue

if (-not $hasFfmpeg) {
    Write-Host "Warning: ffmpeg not found. Install from https://ffmpeg.org/download.html"
}

if ($hasConda) {
    Write-Host ""
    Write-Host "[conda] Creating garden environment..."
    conda env create -f environment.yml
    Write-Host ""
    Write-Host "Done. Activate with: conda activate garden"
} else {
    Write-Host ""
    Write-Host "[pip] Installing garden_core with GPU support..."
    pip install -e '.[gpu]'
    Write-Host ""
    Write-Host "Done. garden_core is now importable."
}

Write-Host ""
Write-Host "Verify: python -c 'from garden_core.stage_asr import FunASRLocal; print(\"OK\")'"
