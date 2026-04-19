# update.ps1 - Telecharge la derniere version du bot depuis GitHub
# Usage: powershell -ExecutionPolicy Bypass -File update.ps1

$branch = "claude/hyperliquid-trading-bot-qE4UW"
$repo = "recomrich/moa-website"
$base = "https://raw.githubusercontent.com/$repo/$branch/hyperliquid-bot"
$dest = "C:\Users\rsser\hyperliquid-bot"

$files = @(
    "main.py",
    "config.yaml",
    "core/__init__.py",
    "core/client.py",
    "core/order_manager.py",
    "core/position_manager.py",
    "core/risk_manager.py",
    "core/portfolio.py",
    "data/__init__.py",
    "data/feed.py",
    "data/cache.py",
    "data/historical.py",
    "database/__init__.py",
    "database/models.py",
    "database/repository.py",
    "dashboard/server.py",
    "dashboard/websocket_manager.py",
    "indicators/__init__.py",
    "indicators/trend.py",
    "indicators/momentum.py",
    "indicators/volatility.py",
    "indicators/volume.py",
    "strategies/__init__.py",
    "strategies/base_strategy.py",
    "strategies/strategy_manager.py",
    "strategies/trend_following.py",
    "strategies/mean_reversion.py",
    "strategies/breakout.py",
    "strategies/momentum.py",
    "strategies/cycle_trader.py",
    "strategies/scalping.py",
    "strategies/grid_trading.py",
    "strategies/swing_range.py",
    "strategies/regime_detector.py",
    "notifications/__init__.py",
    "notifications/telegram.py",
    "backtesting/__init__.py",
    "backtesting/engine.py",
    "backtesting/report.py"
)

Write-Host ""
Write-Host "=== Mise a jour du bot Hyperliquid ===" -ForegroundColor Cyan
Write-Host "Branche: $branch" -ForegroundColor Gray
Write-Host ""

$ok = 0
$fail = 0

foreach ($file in $files) {
    $url = "$base/$file"
    $output = Join-Path $dest ($file -replace '/', '\')
    $dir = Split-Path $output
    if (!(Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    try {
        Invoke-WebRequest -Uri $url -OutFile $output -ErrorAction Stop
        Write-Host "  OK: $file" -ForegroundColor Green
        $ok++
    } catch {
        Write-Host "  SKIP: $file" -ForegroundColor Yellow
        $fail++
    }
}

Write-Host ""
Write-Host "=== Termine: $ok fichiers mis a jour, $fail ignores ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Arrete le bot (Ctrl+C) puis relance avec:" -ForegroundColor White
Write-Host "  python main.py" -ForegroundColor Green
Write-Host ""
