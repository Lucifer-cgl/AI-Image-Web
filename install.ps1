param([switch]$Force)
$ErrorActionPreference = 'Stop'
$python = (& py -3.11 -c 'import sys; print(sys.executable)' | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) {
    throw '未找到 Python 3.11。请先安装 64 位 Python 3.11，并勾选 py launcher。'
}
if ($Force) {
    & $python -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu128
} else {
    & $python -c 'import torch; assert torch.cuda.is_available()' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '正在安装 CUDA 版 PyTorch（文件较大）…' -ForegroundColor Cyan
        & $python -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cu128
    }
}
& $python -m pip install --upgrade -r (Join-Path $PSScriptRoot 'requirements.txt')
& $python -c 'import torch,diffusers,transformers,PIL; print("CUDA:",torch.cuda.is_available(),torch.cuda.get_device_name(0) if torch.cuda.is_available() else "不可用"); print("diffusers:",diffusers.__version__)'
if ($LASTEXITCODE -ne 0) { throw '依赖检查失败' }
Write-Host '安装完成。' -ForegroundColor Green

