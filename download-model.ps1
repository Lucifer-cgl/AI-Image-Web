param([switch]$Force)
$ErrorActionPreference = 'Stop'
$modelsRoot = Join-Path $PSScriptRoot 'models'
New-Item -ItemType Directory -Force -Path $modelsRoot | Out-Null

function Install-ModelArchive {
    param([string]$Name, [string]$ExpectedSha, [string]$ReadyFile)
    $readyPath = Join-Path $modelsRoot $ReadyFile
    if ((Test-Path -LiteralPath $readyPath) -and -not $Force) {
        Write-Host "已存在：$readyPath" -ForegroundColor Green
        return
    }
    $partial = Join-Path $PSScriptRoot "$Name.partial"
    $asset = "https://github.com/Lucifer-cgl/AI-Image-Web/releases/download/v0.1.0/$Name"
    $sources = @("https://ghfast.top/$asset", "https://gh-proxy.com/$asset", $asset)
    $downloaded = $false
    foreach ($url in $sources) {
        Write-Host "尝试下载：$url" -ForegroundColor Cyan
        & curl.exe -L --fail --retry 3 --connect-timeout 15 -C - -o $partial $url
        if ($LASTEXITCODE -eq 0) { $downloaded = $true; break }
    }
    if (-not $downloaded) { throw "$Name 的所有下载源均失败" }
    $actualSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $partial).Hash.ToLowerInvariant()
    if ($actualSha -ne $ExpectedSha) { throw "$Name 的 SHA-256 不一致：$actualSha" }
    Expand-Archive -LiteralPath $partial -DestinationPath $modelsRoot -Force
    if (-not (Test-Path -LiteralPath $readyPath)) { throw "$Name 解压后的结构不正确" }
    Remove-Item -LiteralPath $partial -Force
    Write-Host "安装完成：$readyPath" -ForegroundColor Green
}

Install-ModelArchive -Name 'dreamshaper-8-fp16.zip' -ExpectedSha '98d1b2da2408ce549dfc05eca9ad02347313ab34b656e28835a7fcb67308ee35' -ReadyFile 'dreamshaper-8-fp16\model_index.json'
Install-ModelArchive -Name 'opus-mt-zh-en.zip' -ExpectedSha '63c6c1b52e6b9497522bf3680b9559a81d1bde3f941f10649b82edc0ea2dee62' -ReadyFile 'opus-mt-zh-en\config.json'

