param(
    [string]$ModelPath = '',
    [string]$TranslatorPath = '',
    [int]$Port = 8091
)
$ErrorActionPreference = 'Stop'
if (-not $ModelPath) {
    $bundled = Join-Path $PSScriptRoot 'models\dreamshaper-8-fp16'
    $shared = 'E:\AI-Models\image\dreamshaper-8-fp16'
    $ModelPath = if (Test-Path -LiteralPath (Join-Path $bundled 'model_index.json')) { $bundled } elseif (Test-Path -LiteralPath (Join-Path $shared 'model_index.json')) { $shared } else { $bundled }
}
if (-not $TranslatorPath) {
    $bundledTranslator = Join-Path $PSScriptRoot 'models\opus-mt-zh-en'
    $sharedTranslator = 'E:\AI-Models\translation\opus-mt-zh-en'
    $TranslatorPath = if (Test-Path -LiteralPath (Join-Path $bundledTranslator 'config.json')) { $bundledTranslator } elseif (Test-Path -LiteralPath (Join-Path $sharedTranslator 'config.json')) { $sharedTranslator } else { '' }
}
if (-not (Test-Path -LiteralPath (Join-Path $ModelPath 'model_index.json'))) {
    throw "未找到 DreamShaper 模型：$ModelPath。请先运行 download-model.ps1。"
}
$python = (& py -3.11 -c 'import sys; print(sys.executable)' | Select-Object -Last 1)
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $python)) { throw '未找到 Python 3.11' }
$argsList = @((Join-Path $PSScriptRoot 'app\server.py'),'--model',$ModelPath,'--port',"$Port",'--history',(Join-Path $PSScriptRoot 'data\history'),'--open-browser')
if ($TranslatorPath) { $argsList += @('--translator',$TranslatorPath) }
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$Host.UI.RawUI.WindowTitle = "AI Image Web - $Port"
Write-Host "网页：http://127.0.0.1:$Port/" -ForegroundColor Green
Write-Host "模型：$ModelPath"
Write-Host '保持此窗口打开；Ctrl+C 停止服务。'
& $python @argsList

