$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$html = Get-Content -Raw -Encoding UTF8 (Join-Path $projectRoot "index.html")
$css = Get-Content -Raw -Encoding UTF8 (Join-Path $projectRoot "styles.css")
$javascript = Get-Content -Raw -Encoding UTF8 (Join-Path $projectRoot "app.js")
$data = Get-Content -Raw -Encoding UTF8 (Join-Path $projectRoot "data\stocks.json")

$html = $html.Replace('<link rel="stylesheet" href="styles.css">', "<style>`n$css`n</style>")
$inlineScripts = "<script>window.__STOCK_DATA__ = $data;</script>`n<script>`n$javascript`n</script>"
$html = $html.Replace('<script src="app.js" defer></script>', $inlineScripts)

$output = Join-Path $projectRoot "outputs\valuation-board-single.html"
[System.IO.File]::WriteAllText($output, $html, [System.Text.UTF8Encoding]::new($false))
Write-Output $output
