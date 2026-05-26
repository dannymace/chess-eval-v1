[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ChessEvalArgs
)

$ErrorActionPreference = 'Stop'

if ($ChessEvalArgs.Count -eq 0) {
    throw 'Usage: .\run.ps1 <chess.com-username> [options]'
}

$repoRoot = Split-Path -Parent $PSCommandPath
$reports = Join-Path $repoRoot 'reports'
New-Item -ItemType Directory -Force -Path $reports | Out-Null
$reportsPath = (Resolve-Path $reports).ProviderPath

$image = if ($env:CHESS_EVAL_IMAGE) { $env:CHESS_EVAL_IMAGE } else { 'chess-eval-v1:1.0.2' }
$container = "chess-eval-v1-$([Guid]::NewGuid().ToString('N'))"
$containerArgs = @($ChessEvalArgs)
$hasHtml = $false
foreach ($arg in $containerArgs) {
    if ($arg -eq '--html' -or $arg.StartsWith('--html=')) {
        $hasHtml = $true
        break
    }
}
if (-not $hasHtml) {
    $containerArgs += @('--html', '/reports/')
}
$exitCode = 0

try {
    docker create --name $container $image @containerArgs | Out-Null
    docker start -a $container
    $exitCode = $LASTEXITCODE

    docker cp "${container}:/reports/." $reportsPath | Out-Null
    Write-Host "HTML reports copied to $reportsPath"
}
finally {
    docker rm -f -v $container 2>$null | Out-Null
}

exit $exitCode
