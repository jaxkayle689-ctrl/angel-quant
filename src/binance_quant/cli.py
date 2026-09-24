from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from .backtest import run_sma_backtest
from .client import BinanceAPIError, SpotClient, UMFuturesClient
from .config import FuturesSettings, Settings, load_futures_settings, load_settings
from .data import fetch_klines, save_csv
from .strategies import latest_sma_signal


def build_client(settings: Settings) -> SpotClient:
    return SpotClient(
        base_url=settings.base_url,
        api_key=settings.api_key,
        api_secret=settings.api_secret,
        recv_window=settings.recv_window,
    )


def build_futures_client(settings: FuturesSettings) -> UMFuturesClient:
    return UMFuturesClient(
        base_url=settings.base_url,
        api_key=settings.api_key,
        api_secret=settings.api_secret,
        recv_window=settings.recv_window,
        credential_hint="BINANCE_FUTURES_API_KEY and BINANCE_FUTURES_API_SECRET",
    )


def print_summary(summary: dict[str, object]) -> None:
    for key, value in summary.items():
        print(f"{key}: {value}")


def command_ping(args: argparse.Namespace) -> None:
    settings = load_settings(args.env_file)
    client = build_client(settings)
    client.ping()
    server_time = client.server_time()
    print(f"OK base_url={settings.base_url}")
    print(f"server_time={server_time.get('serverTime')}")


def command_fetch(args: argparse.Namespace) -> None:
    settings = load_settings(args.env_file)
    client = build_client(settings)
    frame = fetch_klines(client, args.symbol, args.interval, args.limit)
    default_output = f"data/{args.symbol.upper()}_{args.interval}.csv"
    output = save_csv(frame, args.output or default_output)
    print(f"saved {len(frame)} rows -> {output}")


def load_or_fetch_frame(args: argparse.Namespace) -> pd.DataFrame:
    if args.csv:
        return pd.read_csv(args.csv, parse_dates=["open_time", "close_time"])
    settings = load_settings(args.env_file)
    client = build_client(settings)
    return fetch_klines(client, args.symbol, args.interval, args.limit)


def command_backtest(args: argparse.Namespace) -> None:
    frame = load_or_fetch_frame(args)
    result = run_sma_backtest(
        frame,
        fast=args.fast,
        slow=args.slow,
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
    )
    print_summary(result.summary)
    if args.trades_output:
        Path(args.trades_output).parent.mkdir(parents=True, exist_ok=True)
        result.trades.to_csv(args.trades_output, index=False)
        print(f"trades_saved={args.trades_output}")


def command_signal(args: argparse.Namespace) -> None:
    frame = load_or_fetch_frame(args)
    signal = latest_sma_signal(frame, fast=args.fast, slow=args.slow)
    print_summary(signal)


def command_account(args: argparse.Namespace) -> None:
    settings = load_settings(args.env_file)
    client = build_client(settings)
    account = client.account()
    non_zero_balances = [
        item
        for item in account.get("balances", [])
        if float(item.get("free", 0)) > 0 or float(item.get("locked", 0)) > 0
    ]
    for item in non_zero_balances:
        print(f"{item['asset']}: free={item['free']} locked={item['locked']}")
    if not non_zero_balances:
        print("No non-zero balances found.")


def command_order(args: argparse.Namespace) -> None:
    settings = load_settings(args.env_file)
    live_order = bool(args.live)
    if live_order:
        if not settings.allow_live_trading:
            raise SystemExit("Refusing live order: set ALLOW_LIVE_TRADING=true in .env first.")
        if args.confirm != "I_UNDERSTAND":
            raise SystemExit("Refusing live order: add --confirm I_UNDERSTAND.")

    client = build_client(settings)
    payload = client.new_order(
        symbol=args.symbol,
        side=args.side,
        order_type=args.order_type,
        quantity=args.quantity,
        quote_order_qty=args.quote_amount,
        price=args.price,
        time_in_force=args.time_in_force,
        test=not live_order,
    )
    mode = "LIVE" if live_order else "TEST"
    print(f"{mode} order accepted by API.")
    if payload:
        print(payload)


def command_futures_ping(args: argparse.Namespace) -> None:
    settings = load_futures_settings(args.env_file)
    client = build_futures_client(settings)
    client.ping()
    server_time = client.server_time()
    print(f"OK futures_base_url={settings.base_url}")
    print(f"server_time={server_time.get('serverTime')}")


def command_futures_fetch(args: argparse.Namespace) -> None:
    settings = load_futures_settings(args.env_file)
    client = build_futures_client(settings)
    frame = fetch_klines(client, args.symbol, args.interval, args.limit)
    default_output = f"data/FUTURES_{args.symbol.upper()}_{args.interval}.csv"
    output = save_csv(frame, args.output or default_output)
    print(f"saved {len(frame)} rows -> {output}")


def load_or_fetch_futures_frame(args: argparse.Namespace) -> pd.DataFrame:
    if args.csv:
        return pd.read_csv(args.csv, parse_dates=["open_time", "close_time"])
    settings = load_futures_settings(args.env_file)
    client = build_futures_client(settings)
    return fetch_klines(client, args.symbol, args.interval, args.limit)


