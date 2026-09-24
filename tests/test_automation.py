from __future__ import annotations

import time
import unittest
from decimal import Decimal

from binance_quant.automation import (
    DEMO_FUTURES_URL,
    AutomationConfig,
    DemoAutomation,
    SymbolRules,
)
from binance_quant.client import UMFuturesClient


def automation_payload(**overrides):
    payload = {
        "confirmation": "DEMO_ONLY",
        "symbol": "BTCUSDT",
        "interval": "1m",
        "strategy_id": "sma_crossover",
        "parameters": {"fast": 5, "slow": 20, "direction": "LONG_SHORT"},
        "leverage": 3,
        "allocation_pct": 5,
        "stop_loss_pct": 1,
        "take_profit_pct": 2,
        "daily_max_loss_pct": 3,
    }
    payload.update(overrides)
    return payload


def exchange_info():
    return {
        "symbols": [
            {
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                    {"filterType": "MARKET_LOT_SIZE", "minQty": "0.001", "maxQty": "100", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ]
    }


def klines(count: int = 240):
    now_ms = int(time.time() * 1000)
    start = now_ms - (count + 2) * 60_000
    rows = []
    for index in range(count):
        open_time = start + index * 60_000
        close_time = open_time + 59_999
        price = 60_000 + index
        rows.append(
            [
                open_time,
                str(price),
                str(price + 10),
                str(price - 10),
                str(price + 1),
                "100",
                close_time,
                "6000000",
                100,
                "50",
                "3000000",
                "0",
            ]
        )
    return rows


class FakeDemoClient:
    base_url = DEMO_FUTURES_URL

    def __init__(self) -> None:
        self.amount = Decimal("0")
        self.entry_price = Decimal("60000")
        self.extra_positions = []
        self.orders = []
        self.regular_orders = []
        self.algo_orders = []
        self.margin_changes = []
        self.leverage_changes = []
        self.cancelled_orders = []

    def position_mode(self):
        return {"dualSidePosition": False}

    def position_risk(self, symbol=None):
        positions = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": str(self.amount),
                "entryPrice": str(self.entry_price),
            }
        ]
        return positions + list(self.extra_positions)

    def exchange_info(self, symbol=None):
        return exchange_info()

    def current_open_orders(self, symbol=None):
        return list(self.regular_orders)

    def current_algo_open_orders(self, symbol=None):
        return list(self.algo_orders)

    def cancel_algo_order(self, algo_id=None, client_algo_id=None):
        self.algo_orders = [
            item
            for item in self.algo_orders
            if item.get("algoId") != algo_id and item.get("clientAlgoId") != client_algo_id
        ]
        return {"code": 200}

    def change_margin_type(self, symbol, margin_type):
        self.margin_changes.append((symbol, margin_type))
        return {"code": 200}

    def change_leverage(self, symbol, leverage):
        self.leverage_changes.append((symbol, leverage))
        return {"leverage": leverage}

    def account(self):
        return {
            "totalMarginBalance": "5000",
            "totalWalletBalance": "5000",
            "availableBalance": "5000",
        }

    def commission_rate(self, symbol):
        return {"makerCommissionRate": "0.0002", "takerCommissionRate": "0.0005"}

    def klines(self, symbol, interval, limit=500):
        return klines(limit)

    def mark_price(self, symbol):
        return {"markPrice": "60000"}

    def book_ticker(self, symbol):
        return {"bidPrice": "59999.90", "askPrice": "60000.10"}

    def cancel_order(self, symbol, order_id=None, client_order_id=None):
        self.cancelled_orders.append((symbol, order_id, client_order_id))
        self.regular_orders = [
            item
            for item in self.regular_orders
            if item.get("orderId") != order_id and item.get("clientOrderId") != client_order_id
        ]
        return {"status": "CANCELED"}

    def new_order(self, symbol, side, order_type="MARKET", quantity=None, reduce_only=None, **kwargs):
        quantity_value = Decimal(str(quantity))
        if reduce_only:
            self.amount = Decimal("0")
        else:
            self.amount = quantity_value if side == "BUY" else -quantity_value
        self.orders.append({
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
            "reduce_only": reduce_only,
            **kwargs,
        })
        return {"status": "FILLED", "avgPrice": str(self.entry_price)}

    def new_algo_order(self, symbol, side, order_type, trigger_price, client_algo_id=None, **kwargs):
        order = {
            "algoId": len(self.algo_orders) + 1,
            "clientAlgoId": client_algo_id,
            "orderType": order_type,
            "triggerPrice": str(trigger_price),
            "symbol": symbol,
            "side": side,
        }
        self.algo_orders.append(order)
        return order


