from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import urlencode

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


class BinanceAPIError(RuntimeError):
    def __init__(self, status_code: int, payload: Any):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"Binance API error {status_code}: {payload}")


class BaseBinanceClient:
    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        api_secret: str = "",
        recv_window: int = 5000,
        timeout: float = 10,
        credential_hint: str = "BINANCE_API_KEY and BINANCE_API_SECRET",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.recv_window = recv_window
        self.timeout = timeout
        self.credential_hint = credential_hint
        self.time_offset_ms = 0
        self.session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=2,
            status=2,
            backoff_factor=0.35,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.session.mount("https://", adapter)

    def _signed_params(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key or not self.api_secret:
            raise ValueError(f"{self.credential_hint} are required for signed endpoints.")

        signed = dict(params)
        signed["timestamp"] = int(time.time() * 1000) + self.time_offset_ms
        signed["recvWindow"] = self.recv_window
        query_string = urlencode(signed, doseq=True)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        signed["signature"] = signature
        return signed

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = False,
        _timestamp_retry: bool = True,
    ) -> Any:
        request_params = {key: value for key, value in (params or {}).items() if value is not None}
        if signed:
            request_params = self._signed_params(request_params)

        headers = {}
        if self.api_key:
            headers["X-MBX-APIKEY"] = self.api_key
        method_name = method.upper()
        request_kwargs: dict[str, Any] = {}
        if method_name == "GET":
            request_kwargs["params"] = request_params
        else:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            request_kwargs["data"] = request_params

        response = self.session.request(
            method_name,
            f"{self.base_url}{path}",
            headers=headers,
            timeout=self.timeout,
            **request_kwargs,
        )

        if response.content:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
        else:
            payload = {}

        if (
            not response.ok
            and signed
            and _timestamp_retry
            and isinstance(payload, dict)
            and payload.get("code") == -1021
        ):
            self.sync_time()
            return self.request(method, path, params, signed=True, _timestamp_retry=False)
        if not response.ok:
            raise BinanceAPIError(response.status_code, payload)
        return payload

    def sync_time(self) -> int:
        payload = self.server_time()
        server_time = int(payload.get("serverTime"))
        self.time_offset_ms = server_time - int(time.time() * 1000)
        return self.time_offset_ms


class SpotClient(BaseBinanceClient):

    def ping(self) -> Any:
        return self.request("GET", "/api/v3/ping")

    def server_time(self) -> Any:
        return self.request("GET", "/api/v3/time")

    def exchange_info(self, symbol: str | None = None) -> Any:
        return self.request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})

    def ticker_price(self, symbol: str) -> Any:
        return self.request("GET", "/api/v3/ticker/price", {"symbol": symbol.upper()})

    def klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> Any:
        return self.request(
            "GET",
            "/api/v3/klines",
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit,
                "startTime": start_time,
                "endTime": end_time,
            },
        )

    def account(self) -> Any:
        return self.request("GET", "/api/v3/account", signed=True)

    def new_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "MARKET",
        quantity: str | float | None = None,
        quote_order_qty: str | float | None = None,
        price: str | float | None = None,
        time_in_force: str | None = None,
        test: bool = True,
    ) -> Any:
        path = "/api/v3/order/test" if test else "/api/v3/order"
        return self.request(
            "POST",
            path,
            {
                "symbol": symbol.upper(),
                "side": side.upper(),
                "type": order_type.upper(),
                "quantity": quantity,
                "quoteOrderQty": quote_order_qty,
                "price": price,
                "timeInForce": time_in_force,
            },
            signed=True,
        )