def command_futures_backtest(args: argparse.Namespace) -> None:
    frame = load_or_fetch_futures_frame(args)
    result = run_sma_backtest(
        frame,
        fast=args.fast,
        slow=args.slow,
        initial_cash=args.initial_cash,
        fee_rate=args.fee_rate,
    )
    print_summary(result.summary)
    if args.trades_output:
        Path(args.trades_output).parent.mkdir(parents=True, exist_ok=True)
        result.trades.to_csv(args.trades_output, index=False)
        print(f"trades_saved={args.trades_output}")


def command_futures_signal(args: argparse.Namespace) -> None:
    frame = load_or_fetch_futures_frame(args)
    signal = latest_sma_signal(frame, fast=args.fast, slow=args.slow)
    print_summary(signal)


def command_futures_account(args: argparse.Namespace) -> None:
    settings = load_futures_settings(args.env_file)
    client = build_futures_client(settings)
    account = client.account()
    assets = [
        item
        for item in account.get("assets", [])
        if float(item.get("walletBalance", 0)) != 0
        or float(item.get("unrealizedProfit", 0)) != 0
        or float(item.get("marginBalance", 0)) != 0
    ]
    print(f"totalWalletBalance={account.get('totalWalletBalance')}")
    print(f"totalUnrealizedProfit={account.get('totalUnrealizedProfit')}")
    print(f"availableBalance={account.get('availableBalance')}")
    for item in assets:
        print(
            f"{item['asset']}: wallet={item.get('walletBalance')} "
            f"unrealized={item.get('unrealizedProfit')} margin={item.get('marginBalance')}"
        )


def command_futures_positions(args: argparse.Namespace) -> None:
    settings = load_futures_settings(args.env_file)
    client = build_futures_client(settings)
    positions = client.position_risk(args.symbol)
    active_positions = [
        item
        for item in positions
        if float(item.get("positionAmt", 0)) != 0 or float(item.get("unRealizedProfit", 0)) != 0
    ]
    for item in active_positions:
        print(
            f"{item['symbol']} {item.get('positionSide', 'BOTH')}: "
            f"amount={item.get('positionAmt')} entry={item.get('entryPrice')} "
            f"mark={item.get('markPrice')} leverage={item.get('leverage')} "
            f"unrealized={item.get('unRealizedProfit')} liq={item.get('liquidationPrice')}"
        )
    if not active_positions:
        print("No active futures positions found.")


def command_futures_leverage(args: argparse.Namespace) -> None:
    if args.leverage < 1 or args.leverage > 125:
        raise SystemExit("Leverage must be between 1 and 125.")
    settings = load_futures_settings(args.env_file)
    client = build_futures_client(settings)
    payload = client.change_leverage(args.symbol, args.leverage)
    print(payload)


def command_futures_margin_type(args: argparse.Namespace) -> None:
    settings = load_futures_settings(args.env_file)
    client = build_futures_client(settings)
    payload = client.change_margin_type(args.symbol, args.margin_type)
    print(payload)