class AutomationTests(unittest.TestCase):
    def test_config_enforces_demo_leverage_cap(self) -> None:
        with self.assertRaisesRegex(ValueError, "1 到 125"):
            AutomationConfig.from_payload(automation_payload(leverage=126))

    def test_ema_pullback_requires_at_least_50x(self) -> None:
        with self.assertRaisesRegex(ValueError, "至少 50"):
            AutomationConfig.from_payload(
                automation_payload(
                    strategy_id="ema7_trend_pullback",
                    parameters={},
                    leverage=49,
                    stop_loss_pct=15,
                    take_profit_pct=3,
                )
            )

    def test_symbol_rules_floor_quantity_and_prices(self) -> None:
        rules = SymbolRules.from_exchange_info(exchange_info(), "BTCUSDT")
        quantity = rules.quantity_for(Decimal("5000"), 5, 3, Decimal("64019.07"))
        self.assertEqual(quantity, Decimal("0.011"))
        self.assertEqual(rules.price(Decimal("63378.8793")), Decimal("63378.80"))

    def test_only_app_owned_regular_orders_are_recovered(self) -> None:
        client = FakeDemoClient()
        client.regular_orders = [
            {"orderId": 1, "clientOrderId": "bq_123_open"},
            {"orderId": 2, "clientOrderId": "manual_order"},
        ]
        engine = DemoAutomation(client)
        engine._cancel_owned_regular_orders("BTCUSDT")
        self.assertEqual(client.regular_orders, [{"orderId": 2, "clientOrderId": "manual_order"}])

    def test_client_uses_current_algo_order_endpoint(self) -> None:
        client = UMFuturesClient(DEMO_FUTURES_URL, "key", "secret")
        captured = {}

        def request(method, path, params=None, signed=False):
            captured.update(method=method, path=path, params=params, signed=signed)
            return {"algoId": 1}

        client.request = request  # type: ignore[method-assign]
        client.new_algo_order(
            "BTCUSDT",
            "SELL",
            "STOP_MARKET",
            "59000",
            close_position=True,
            client_algo_id="bq_test_sl",
        )
        self.assertEqual(captured["path"], "/fapi/v1/algoOrder")
        self.assertEqual(captured["params"]["triggerPrice"], "59000")
        self.assertEqual(captured["params"]["closePosition"], "true")
        self.assertTrue(captured["signed"])

    def test_client_uses_trade_history_and_user_stream_endpoints(self) -> None:
        client = UMFuturesClient(DEMO_FUTURES_URL, "key", "secret")
        calls = []

        def request(method, path, params=None, signed=False):
            calls.append((method, path, params, signed))
            return {"listenKey": "test"} if method == "POST" else []

        client.request = request  # type: ignore[method-assign]
        client.user_trades("BTCUSDT", start_time=1, end_time=2, limit=1000)
        client.start_user_data_stream()
        client.keepalive_user_data_stream()
        client.close_user_data_stream()
        self.assertEqual(calls[0][1], "/fapi/v1/userTrades")
        self.assertTrue(calls[0][3])
        self.assertEqual([item[:2] for item in calls[1:]], [
            ("POST", "/fapi/v1/listenKey"),
            ("PUT", "/fapi/v1/listenKey"),
            ("DELETE", "/fapi/v1/listenKey"),
        ])

    def test_signed_request_resyncs_after_timestamp_error(self) -> None:
        class FakeResponse:
            def __init__(self, status_code, payload):
                self.status_code = status_code
                self.payload = payload
                self.ok = status_code < 400
                self.content = b"json"

            def json(self):
                return self.payload

        client = UMFuturesClient(DEMO_FUTURES_URL, "key", "secret")
        responses = [
            FakeResponse(400, {"code": -1021, "msg": "timestamp"}),
            FakeResponse(200, {"totalWalletBalance": "5000"}),
        ]
        client.session.request = lambda *args, **kwargs: responses.pop(0)  # type: ignore[method-assign]
        server_time = int(time.time() * 1000) + 5000
        client.server_time = lambda: {"serverTime": server_time}  # type: ignore[method-assign]
        result = client.account()
        self.assertEqual(result["totalWalletBalance"], "5000")
        self.assertGreaterEqual(client.time_offset_ms, 4900)

    def test_live_client_is_hard_locked_before_account_calls(self) -> None:
        client = UMFuturesClient("https://fapi.binance.com", "key", "secret")
        engine = DemoAutomation(client)
        with self.assertRaisesRegex(ValueError, "Demo"):
            engine.start(automation_payload())
        self.assertFalse(engine.status()["running"])

    def test_safe_start_waits_for_next_closed_candle(self) -> None:
        client = FakeDemoClient()
        engine = DemoAutomation(client, poll_seconds=3600)
        status = engine.start(automation_payload())
        try:
            self.assertTrue(status["running"])
            self.assertIn("等待下一根", status["reason"])
            self.assertEqual(client.margin_changes, [("BTCUSDT", "ISOLATED")])
            self.assertEqual(client.leverage_changes, [("BTCUSDT", 3)])
            self.assertEqual(client.orders, [])
        finally:
            engine.stop(close_position=False)

    def test_open_position_always_places_stop_and_take_profit(self) -> None:
        client = FakeDemoClient()
        engine = DemoAutomation(client)
        config = AutomationConfig.from_payload(automation_payload())
        engine._config = config
        engine._rules = SymbolRules.from_exchange_info(exchange_info(), "BTCUSDT")
        engine._execute_target(config, signal=1, amount=Decimal("0"))
        self.assertGreater(client.amount, 0)
        self.assertEqual([item["orderType"] for item in client.algo_orders], ["STOP_MARKET", "TAKE_PROFIT_MARKET"])
        self.assertTrue(all(item["clientAlgoId"].startswith("bq_") for item in client.algo_orders))

    def test_ema_pullback_uses_maker_entry_and_net_roi_protection(self) -> None:
        client = FakeDemoClient()
        engine = DemoAutomation(client)
        config = AutomationConfig.from_payload(
            automation_payload(
                strategy_id="ema7_trend_pullback",
                parameters={},
                leverage=50,
                stop_loss_pct=15,
                take_profit_pct=3,
            )
        )
        engine._config = config
        engine._rules = SymbolRules.from_exchange_info(exchange_info(), "BTCUSDT")
        engine._policy = {
            "entry_order": "MAKER_GTX",
            "entry_timeout_seconds": 0.25,
            "protection_mode": "NET_ROI_STRUCTURAL",
            "max_spread_bps": 2,
            "exit_slippage_bps": 1,
        }
        engine._maker_rate = Decimal("0.0002")
        engine._taker_rate = Decimal("0.0005")
        engine._execute_target(
            config,
            signal=1,
            amount=Decimal("0"),
            signal_row={"stop_price": 59880, "resistance_level": 61000},
        )
        self.assertGreater(client.amount, 0)
        self.assertEqual(client.orders[0]["time_in_force"], "GTX")
        self.assertEqual([item["orderType"] for item in client.algo_orders], ["STOP_MARKET", "TAKE_PROFIT_MARKET"])
        self.assertGreaterEqual(
            engine._net_roi_pct(config, 1, Decimal("60000"), engine._active_take_price),
            Decimal("3"),
        )
        self.assertGreaterEqual(
            engine._net_roi_pct(config, 1, Decimal("60000"), engine._active_stop_price),
            Decimal("-15"),
        )

    def test_ema_pullback_rejects_structure_beyond_loss_cap(self) -> None:
        client = FakeDemoClient()
        engine = DemoAutomation(client)
        config = AutomationConfig.from_payload(
            automation_payload(
                strategy_id="ema7_trend_pullback",
                parameters={},
                leverage=50,
                stop_loss_pct=15,
                take_profit_pct=3,
            )
        )
        engine._config = config
        engine._rules = SymbolRules.from_exchange_info(exchange_info(), "BTCUSDT")
        engine._policy = {
            "entry_order": "MAKER_GTX",
            "protection_mode": "NET_ROI_STRUCTURAL",
            "max_spread_bps": 2,
            "exit_slippage_bps": 1,
        }
        engine._execute_target(
            config,
            signal=1,
            amount=Decimal("0"),
            signal_row={"stop_price": 59700, "resistance_level": 61000},
        )
        self.assertEqual(client.amount, Decimal("0"))
        self.assertEqual(client.orders, [])

    def test_strategy_1_places_fixed_fifteen_percent_net_roi_take_profit(self) -> None:
        client = FakeDemoClient()
        engine = DemoAutomation(client)
        config = AutomationConfig.from_payload(
            automation_payload(
                strategy_id="strategy_1",
                parameters={},
                leverage=20,
                stop_loss_pct=25,
                take_profit_pct=15,
            )
        )
        engine._config = config
        engine._rules = SymbolRules.from_exchange_info(exchange_info(), "BTCUSDT")
        engine._policy = {
            "entry_order": "MARKET",
            "protection_mode": "NET_ROI_FIXED",
            "reverse_on_signal_change": False,
            "reenter_same_signal": False,
            "exit_slippage_bps": 1,
        }
        engine._maker_rate = Decimal("0.0002")
        engine._taker_rate = Decimal("0.0005")
        engine._execute_target(config, signal=1, amount=Decimal("0"))
        self.assertGreater(client.amount, 0)
        self.assertEqual([item["orderType"] for item in client.algo_orders], ["STOP_MARKET", "TAKE_PROFIT_MARKET"])
        self.assertGreaterEqual(
            engine._net_roi_pct(config, 1, Decimal("60000"), engine._active_take_price),
            Decimal("15"),
        )
        self.assertGreaterEqual(
            engine._net_roi_pct(config, 1, Decimal("60000"), engine._active_stop_price),
            Decimal("-25"),
        )

    def test_strategy_1_holds_position_when_signal_direction_changes(self) -> None:
        client = FakeDemoClient()
        client.amount = Decimal("0.01")
        engine = DemoAutomation(client)
        config = AutomationConfig.from_payload(
            automation_payload(
                strategy_id="strategy_1",
                parameters={},
                leverage=20,
                stop_loss_pct=25,
                take_profit_pct=15,
            )
        )
        engine._config = config
        engine._rules = SymbolRules.from_exchange_info(exchange_info(), "BTCUSDT")
        engine._policy = {
            "entry_order": "MARKET",
            "protection_mode": "NET_ROI_FIXED",
            "reverse_on_signal_change": False,
            "reenter_same_signal": False,
            "exit_slippage_bps": 1,
        }

        engine._execute_target(config, signal=-1, amount=client.amount)

        self.assertGreater(client.amount, 0)
        self.assertEqual(client.orders, [])
        self.assertEqual(client.algo_orders, [])

    def test_market_open_confirmation_failure_flattens_position(self) -> None:
        client = FakeDemoClient()
        engine = DemoAutomation(client)
        config = AutomationConfig.from_payload(automation_payload())
        engine._config = config
        engine._rules = SymbolRules.from_exchange_info(exchange_info(), "BTCUSDT")

        def fail_confirmation(symbol, signal):
            raise ValueError("position confirmation timed out")

        engine._wait_for_position = fail_confirmation  # type: ignore[method-assign]
        with self.assertRaisesRegex(ValueError, "confirmation timed out"):
            engine._execute_target(config, signal=1, amount=Decimal("0"))

        self.assertEqual(client.amount, Decimal("0"))
        self.assertTrue(client.orders[-1].get("reduce_only"))

    def test_protection_failure_flattens_new_position(self) -> None:
        class FailingProtectionClient(FakeDemoClient):
            def new_algo_order(self, symbol, side, order_type, trigger_price, client_algo_id=None, **kwargs):
                if order_type == "TAKE_PROFIT_MARKET":
                    raise RuntimeError("protection rejected")
                return super().new_algo_order(symbol, side, order_type, trigger_price, client_algo_id, **kwargs)

        client = FailingProtectionClient()
        engine = DemoAutomation(client)
        config = AutomationConfig.from_payload(automation_payload())
        engine._config = config
        engine._rules = SymbolRules.from_exchange_info(exchange_info(), "BTCUSDT")
        with self.assertRaisesRegex(RuntimeError, "protection rejected"):
            engine._execute_target(config, signal=1, amount=Decimal("0"))
        self.assertEqual(client.amount, Decimal("0"))
        self.assertEqual(client.algo_orders, [])

    def test_other_contract_position_halts_without_closing_it(self) -> None:
        client = FakeDemoClient()
        client.extra_positions = [{"symbol": "ETHUSDT", "positionAmt": "1", "entryPrice": "3000"}]
        engine = DemoAutomation(client)
        engine._config = AutomationConfig.from_payload(automation_payload())
        engine._baseline_balance = Decimal("5000")
        engine._baseline_date = time.strftime("%Y-%m-%d", time.gmtime())
        engine._running = True
        engine._tick()
        self.assertEqual(engine.status()["status"], "halted")
        self.assertEqual(client.extra_positions[0]["positionAmt"], "1")

    def test_external_reversal_is_flattened_and_halted(self) -> None:
        client = FakeDemoClient()
        client.amount = Decimal("-0.01")
        engine = DemoAutomation(client)
        engine._config = AutomationConfig.from_payload(automation_payload())
        engine._baseline_balance = Decimal("5000")
        engine._baseline_date = time.strftime("%Y-%m-%d", time.gmtime())
        engine._managed_direction = 1
        engine._running = True
        engine._tick()
        self.assertEqual(client.amount, Decimal("0"))
        self.assertEqual(engine.status()["status"], "halted")


if __name__ == "__main__":
    unittest.main()
