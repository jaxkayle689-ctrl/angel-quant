from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import zipfile
from pathlib import Path
from urllib.request import getproxies


ROOT = Path(__file__).resolve().parent
APP_SUPPORT = Path.home() / "Library/Application Support/Binance Quant"
FREQTRADE = APP_SUPPORT / "freqtrade-runtime/bin/freqtrade"
USERDIR = APP_SUPPORT / "freqtrade"
CONFIG = ROOT / "martingale_config.json"
STRATEGY_PATH = ROOT / "strategies"
RESULT_DIR = ROOT / "martingale_results/portfolio5"
SUMMARY_CSV = RESULT_DIR / "summary.csv"
INITIAL_CAPITAL = 5000.0
PAIRS = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "BNB/USDT:USDT",
    "XRP/USDT:USDT",
]
STRATEGIES = [
    "Strategy1Trend20Fixed",
    "Strategy1MartingaleOneAdd",
    "Strategy1Martingale20",
]


def subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for proxy_name, variable in (
        ("http", "HTTP_PROXY"),
        ("https", "HTTPS_PROXY"),
        ("all", "ALL_PROXY"),
        ("no", "NO_PROXY"),
    ):
        if environment.get(variable) or environment.get(variable.lower()):
            continue
        value = getproxies().get(proxy_name)
        if value:
            environment[variable] = value
            environment[variable.lower()] = value
    return environment


def latest_result() -> Path:
    candidates = list(RESULT_DIR.glob("*.zip"))
    if not candidates:
        raise RuntimeError(f"No backtest result in {RESULT_DIR}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_payload(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        result_name = next(
            name
            for name in archive.namelist()
            if name.endswith(".json")
            and not name.endswith(("_config.json", "_meta.json", ".meta.json"))
        )
        return json.loads(archive.read(result_name).decode("utf-8"))


def summarize(payload: dict, result_file: Path) -> list[dict]:
    rows = []
    for strategy_name in STRATEGIES:
        strategy = payload["strategy"][strategy_name]
        trades = strategy["trades"]
        wins = [trade for trade in trades if float(trade["profit_abs"]) > 0]
        losses = [trade for trade in trades if float(trade["profit_abs"]) < 0]
        gross_win = sum(float(trade["profit_abs"]) for trade in wins)
        gross_loss = -sum(float(trade["profit_abs"]) for trade in losses)
        fees = sum(
            float(trade["fee_open"]) * float(trade["amount"]) * float(trade["open_rate"])
            + float(trade["fee_close"]) * float(trade["amount"]) * float(trade["close_rate"])
            for trade in trades
        )
        avg_win = gross_win / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0
        longs = [trade for trade in trades if not trade["is_short"]]
        shorts = [trade for trade in trades if trade["is_short"]]
        rows.append(
            {
                "strategy": strategy_name,
                "profit_pct": float(strategy["profit_total"]) * 100,
                "profit_abs": float(strategy["profit_total_abs"]),
                "max_drawdown_pct": float(strategy["max_drawdown_account"]) * 100,
                "trades": len(trades),
                "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0.0,
                "profit_factor": gross_win / gross_loss if gross_loss else 0.0,
                "payoff_ratio": avg_win / avg_loss if avg_loss else 0.0,
                "fees_abs_est": fees,
                "long_trades": len(longs),
                "long_profit_abs": sum(float(trade["profit_abs"]) for trade in longs),
                "short_trades": len(shorts),
                "short_profit_abs": sum(float(trade["profit_abs"]) for trade in shorts),
                "result_file": str(result_file),
            }
        )
    return rows


def write_summary(rows: list[dict]) -> None:
    with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_backtest(timerange: str) -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    command = [
        str(FREQTRADE),
        "backtesting",
        "--config",
        str(CONFIG),
        "--userdir",
        str(USERDIR),
        "--strategy-path",
        str(STRATEGY_PATH),
        "--recursive-strategy-search",
        "--strategy-list",
        *STRATEGIES,
        "--timeframe",
        "1m",
        "--timerange",
        timerange,
        "--dry-run-wallet",
        str(INITIAL_CAPITAL),
        "--export",
        "trades",
        "--backtest-directory",
        str(RESULT_DIR),
        "--cache",
        "none",
        "--pairs",
        *PAIRS,
    ]
    subprocess.run(command, cwd=ROOT, env=subprocess_environment(), check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the five-pair Strategy1 martingale ablation.")
    parser.add_argument("--timerange", default="20260713-20260812")
    parser.add_argument("--summarize-only", action="store_true")
    arguments = parser.parse_args()
    if not arguments.summarize_only:
        run_backtest(arguments.timerange)
    result_file = latest_result()
    write_summary(summarize(load_payload(result_file), result_file))
    print(f"Wrote {SUMMARY_CSV}")


if __name__ == "__main__":
    main()