def command_futures_order(args: argparse.Namespace) -> None:
    settings = load_futures_settings(args.env_file)
    live_order = bool(args.live)
    if live_order:
        if not settings.allow_live_trading:
            raise SystemExit("Refusing futures live order: set ALLOW_FUTURES_LIVE_TRADING=true in .env first.")
        if args.confirm != "I_UNDERSTAND":
            raise SystemExit("Refusing futures live order: add --confirm I_UNDERSTAND.")

    client = build_futures_client(settings)
    payload = client.new_order(
        symbol=args.symbol,
        side=args.side,
        order_type=args.order_type,
        quantity=args.quantity,
        price=args.price,
        time_in_force=args.time_in_force,
        position_side=args.position_side,
        reduce_only=args.reduce_only,
        stop_price=args.stop_price,
        test=not live_order,
    )
    mode = "LIVE" if live_order else "TEST"
    print(f"FUTURES {mode} order accepted by API.")
    if payload:
        print(payload)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bq", description="Binance Spot and USD-M Futures quant starter CLI.")
    parser.add_argument("--env-file", default=".env", help="Path to .env file.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ping = subparsers.add_parser("ping", help="Check API connectivity.")
    ping.set_defaults(func=command_ping)

    fetch = subparsers.add_parser("fetch", help="Fetch recent klines to CSV.")
    fetch.add_argument("--symbol", default="BTCUSDT")
    fetch.add_argument("--interval", default="1h")
    fetch.add_argument("--limit", type=int, default=500)
    fetch.add_argument("--output")
    fetch.set_defaults(func=command_fetch)

    backtest = subparsers.add_parser("backtest", help="Run SMA crossover backtest.")
    backtest.add_argument("--csv")
    backtest.add_argument("--symbol", default="BTCUSDT")
    backtest.add_argument("--interval", default="1h")
    backtest.add_argument("--limit", type=int, default=1000)
    backtest.add_argument("--fast", type=int, default=20)
    backtest.add_argument("--slow", type=int, default=60)
    backtest.add_argument("--initial-cash", type=float, default=1000.0)
    backtest.add_argument("--fee-rate", type=float, default=0.001)
    backtest.add_argument("--trades-output")
    backtest.set_defaults(func=command_backtest)

    signal = subparsers.add_parser("signal", help="Print latest SMA crossover signal.")
    signal.add_argument("--csv")
    signal.add_argument("--symbol", default="BTCUSDT")
    signal.add_argument("--interval", default="1h")
    signal.add_argument("--limit", type=int, default=500)
    signal.add_argument("--fast", type=int, default=20)
    signal.add_argument("--slow", type=int, default=60)
    signal.set_defaults(func=command_signal)

    account = subparsers.add_parser("account", help="Print non-zero account balances.")
    account.set_defaults(func=command_account)

    order = subparsers.add_parser("order", help="Submit a test order by default.")
    order.add_argument("--symbol", default="BTCUSDT")
    order.add_argument("--side", choices=["BUY", "SELL"], required=True)
    order.add_argument("--order-type", default="MARKET")
    order.add_argument("--quantity")
    order.add_argument("--quote-amount")
    order.add_argument("--price")
    order.add_argument("--time-in-force")
    order.add_argument("--live", action="store_true")
    order.add_argument("--confirm")
    order.set_defaults(func=command_order)

    futures_ping = subparsers.add_parser("futures-ping", help="Check USD-M Futures API connectivity.")
    futures_ping.set_defaults(func=command_futures_ping)

    futures_fetch = subparsers.add_parser("futures-fetch", help="Fetch recent USD-M Futures klines to CSV.")
    futures_fetch.add_argument("--symbol", default="BTCUSDT")
    futures_fetch.add_argument("--interval", default="1h")
    futures_fetch.add_argument("--limit", type=int, default=500)
    futures_fetch.add_argument("--output")
    futures_fetch.set_defaults(func=command_futures_fetch)

    futures_backtest = subparsers.add_parser("futures-backtest", help="Run SMA backtest on USD-M Futures klines.")
    futures_backtest.add_argument("--csv")
    futures_backtest.add_argument("--symbol", default="BTCUSDT")
    futures_backtest.add_argument("--interval", default="1h")
    futures_backtest.add_argument("--limit", type=int, default=1000)
    futures_backtest.add_argument("--fast", type=int, default=20)
    futures_backtest.add_argument("--slow", type=int, default=60)
    futures_backtest.add_argument("--initial-cash", type=float, default=1000.0)
    futures_backtest.add_argument("--fee-rate", type=float, default=0.0005)
    futures_backtest.add_argument("--trades-output")
    futures_backtest.set_defaults(func=command_futures_backtest)

    futures_signal = subparsers.add_parser("futures-signal", help="Print latest USD-M Futures SMA signal.")
    futures_signal.add_argument("--csv")
    futures_signal.add_argument("--symbol", default="BTCUSDT")
    futures_signal.add_argument("--interval", default="1h")
    futures_signal.add_argument("--limit", type=int, default=500)
    futures_signal.add_argument("--fast", type=int, default=20)
    futures_signal.add_argument("--slow", type=int, default=60)
    futures_signal.set_defaults(func=command_futures_signal)

    futures_account = subparsers.add_parser("futures-account", help="Print USD-M Futures account summary.")
    futures_account.set_defaults(func=command_futures_account)

    futures_positions = subparsers.add_parser("futures-positions", help="Print active USD-M Futures positions.")
    futures_positions.add_argument("--symbol")
    futures_positions.set_defaults(func=command_futures_positions)

    futures_leverage = subparsers.add_parser("futures-leverage", help="Change USD-M Futures leverage.")
    futures_leverage.add_argument("--symbol", default="BTCUSDT")
    futures_leverage.add_argument("--leverage", type=int, required=True)
    futures_leverage.set_defaults(func=command_futures_leverage)

    futures_margin_type = subparsers.add_parser("futures-margin-type", help="Change USD-M Futures margin type.")
    futures_margin_type.add_argument("--symbol", default="BTCUSDT")
    futures_margin_type.add_argument("--margin-type", choices=["ISOLATED", "CROSSED"], required=True)
    futures_margin_type.set_defaults(func=command_futures_margin_type)

    futures_order = subparsers.add_parser("futures-order", help="Submit a USD-M Futures test order by default.")
    futures_order.add_argument("--symbol", default="BTCUSDT")
    futures_order.add_argument("--side", choices=["BUY", "SELL"], required=True)
    futures_order.add_argument("--order-type", default="MARKET")
    futures_order.add_argument("--quantity", required=True)
    futures_order.add_argument("--price")
    futures_order.add_argument("--time-in-force")
    futures_order.add_argument("--position-side", choices=["BOTH", "LONG", "SHORT"])
    futures_order.add_argument("--reduce-only", action="store_true")
    futures_order.add_argument("--stop-price")
    futures_order.add_argument("--live", action="store_true")
    futures_order.add_argument("--confirm")
    futures_order.set_defaults(func=command_futures_order)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    except BinanceAPIError as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
