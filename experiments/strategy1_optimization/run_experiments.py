from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from urllib.request import getproxies


ROOT = Path(__file__).resolve().parent
APP_SUPPORT = Path.home() / "Library/Application Support/Binance Quant"
FREQTRADE = APP_SUPPORT / "freqtrade-runtime/bin/freqtrade"
USERDIR = APP_SUPPORT / "freqtrade"
CONFIG = ROOT / "config.json"
RESULT_DIR = ROOT / "results"
SUMMARY_CSV = RESULT_DIR / "summary.csv"
INITIAL_CAPITAL = 5000.0

PAIRS = ["BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT"]
WINDOWS = {
    "last_2d": "20260810-20260812",
    "last_7d": "20260805-20260812",
    "july_7d": "20260715-20260722",
    "last_30d": "20260713-20260812",
}
STRATEGIES = [
    "Strategy1BaselineExact",
    "Strategy1NetStop15",
    "Strategy1Gap04",
    "Strategy1Gap08",
    "Strategy1Slope25",
    "Strategy1ADX25",
    "Strategy1ADX35",
    "Strategy1ATR08",
    "Strategy1Volume125",
    "Strategy1Confirm3",
    "Strategy1Trend200",
    "Strategy1Gap04ADX20",
    "Strategy1Gap04Confirm3",
    "Strategy1Gap04Slope25",
]


def subprocess_environment() -> dict[str, str]:
    env = os.environ.copy()
    for proxy_name, environment_name in (
        ("http", "HTTP_PROXY"),
        ("https", "HTTPS_PROXY"),
        ("all", "ALL_PROXY"),
        ("no", "NO_PROXY"),
    ):
        lower_name = environment_name.lower()
        if env.get(environment_name) or env.get(lower_name):
            continue
        value = getproxies().get(proxy_name)
        if value:
            env[environment_name] = value
            env[lower_name] = value
    return env


def run_command(command: list[str], log_file: Path) -> None:
    print(" ".join(command), flush=True)
    process = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=subprocess_environment(),
    )
    log_file.write_text(process.stdout, encoding="utf-8")
    if process.returncode:
        sys.stdout.write(process.stdout[-4000:])
        raise SystemExit(process.returncode)


def latest_zip(previous: set[Path]) -> Path:
    created = [path for path in RESULT_DIR.glob("*.zip") if path not in previous]
    candidates = created or list(RESULT_DIR.glob("*.zip"))
    if not candidates:
        raise RuntimeError("No backtest zip produced.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def load_payload(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json") and not name.endswith(".meta.json")
        ]
        if not names:
            raise RuntimeError(f"No result JSON in {path}")
        return json.loads(archive.read(names[0]).decode("utf-8"))


def est_fee_abs(trade: dict) -> float:
    return (
        float(trade["fee_open"]) * float(trade["amount"]) * float(trade["open_rate"])
        + float(trade["fee_close"]) * float(trade["amount"]) * float(trade["close_rate"])
    )


def summarize_strategy(strategy_name: str, pair: str, window_name: str, timerange: str, payload: dict, result_file: Path) -> dict:
    strategy = payload["strategy"][strategy_name]
    trades = [trade for trade in strategy.get("trades", []) if trade.get("pair") == pair]
    wins = sum(1 for trade in trades if float(trade.get("profit_abs", 0)) > 0)
    losses = sum(1 for trade in trades if float(trade.get("profit_abs", 0)) < 0)
    profit_abs = sum(float(trade.get("profit_abs", 0)) for trade in trades)
    gross_win = sum(float(trade.get("profit_abs", 0)) for trade in trades if float(trade.get("profit_abs", 0)) > 0)
    gross_loss = -sum(float(trade.get("profit_abs", 0)) for trade in trades if float(trade.get("profit_abs", 0)) < 0)
    long_trades = [trade for trade in trades if not trade.get("is_short")]
    short_trades = [trade for trade in trades if trade.get("is_short")]
    exit_counts = Counter(str(trade.get("exit_reason")) for trade in trades)
    exit_profit = defaultdict(float)
    for trade in trades:
        exit_profit[str(trade.get("exit_reason"))] += float(trade.get("profit_abs", 0))
    durations = sorted(int(trade.get("trade_duration") or 0) for trade in trades)
    side_flips = sum(1 for previous, current in zip(trades, trades[1:]) if previous.get("is_short") != current.get("is_short"))
    fee_abs = sum(est_fee_abs(trade) for trade in trades)
    avg_win = gross_win / wins if wins else 0.0
    avg_loss = gross_loss / losses if losses else 0.0
    return {
        "strategy": strategy_name,
        "pair": pair,
        "window": window_name,
        "timerange": timerange,
        "profit_pct": profit_abs / INITIAL_CAPITAL * 100,
        "max_drawdown_pct": float(strategy.get("max_drawdown_account") or strategy.get("max_drawdown") or 0) * 100,
        "pair_profit_abs": profit_abs,
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": wins / len(trades) * 100 if trades else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss else 0.0,
        "avg_win_abs": avg_win,
        "avg_loss_abs": avg_loss,
        "payoff_ratio": avg_win / avg_loss if avg_loss else 0.0,
        "fees_abs_est": fee_abs,
        "long_trades": len(long_trades),
        "long_profit_abs": sum(float(trade.get("profit_abs", 0)) for trade in long_trades),
        "short_trades": len(short_trades),
        "short_profit_abs": sum(float(trade.get("profit_abs", 0)) for trade in short_trades),
        "roi_exits": exit_counts["roi"],
        "roi_profit_abs": exit_profit["roi"],
        "exit_signal_exits": exit_counts["exit_signal"],
        "exit_signal_profit_abs": exit_profit["exit_signal"],
        "stop_loss_exits": exit_counts["stop_loss"],
        "stop_loss_profit_abs": exit_profit["stop_loss"],
        "force_exit_exits": exit_counts["force_exit"],
        "median_duration_min": durations[len(durations) // 2] if durations else 0,
        "p90_duration_min": durations[int(len(durations) * 0.9)] if durations else 0,
        "side_flips": side_flips,
        "result_file": str(result_file),
    }


def write_rows(rows: list[dict]) -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fieldnames = list(rows[0].keys())
    with SUMMARY_CSV.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    RESULT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    for window_name, timerange in WINDOWS.items():
        for pair in PAIRS:
            before = set(RESULT_DIR.glob("*.zip"))
            command = [
                str(FREQTRADE),
                "backtesting",
                "--config",
                str(CONFIG),
                "--userdir",
                str(USERDIR),
                "--strategy-path",
                str(ROOT / "strategies"),
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
                pair,
            ]
            log_file = RESULT_DIR / f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{window_name}_{pair.replace('/', '_').replace(':', '_')}.log"
            run_command(command, log_file)
            result_file = latest_zip(before)
            payload = load_payload(result_file)
            for strategy_name in STRATEGIES:
                if strategy_name not in payload.get("strategy", {}):
                    continue
                rows.append(summarize_strategy(strategy_name, pair, window_name, timerange, payload, result_file))
            write_rows(rows)
    print(f"Wrote {SUMMARY_CSV}")


if __name__ == "__main__":
    main()