class UMFuturesClient(BaseBinanceClient):
    def ping(self) -> Any:
        return self.request("GET", "/fapi/v1/ping")

    def server_time(self) -> Any:
        return self.request("GET", "/fapi/v1/time")

    def exchange_info(self, symbol: str | None = None) -> Any:
        return self.request("GET", "/fapi/v1/exchangeInfo", {"symbol": symbol})

    def ticker_price(self, symbol: str) -> Any:
        return self.request("GET", "/fapi/v1/ticker/price", {"symbol": symbol.upper()})

    def ticker_24h(self, symbol: str) -> Any:
        return self.request("GET", "/fapi/v1/ticker/24hr", {"symbol": symbol.upper()})

    def mark_price(self, symbol: str) -> Any:
        return self.request("GET", "/fapi/v1/premiumIndex", {"symbol": symbol.upper()})

    def book_ticker(self, symbol: str) -> Any:
        return self.request("GET", "/fapi/v1/ticker/bookTicker", {"symbol": symbol.upper()})

    def klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> Any:
        return self.request(
            "GET",
            "/fapi/v1/klines",
            {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit,
                "startTime": start_time,
                "endTime": end_time,
            },
        )

    def account(self) -> Any:
        return self.request("GET", "/fapi/v3/account", signed=True)

    def balance(self) -> Any:
        return self.request("GET", "/fapi/v3/balance", signed=True)

    def position_risk(self, symbol: str | None = None) -> Any:
        return self.request("GET", "/fapi/v3/positionRisk", {"symbol": symbol.upper() if symbol else None}, signed=True)

    def symbol_config(self, symbol: str | None = None) -> Any:
        return self.request(
            "GET",
            "/fapi/v1/symbolConfig",
            {"symbol": symbol.upper() if symbol else None},
            signed=True,
        )

    def position_mode(self) -> Any:
        return self.request("GET", "/fapi/v1/positionSide/dual", signed=True)

    def commission_rate(self, symbol: str) -> Any:
        return self.request(
            "GET",
            "/fapi/v1/commissionRate",
            {"symbol": symbol.upper()},
            signed=True,
        )

    def user_trades(
        self,
        symbol: str,
        order_id: int | str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
        from_id: int | None = None,
        limit: int = 1000,
    ) -> Any:
        return self.request(
            "GET",
            "/fapi/v1/userTrades",
            {
                "symbol": symbol.upper(),
                "orderId": order_id,
                "startTime": start_time,
                "endTime": end_time,
                "fromId": from_id,
                "limit": limit,
            },
            signed=True,
        )

    def start_user_data_stream(self) -> Any:
        return self.request("POST", "/fapi/v1/listenKey")

    def keepalive_user_data_stream(self) -> Any:
        return self.request("PUT", "/fapi/v1/listenKey")

    def close_user_data_stream(self) -> Any:
        return self.request("DELETE", "/fapi/v1/listenKey")

    def current_open_orders(self, symbol: str | None = None) -> Any:
        return self.request(
            "GET",
            "/fapi/v1/openOrders",
            {"symbol": symbol.upper() if symbol else None},
            signed=True,
        )

    def current_algo_open_orders(self, symbol: str | None = None) -> Any:
        return self.request(
            "GET",
            "/fapi/v1/openAlgoOrders",
            {
                "algoType": "CONDITIONAL",
                "symbol": symbol.upper() if symbol else None,
            },
            signed=True,
        )

    def change_leverage(self, symbol: str, leverage: int) -> Any:
        return self.request(
            "POST",
            "/fapi/v1/leverage",
            {
                "symbol": symbol.upper(),
                "leverage": leverage,
            },
            signed=True,
        )

    def change_margin_type(self, symbol: str, margin_type: str) -> Any:
        return self.request(
            "POST",
            "/fapi/v1/marginType",
            {
                "symbol": symbol.upper(),
                "marginType": margin_type.upper(),
            },
            signed=True,
        )

    def new_order(
        self,
        symbol: str,
        side: str,
        order_type: str = "MARKET",
        quantity: str | float | None = None,
        price: str | float | None = None,
        time_in_force: str | None = None,
        position_side: str | None = None,
        reduce_only: bool | None = None,
        stop_price: str | float | None = None,
        client_order_id: str | None = None,
        new_order_resp_type: str | None = None,
        test: bool = True,
    ) -> Any:
        path = "/fapi/v1/order/test" if test else "/fapi/v1/order"
        return self.request(
            "POST",
            path,
            {
                "symbol": symbol.upper(),
                "side": side.upper(),
                "type": order_type.upper(),
                "quantity": quantity,
                "price": price,
                "timeInForce": time_in_force,
                "positionSide": position_side.upper() if position_side else None,
                "reduceOnly": "true" if reduce_only else None,
                "stopPrice": stop_price,
                "newClientOrderId": client_order_id,
                "newOrderRespType": new_order_resp_type,
            },
            signed=True,
        )

    def cancel_order(
        self,
        symbol: str,
        order_id: int | str | None = None,
        client_order_id: str | None = None,
    ) -> Any:
        if order_id is None and not client_order_id:
            raise ValueError("order_id or client_order_id is required.")
        return self.request(
            "DELETE",
            "/fapi/v1/order",
            {
                "symbol": symbol.upper(),
                "orderId": order_id,
                "origClientOrderId": client_order_id,
            },
            signed=True,
        )

    def new_algo_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        trigger_price: str | float,
        position_side: str = "BOTH",
        close_position: bool = True,
        working_type: str = "MARK_PRICE",
        price_protect: bool = False,
        client_algo_id: str | None = None,
    ) -> Any:
        return self.request(
            "POST",
            "/fapi/v1/algoOrder",
            {
                "algoType": "CONDITIONAL",
                "symbol": symbol.upper(),
                "side": side.upper(),
                "type": order_type.upper(),
                "triggerPrice": trigger_price,
                "positionSide": position_side.upper(),
                "closePosition": "true" if close_position else "false",
                "workingType": working_type.upper(),
                "priceProtect": "true" if price_protect else "false",
                "clientAlgoId": client_algo_id,
            },
            signed=True,
        )

    def cancel_algo_order(
        self,
        algo_id: int | str | None = None,
        client_algo_id: str | None = None,
    ) -> Any:
        if algo_id is None and not client_algo_id:
            raise ValueError("algo_id or client_algo_id is required.")
        return self.request(
            "DELETE",
            "/fapi/v1/algoOrder",
            {
                "algoId": algo_id,
                "clientAlgoId": client_algo_id,
            },
            signed=True,
        )
