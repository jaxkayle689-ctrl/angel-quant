from __future__ import annotations

from datetime import timedelta

from pandas import DataFrame
import talib.abstract as ta

from freqtrade.strategy import IStrategy, informative


class Strategy1Base(IStrategy):
    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "1m"
    startup_candle_count = 25
    process_only_new_candles = True

    # Freqtrade futures profit_ratio is leverage-adjusted. These values target
    # margin ROI, not raw underlying price movement.
    minimal_roi = {"0": 0.03}
    stoploss = -0.15
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    order_types = {
        "entry": "market",
        "exit": "market",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    ema_gap_min = 0.0
    slope_window = 0
    slope_min = 0.0
    adx_min = 0.0
    atr_min = 0.0
    volume_mult = 0.0
    confirm_candles = 1
    trend_filter = False
    net_stoploss = False

    def leverage(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag,
        side: str,
        **kwargs,
    ) -> float:
        return min(50.0, max_leverage)

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema7"] = ta.EMA(dataframe, timeperiod=7)
        dataframe["ema25"] = ta.EMA(dataframe, timeperiod=25)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["ema_gap"] = (dataframe["ema7"] - dataframe["ema25"]).abs() / dataframe["close"]
        dataframe["ema25_slope"] = dataframe["ema25"].pct_change(self.slope_window or 1)
        dataframe["volume_sma20"] = dataframe["volume"].rolling(20).mean()
        dataframe["ema_side"] = 0
        dataframe.loc[dataframe["ema7"] > dataframe["ema25"], "ema_side"] = 1
        dataframe.loc[dataframe["ema7"] < dataframe["ema25"], "ema_side"] = -1
        return dataframe

    def _entry_filter(self, dataframe: DataFrame) -> DataFrame:
        active = dataframe["volume"] > 0
        if self.ema_gap_min:
            active &= dataframe["ema_gap"] >= self.ema_gap_min
        if self.adx_min:
            active &= dataframe["adx"] >= self.adx_min
        if self.atr_min:
            active &= dataframe["atr_pct"] >= self.atr_min
        if self.volume_mult:
            active &= dataframe["volume"] >= dataframe["volume_sma20"] * self.volume_mult
        return active

    def _confirmed_side(self, dataframe: DataFrame, side: int) -> DataFrame:
        condition = dataframe["ema_side"] == side
        candles = max(1, int(self.confirm_candles))
        if candles == 1:
            return condition
        confirmed = condition
        for offset in range(1, candles):
            confirmed &= condition.shift(offset).fillna(False)
        return confirmed

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        active = self._entry_filter(dataframe)
        long_condition = active & self._confirmed_side(dataframe, 1)
        short_condition = active & self._confirmed_side(dataframe, -1)
        if self.slope_window:
            long_condition &= dataframe["ema25_slope"] >= self.slope_min
            short_condition &= dataframe["ema25_slope"] <= -self.slope_min
        if self.trend_filter:
            long_condition &= dataframe["close"] > dataframe["ema200"]
            short_condition &= dataframe["close"] < dataframe["ema200"]
        dataframe.loc[long_condition, "enter_long"] = 1
        dataframe.loc[short_condition, "enter_short"] = 1
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[dataframe["ema7"] < dataframe["ema25"], "exit_long"] = 1
        dataframe.loc[dataframe["ema7"] > dataframe["ema25"], "exit_short"] = 1
        return dataframe


class Strategy1BaselineExact(Strategy1Base):
    pass


class Strategy1NetStop15(Strategy1Base):
    # Approximate net -15% after two 0.05% taker fees at 50x.
    stoploss = -0.10


class Strategy1Gap04(Strategy1Base):
    ema_gap_min = 0.0004


class Strategy1Gap08(Strategy1Base):
    ema_gap_min = 0.0008


class Strategy1Slope25(Strategy1Base):
    slope_window = 5
    slope_min = 0.00005


class Strategy1ADX25(Strategy1Base):
    adx_min = 25.0


class Strategy1ADX35(Strategy1Base):
    adx_min = 35.0


class Strategy1ATR08(Strategy1Base):
    atr_min = 0.0008


class Strategy1Volume125(Strategy1Base):
    volume_mult = 1.25


class Strategy1Confirm3(Strategy1Base):
    confirm_candles = 3


class Strategy1Trend200(Strategy1Base):
    startup_candle_count = 220
    trend_filter = True


class Strategy1Gap04ADX20(Strategy1Base):
    ema_gap_min = 0.0004
    adx_min = 20.0


class Strategy1Gap04Confirm3(Strategy1Base):
    ema_gap_min = 0.0004
    confirm_candles = 3


class Strategy1Gap04Slope25(Strategy1Base):
    ema_gap_min = 0.0004
    slope_window = 5
    slope_min = 0.00005


class Strategy1Trend20Fixed(IStrategy):
    """Filtered EMA entry with a fixed 50 USDT isolated-margin stake."""

    INTERFACE_VERSION = 3
    can_short = True
    timeframe = "1m"
    startup_candle_count = 220
    process_only_new_candles = True

    # Freqtrade futures ROI already includes leverage and trading fees.
    minimal_roi = {"0": 0.10}
    # The normal stop is only a disaster fallback. custom_exit enforces the
    # requested -30% on the whole trade after every DCA average-price change.
    stoploss = -0.90
    # Required for custom_exit; populate_exit_trend deliberately emits no exits.
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    use_custom_stoploss = False

    position_adjustment_enable = False
    max_entry_position_adjustment = 0

    initial_stake = 50.0
    project_capital = 1000.0

    order_types = {
        "entry": "market",
        "exit": "market",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    def leverage(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_leverage: float,
        max_leverage: float,
        entry_tag,
        side: str,
        **kwargs,
    ) -> float:
        return min(20.0, max_leverage)

    def custom_stake_amount(
        self,
        pair: str,
        current_time,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag,
        side: str,
        **kwargs,
    ) -> float:
        stake = min(self.initial_stake, max_stake)
        if min_stake is not None and stake < min_stake:
            return min_stake if min_stake <= max_stake else 0.0
        return stake

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        # 30% of a 1000 USDT project is 300 USDT, not 1000 USDT.
        if current_profit <= -0.30:
            return "net_roi_stop_30"
        if trade.calc_profit(current_rate) <= -(self.project_capital * 0.30):
            return "project_loss_30pct"
        return None

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema7"] = ta.EMA(dataframe, timeperiod=7)
        dataframe["ema25"] = ta.EMA(dataframe, timeperiod=25)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["ema_gap"] = (dataframe["ema7"] - dataframe["ema25"]).abs() / dataframe["close"]
        dataframe["ema25_slope"] = dataframe["ema25"].pct_change(5)
        return dataframe

    @staticmethod
    def _confirmed_once(condition: DataFrame, candles: int = 3) -> DataFrame:
        confirmed = condition.copy()
        for offset in range(1, candles):
            confirmed &= condition.shift(offset).fillna(False)
        return confirmed & ~confirmed.shift(1).fillna(False)

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        active = (
            (dataframe["volume"] > 0)
            & (dataframe["ema_gap"] >= 0.0008)
            & (dataframe["adx"] >= 25.0)
            & (dataframe["atr_pct"] >= 0.0007)
        )
        long_setup = (
            active
            & (dataframe["ema7"] > dataframe["ema25"])
            & (dataframe["ema25_slope"] > 0)
            & (dataframe["close"] > dataframe["ema200"])
        )
        short_setup = (
            active
            & (dataframe["ema7"] < dataframe["ema25"])
            & (dataframe["ema25_slope"] < 0)
            & (dataframe["close"] < dataframe["ema200"])
        )
        dataframe.loc[self._confirmed_once(long_setup), ["enter_long", "enter_tag"]] = (1, "ema_trend_long")
        dataframe.loc[self._confirmed_once(short_setup), ["enter_short", "enter_tag"]] = (1, "ema_trend_short")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_short"] = 0
        return dataframe


class Strategy1Martingale20(Strategy1Trend20Fixed):
    """50 + 100 + 200 + 400 + 250 USDT DCA ladder, capped at 1000."""

    position_adjustment_enable = True
    max_entry_position_adjustment = 4
    dca_stakes = (100.0, 200.0, 400.0, 250.0)
    dca_trigger_roi = -0.20
    dca_min_interval = timedelta(minutes=3)

    def adjust_trade_position(
        self,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ):
        entry_count = trade.nr_of_successful_entries
        if entry_count >= 1 + len(self.dca_stakes):
            return None
        if current_profit > self.dca_trigger_roi:
            return None
        if current_time - trade.date_last_filled_utc < self.dca_min_interval:
            return None

        remaining = max(0.0, self.project_capital - float(trade.stake_amount))
        stake = min(self.dca_stakes[entry_count - 1], remaining, max_stake)
        if stake <= 0:
            return None
        if min_stake is not None and stake < min_stake:
            return None
        return stake, f"dca_{entry_count}"


class Strategy1MartingaleOneAdd(Strategy1Martingale20):
    """Conservative ablation: one 100 USDT add, 150 USDT total margin."""

    max_entry_position_adjustment = 1
    dca_stakes = (100.0,)


class Strategy1MartingaleTrendGuard(Strategy1Martingale20):
    """Only averages while the original trend is valid; exits on a strong flip."""

    dca_min_interval = timedelta(minutes=15)

    def _recent_trend(self, pair: str, is_short: bool, candles: int = 3) -> bool:
        if self.dp is None:
            return False
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or len(dataframe) < candles:
            return False
        recent = dataframe.tail(candles)
        if is_short:
            condition = (
                (recent["ema7"] < recent["ema25"])
                & (recent["ema25_slope"] < 0)
                & (recent["close"] < recent["ema200"])
                & (recent["adx"] >= 25.0)
            )
        else:
            condition = (
                (recent["ema7"] > recent["ema25"])
                & (recent["ema25_slope"] > 0)
                & (recent["close"] > recent["ema200"])
                & (recent["adx"] >= 25.0)
            )
        return bool(condition.all())

    def adjust_trade_position(self, trade, *args, **kwargs):
        if not self._recent_trend(trade.pair, trade.is_short):
            return None
        return super().adjust_trade_position(trade, *args, **kwargs)

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        risk_exit = super().custom_exit(
            pair,
            trade,
            current_time,
            current_rate,
            current_profit,
            **kwargs,
        )
        if risk_exit:
            return risk_exit
        if current_time - trade.open_date_utc < timedelta(minutes=15):
            return None
        if self._recent_trend(pair, not trade.is_short):
            return "trend_invalidated"
        return None


class Strategy1MTFPullbackBase(Strategy1Martingale20):
    """Multi-timeframe trend plus 1m pullback entry with confirmed DCA."""

    startup_candle_count = 240
    minimal_roi = {"0": 0.12}
    stop_roi = -0.25
    dca_trigger_roi = -0.20
    dca_min_interval = timedelta(minutes=15)

    @informative("5m")
    def populate_indicators_5m(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema7"] = ta.EMA(dataframe, timeperiod=7)
        dataframe["ema25"] = ta.EMA(dataframe, timeperiod=25)
        dataframe["ema100"] = ta.EMA(dataframe, timeperiod=100)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["ema25_slope"] = dataframe["ema25"].pct_change(3)
        dataframe["adx_delta"] = dataframe["adx"] - dataframe["adx"].shift(3)
        dataframe["trend_long"] = (
            (dataframe["ema7"] > dataframe["ema25"])
            & (dataframe["ema25"] > dataframe["ema100"])
            & (dataframe["ema25_slope"] > 0)
            & (dataframe["adx"] >= 20.0)
        )
        dataframe["trend_short"] = (
            (dataframe["ema7"] < dataframe["ema25"])
            & (dataframe["ema25"] < dataframe["ema100"])
            & (dataframe["ema25_slope"] < 0)
            & (dataframe["adx"] >= 20.0)
        )
        long_groups = (dataframe["trend_long"] != dataframe["trend_long"].shift()).cumsum()
        short_groups = (dataframe["trend_short"] != dataframe["trend_short"].shift()).cumsum()
        dataframe["trend_long_age"] = dataframe["trend_long"].groupby(long_groups).cumcount() + 1
        dataframe["trend_short_age"] = dataframe["trend_short"].groupby(short_groups).cumcount() + 1
        dataframe.loc[~dataframe["trend_long"], "trend_long_age"] = 0
        dataframe.loc[~dataframe["trend_short"], "trend_short_age"] = 0
        return dataframe

    @informative("15m")
    def populate_indicators_15m(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema60"] = ta.EMA(dataframe, timeperiod=60)
        dataframe["adx"] = ta.ADX(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["ema20_slope"] = dataframe["ema20"].pct_change(3)
        dataframe["trend_long"] = (
            (dataframe["close"] > dataframe["ema60"])
            & (dataframe["ema20"] > dataframe["ema60"])
            & (dataframe["ema20_slope"] > 0)
            & (dataframe["adx"] >= 18.0)
        )
        dataframe["trend_short"] = (
            (dataframe["close"] < dataframe["ema60"])
            & (dataframe["ema20"] < dataframe["ema60"])
            & (dataframe["ema20_slope"] < 0)
            & (dataframe["adx"] >= 18.0)
        )
        long_groups = (dataframe["trend_long"] != dataframe["trend_long"].shift()).cumsum()
        short_groups = (dataframe["trend_short"] != dataframe["trend_short"].shift()).cumsum()
        dataframe["trend_long_age"] = dataframe["trend_long"].groupby(long_groups).cumcount() + 1
        dataframe["trend_short_age"] = dataframe["trend_short"].groupby(short_groups).cumcount() + 1
        dataframe.loc[~dataframe["trend_long"], "trend_long_age"] = 0
        dataframe.loc[~dataframe["trend_short"], "trend_short_age"] = 0
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema7"] = ta.EMA(dataframe, timeperiod=7)
        dataframe["ema25"] = ta.EMA(dataframe, timeperiod=25)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["atr_pct"] = dataframe["atr"] / dataframe["close"]
        dataframe["volume_sma20"] = dataframe["volume"].rolling(20).mean()

        recent_low = dataframe["low"].rolling(4).min()
        recent_high = dataframe["high"].rolling(4).max()
        long_touch = (
            (recent_low <= dataframe["ema25"] + dataframe["atr"] * 0.20)
            & (recent_low >= dataframe["ema25"] - dataframe["atr"] * 1.20)
        )
        short_touch = (
            (recent_high >= dataframe["ema25"] - dataframe["atr"] * 0.20)
            & (recent_high <= dataframe["ema25"] + dataframe["atr"] * 1.20)
        )
        bullish_reclaim = (
            (dataframe["close"] > dataframe["ema7"])
            & (dataframe["close"] > dataframe["open"])
            & (dataframe["close"] > dataframe["close"].shift(1))
            & ((dataframe["close"] - dataframe["open"]) <= dataframe["atr"] * 1.20)
        )
        bearish_reclaim = (
            (dataframe["close"] < dataframe["ema7"])
            & (dataframe["close"] < dataframe["open"])
            & (dataframe["close"] < dataframe["close"].shift(1))
            & ((dataframe["open"] - dataframe["close"]) <= dataframe["atr"] * 1.20)
        )
        context_long = dataframe["trend_long_5m"] & dataframe["trend_long_15m"]
        context_short = dataframe["trend_short_5m"] & dataframe["trend_short_15m"]
        liquid = (
            (dataframe["volume"] > 0)
            & (dataframe["volume"] >= dataframe["volume_sma20"] * 0.70)
            & (dataframe["atr_pct"] >= 0.00035)
        )
        dataframe["entry_long_setup"] = context_long & long_touch & bullish_reclaim & liquid
        dataframe["entry_short_setup"] = context_short & short_touch & bearish_reclaim & liquid
        dataframe["dca_long_confirm"] = (
            context_long
            & bullish_reclaim
            & (dataframe["low"] <= dataframe["ema25"] + dataframe["atr"] * 0.50)
        )
        dataframe["dca_short_confirm"] = (
            context_short
            & bearish_reclaim
            & (dataframe["high"] >= dataframe["ema25"] - dataframe["atr"] * 0.50)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        enter_long = dataframe["entry_long_setup"] & ~dataframe["entry_long_setup"].shift(1).fillna(False)
        enter_short = dataframe["entry_short_setup"] & ~dataframe["entry_short_setup"].shift(1).fillna(False)
        dataframe.loc[enter_long, ["enter_long", "enter_tag"]] = (1, "mtf_pullback_long")
        dataframe.loc[enter_short, ["enter_short", "enter_tag"]] = (1, "mtf_pullback_short")
        return dataframe

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        if current_profit <= self.stop_roi:
            return f"net_roi_stop_{abs(int(self.stop_roi * 100))}"
        if trade.calc_profit(current_rate) <= -(self.project_capital * abs(self.stop_roi)):
            return "project_loss_limit"
        return None

    def adjust_trade_position(
        self,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ):
        entry_count = trade.nr_of_successful_entries
        if entry_count >= 1 + len(self.dca_stakes):
            return None
        if current_profit > self.dca_trigger_roi:
            return None
        if current_time - trade.date_last_filled_utc < self.dca_min_interval:
            return None
        if self.dp is None:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        confirmation_column = "dca_short_confirm" if trade.is_short else "dca_long_confirm"
        if not bool(dataframe.iloc[-1].get(confirmation_column, False)):
            return None

        remaining = max(0.0, self.project_capital - float(trade.stake_amount))
        stake = min(self.dca_stakes[entry_count - 1], remaining, max_stake)
        if stake <= 0 or (min_stake is not None and stake < min_stake):
            return None
        return stake, f"confirmed_dca_{entry_count}"


class Strategy1MTF12Stop25(Strategy1MTFPullbackBase):
    pass


class Strategy1MTF15Stop25(Strategy1MTFPullbackBase):
    minimal_roi = {"0": 0.15}


class Strategy1MTF12Stop20(Strategy1MTFPullbackBase):
    stop_roi = -0.20
    dca_trigger_roi = -0.16


class Strategy1MTF12Stop25TwoAdds(Strategy1MTFPullbackBase):
    max_entry_position_adjustment = 2
    dca_stakes = (100.0, 200.0)


class Strategy1MTF12Stop25OneAdd(Strategy1MTFPullbackBase):
    max_entry_position_adjustment = 1
    dca_stakes = (100.0,)


class Strategy1MTF12Stop25EarlyDCA(Strategy1MTFPullbackBase):
    dca_trigger_roi = -0.10


class Strategy1MTF12Stop25EarlyTwoAdds(Strategy1MTFPullbackBase):
    max_entry_position_adjustment = 2
    dca_stakes = (100.0, 200.0)
    dca_trigger_roi = -0.12


class Strategy1MTF12Stop30EarlyTwoAdds(Strategy1MTF12Stop25EarlyTwoAdds):
    stop_roi = -0.30


class Strategy1MTF12Stop25Fixed(Strategy1MTFPullbackBase):
    position_adjustment_enable = False
    max_entry_position_adjustment = 0
    dca_stakes = ()


class Strategy1StrictReclaimBase(Strategy1MTFPullbackBase):
    """Enter only on an actual EMA7 reclaim inside a strong MTF trend."""

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        long_reclaim = (
            (dataframe["close"].shift(1) <= dataframe["ema7"].shift(1))
            & (dataframe["close"] > dataframe["ema7"])
            & (dataframe["close"] > dataframe["open"])
        )
        short_reclaim = (
            (dataframe["close"].shift(1) >= dataframe["ema7"].shift(1))
            & (dataframe["close"] < dataframe["ema7"])
            & (dataframe["close"] < dataframe["open"])
        )
        long_mtf_strength = (
            dataframe["trend_long_5m"]
            & dataframe["trend_long_15m"]
            & (dataframe["adx_5m"] >= 25.0)
            & (dataframe["adx_15m"] >= 20.0)
            & ((dataframe["ema7_5m"] - dataframe["ema25_5m"]) / dataframe["close_5m"] >= 0.0008)
            & ((dataframe["ema20_15m"] - dataframe["ema60_15m"]) / dataframe["close_15m"] >= 0.0015)
        )
        short_mtf_strength = (
            dataframe["trend_short_5m"]
            & dataframe["trend_short_15m"]
            & (dataframe["adx_5m"] >= 25.0)
            & (dataframe["adx_15m"] >= 20.0)
            & ((dataframe["ema25_5m"] - dataframe["ema7_5m"]) / dataframe["close_5m"] >= 0.0008)
            & ((dataframe["ema60_15m"] - dataframe["ema20_15m"]) / dataframe["close_15m"] >= 0.0015)
        )
        no_long_chase = (dataframe["close"] - dataframe["ema25"]) <= dataframe["atr"] * 0.80
        no_short_chase = (dataframe["ema25"] - dataframe["close"]) <= dataframe["atr"] * 0.80
        liquid = dataframe["volume"] >= dataframe["volume_sma20"] * 0.80
        dataframe["entry_long_setup"] = long_mtf_strength & long_reclaim & no_long_chase & liquid
        dataframe["entry_short_setup"] = short_mtf_strength & short_reclaim & no_short_chase & liquid
        dataframe["dca_long_confirm"] = long_mtf_strength & long_reclaim & no_long_chase
        dataframe["dca_short_confirm"] = short_mtf_strength & short_reclaim & no_short_chase
        return dataframe

    def _opposite_mtf_trend(self, pair: str, is_short: bool) -> bool:
        if self.dp is None:
            return False
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return False
        row = dataframe.iloc[-1]
        column = "trend_long_15m" if is_short else "trend_short_15m"
        return bool(row.get(column, False))


class Strategy1Strict12Stop25Fixed(Strategy1StrictReclaimBase):
    position_adjustment_enable = False
    max_entry_position_adjustment = 0
    dca_stakes = ()


class Strategy1Strict12Stop25OneAdd(Strategy1StrictReclaimBase):
    max_entry_position_adjustment = 1
    dca_stakes = (100.0,)
    dca_trigger_roi = -0.10


class Strategy1Strict12Stop25TwoAdds(Strategy1StrictReclaimBase):
    max_entry_position_adjustment = 2
    dca_stakes = (100.0, 200.0)
    dca_trigger_roi = -0.10


class Strategy1Strict15Stop25Fixed(Strategy1Strict12Stop25Fixed):
    minimal_roi = {"0": 0.15}


class Strategy1Strict12Stop20Fixed(Strategy1Strict12Stop25Fixed):
    stop_roi = -0.20


class Strategy1Strict12Stop25TrendAbort(Strategy1Strict12Stop25OneAdd):
    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        risk_exit = super().custom_exit(
            pair,
            trade,
            current_time,
            current_rate,
            current_profit,
            **kwargs,
        )
        if risk_exit:
            return risk_exit
        if (
            current_profit < -0.05
            and current_time - trade.open_date_utc >= timedelta(minutes=30)
            and self._opposite_mtf_trend(pair, trade.is_short)
        ):
            return "opposite_15m_trend"
        return None


class Strategy1StrictProtectBase(Strategy1Strict12Stop25Fixed):
    protect_trigger = 0.06
    protect_floor = 0.00

    @staticmethod
    def _peak_profit(trade) -> float:
        best_rate = trade.min_rate if trade.is_short else trade.max_rate
        if not best_rate:
            return 0.0
        return float(trade.calc_profit_ratio(best_rate))

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        risk_exit = super().custom_exit(
            pair,
            trade,
            current_time,
            current_rate,
            current_profit,
            **kwargs,
        )
        if risk_exit:
            return risk_exit
        if self._peak_profit(trade) >= self.protect_trigger and current_profit <= self.protect_floor:
            return "profit_protection"
        return None


class Strategy1StrictProtect6BE(Strategy1StrictProtectBase):
    pass


class Strategy1StrictProtect8Lock3(Strategy1StrictProtectBase):
    protect_trigger = 0.08
    protect_floor = 0.03


class Strategy1StrictProtect6BEOneAdd(Strategy1StrictProtect6BE):
    position_adjustment_enable = True
    max_entry_position_adjustment = 1
    dca_stakes = (100.0,)
    dca_trigger_roi = -0.10


class Strategy1StrictTimeROI(Strategy1Strict12Stop25Fixed):
    minimal_roi = {
        "0": 0.15,
        "180": 0.12,
        "360": 0.08,
        "720": 0.04,
    }


class Strategy1StrictTimeROIProtect(Strategy1StrictProtect6BE):
    minimal_roi = {
        "0": 0.15,
        "180": 0.12,
        "360": 0.08,
        "720": 0.04,
    }


class Strategy1QualityBase(Strategy1StrictReclaimBase):
    max_trend_age_15m = 32
    max_distance_5m_atr = 0.80
    max_distance_15m_atr = 1.50
    require_adx_rising = True

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        near_5m_ema = (
            (dataframe["close_5m"] - dataframe["ema7_5m"]).abs()
            <= dataframe["atr_5m"] * self.max_distance_5m_atr
        )
        not_extended_15m = (
            (dataframe["close_15m"] - dataframe["ema20_15m"]).abs()
            <= dataframe["atr_15m"] * self.max_distance_15m_atr
        )
        long_age_ok = dataframe["trend_long_age_15m"].between(1, self.max_trend_age_15m)
        short_age_ok = dataframe["trend_short_age_15m"].between(1, self.max_trend_age_15m)
        adx_ok = dataframe["adx_delta_5m"] > 0 if self.require_adx_rising else True
        dataframe["entry_long_setup"] &= near_5m_ema & not_extended_15m & long_age_ok & adx_ok
        dataframe["entry_short_setup"] &= near_5m_ema & not_extended_15m & short_age_ok & adx_ok
        dataframe["dca_long_confirm"] &= near_5m_ema & not_extended_15m & long_age_ok & adx_ok
        dataframe["dca_short_confirm"] &= near_5m_ema & not_extended_15m & short_age_ok & adx_ok
        return dataframe


class Strategy1QualityAge16Fixed(Strategy1QualityBase):
    position_adjustment_enable = False
    max_entry_position_adjustment = 0
    dca_stakes = ()
    max_trend_age_15m = 16


class Strategy1QualityAge32Fixed(Strategy1QualityAge16Fixed):
    max_trend_age_15m = 32


class Strategy1QualityAge64Fixed(Strategy1QualityAge16Fixed):
    max_trend_age_15m = 64


class Strategy1QualityAge32OneAdd(Strategy1QualityBase):
    max_entry_position_adjustment = 1
    dca_stakes = (100.0,)
    dca_trigger_roi = -0.08


class Strategy1QualityAge32TP15(Strategy1QualityAge32Fixed):
    minimal_roi = {"0": 0.15}


class Strategy1QualityAge32NoAdxRise(Strategy1QualityAge32Fixed):
    require_adx_rising = False


class Strategy1QualityAge16NoAdxRise(Strategy1QualityAge16Fixed):
    require_adx_rising = False


class Strategy1QualityAge64NoAdxRise(Strategy1QualityAge64Fixed):
    require_adx_rising = False


class Strategy1QualityAge32NoAdxTP15(Strategy1QualityAge32NoAdxRise):
    minimal_roi = {"0": 0.15}


class Strategy1QualityAge32NoAdxStop20(Strategy1QualityAge32NoAdxRise):
    stop_roi = -0.20


class Strategy1QualityAge32NoAdxOneAdd(Strategy1QualityBase):
    require_adx_rising = False
    max_entry_position_adjustment = 1
    dca_stakes = (100.0,)
    dca_trigger_roi = -0.08


class Strategy1HourlyFilterBase(Strategy1QualityAge16NoAdxRise):
    hourly_mode = "alignment"

    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema60"] = ta.EMA(dataframe, timeperiod=60)
        dataframe["ema20_slope"] = dataframe["ema20"].pct_change(2)
        dataframe["trend_long"] = (
            (dataframe["close"] > dataframe["ema60"])
            & (dataframe["ema20"] > dataframe["ema60"])
        )
        dataframe["trend_short"] = (
            (dataframe["close"] < dataframe["ema60"])
            & (dataframe["ema20"] < dataframe["ema60"])
        )
        dataframe["slope_long"] = dataframe["trend_long"] & (dataframe["ema20_slope"] > 0)
        dataframe["slope_short"] = dataframe["trend_short"] & (dataframe["ema20_slope"] < 0)
        dataframe["price_long"] = dataframe["close"] > dataframe["ema60"]
        dataframe["price_short"] = dataframe["close"] < dataframe["ema60"]
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        if self.hourly_mode == "slope":
            long_hourly = dataframe["slope_long_1h"]
            short_hourly = dataframe["slope_short_1h"]
        elif self.hourly_mode == "price":
            long_hourly = dataframe["price_long_1h"]
            short_hourly = dataframe["price_short_1h"]
        else:
            long_hourly = dataframe["trend_long_1h"]
            short_hourly = dataframe["trend_short_1h"]
        dataframe["entry_long_setup"] &= long_hourly
        dataframe["entry_short_setup"] &= short_hourly
        dataframe["dca_long_confirm"] &= long_hourly
        dataframe["dca_short_confirm"] &= short_hourly
        return dataframe


class Strategy1HourlyAlignment(Strategy1HourlyFilterBase):
    pass


class Strategy1HourlySlope(Strategy1HourlyFilterBase):
    hourly_mode = "slope"


class Strategy1HourlyPrice(Strategy1HourlyFilterBase):
    hourly_mode = "price"


class Strategy1HourlyAlignmentOneAdd(Strategy1HourlyAlignment):
    position_adjustment_enable = True
    max_entry_position_adjustment = 1
    dca_stakes = (100.0,)
    dca_trigger_roi = -0.08


class Strategy1HourlyAlignmentTP15(Strategy1HourlyAlignment):
    minimal_roi = {"0": 0.15}


class Strategy1HourlyAlignmentStop20(Strategy1HourlyAlignment):
    stop_roi = -0.20


class Strategy1TriggerBase(Strategy1QualityAge16NoAdxRise):
    volume_multiplier = 0.80
    close_location_min = 0.0
    body_atr_min = 0.0
    require_breakout = False

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        candle_range = (dataframe["high"] - dataframe["low"]).clip(lower=1e-12)
        body = (dataframe["close"] - dataframe["open"]).abs()
        long_location = (dataframe["close"] - dataframe["low"]) / candle_range
        short_location = (dataframe["high"] - dataframe["close"]) / candle_range
        volume_ok = dataframe["volume"] >= dataframe["volume_sma20"] * self.volume_multiplier
        body_ok = body >= dataframe["atr"] * self.body_atr_min
        long_quality = long_location >= self.close_location_min
        short_quality = short_location >= self.close_location_min
        if self.require_breakout:
            long_quality &= dataframe["close"] > dataframe["high"].shift(1)
            short_quality &= dataframe["close"] < dataframe["low"].shift(1)
        dataframe["entry_long_setup"] &= volume_ok & body_ok & long_quality
        dataframe["entry_short_setup"] &= volume_ok & body_ok & short_quality
        dataframe["dca_long_confirm"] &= volume_ok & body_ok & long_quality
        dataframe["dca_short_confirm"] &= volume_ok & body_ok & short_quality
        return dataframe


class Strategy1TriggerVolume100(Strategy1TriggerBase):
    volume_multiplier = 1.00


class Strategy1TriggerVolume125(Strategy1TriggerBase):
    volume_multiplier = 1.25


class Strategy1TriggerClose70(Strategy1TriggerBase):
    close_location_min = 0.70


class Strategy1TriggerBody20(Strategy1TriggerBase):
    body_atr_min = 0.20


class Strategy1TriggerBreakout(Strategy1TriggerBase):
    require_breakout = True


class Strategy1TriggerClose70Body20(Strategy1TriggerBase):
    close_location_min = 0.70
    body_atr_min = 0.20


class Strategy1TriggerVolume100TP10(Strategy1TriggerVolume100):
    minimal_roi = {"0": 0.10}


class Strategy1TriggerVolume100Stop20(Strategy1TriggerVolume100):
    stop_roi = -0.20


class Strategy1TriggerVolume100TP10Stop20(Strategy1TriggerVolume100TP10):
    stop_roi = -0.20


class Strategy1TriggerVolume100TP15(Strategy1TriggerVolume100):
    minimal_roi = {"0": 0.15}


class Strategy1TriggerVolume100Stop30(Strategy1TriggerVolume100):
    stop_roi = -0.30


class Strategy1TriggerVolume100DCA12(Strategy1TriggerVolume100):
    position_adjustment_enable = True
    max_entry_position_adjustment = 1
    dca_stakes = (100.0,)
    dca_trigger_roi = -0.12


class Strategy1TriggerVolume100DCA15(Strategy1TriggerVolume100DCA12):
    dca_trigger_roi = -0.15


class Strategy1TriggerVolume100DCA18(Strategy1TriggerVolume100DCA12):
    dca_trigger_roi = -0.18


class Strategy1ConfirmedDCA15Base(Strategy1TriggerVolume100TP15):
    position_adjustment_enable = True
    dca_min_interval = timedelta(minutes=30)
    dca_thresholds = (-0.15,)
    dca_stakes = (100.0,)
    max_entry_position_adjustment = 1

    def adjust_trade_position(
        self,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        min_stake: float | None,
        max_stake: float,
        current_entry_rate: float,
        current_exit_rate: float,
        current_entry_profit: float,
        current_exit_profit: float,
        **kwargs,
    ):
        entry_count = trade.nr_of_successful_entries
        index = entry_count - 1
        if index >= len(self.dca_stakes):
            return None
        if current_profit > self.dca_thresholds[index]:
            return None
        if current_time - trade.date_last_filled_utc < self.dca_min_interval:
            return None
        if self.dp is None:
            return None
        dataframe, _ = self.dp.get_analyzed_dataframe(trade.pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return None
        row = dataframe.iloc[-1]
        if trade.is_short:
            confirmed = (
                bool(row.get("trend_short_5m", False))
                and bool(row.get("trend_short_15m", False))
                and 1 <= float(row.get("trend_short_age_15m", 0)) <= 16
                and float(row["close"]) < float(row["open"])
                and float(row["volume"]) >= float(row["volume_sma20"])
            )
        else:
            confirmed = (
                bool(row.get("trend_long_5m", False))
                and bool(row.get("trend_long_15m", False))
                and 1 <= float(row.get("trend_long_age_15m", 0)) <= 16
                and float(row["close"]) > float(row["open"])
                and float(row["volume"]) >= float(row["volume_sma20"])
            )
        if not confirmed:
            return None
        remaining = max(0.0, self.project_capital - float(trade.stake_amount))
        stake = min(self.dca_stakes[index], remaining, max_stake)
        if stake <= 0 or (min_stake is not None and stake < min_stake):
            return None
        return stake, f"mtf_dca_{entry_count}"


class Strategy1ConfirmedDCA10(Strategy1ConfirmedDCA15Base):
    dca_thresholds = (-0.10,)


class Strategy1ConfirmedDCA15(Strategy1ConfirmedDCA15Base):
    pass


class Strategy1ConfirmedDCA18(Strategy1ConfirmedDCA15Base):
    dca_thresholds = (-0.18,)


class Strategy1ConfirmedDCATwoAdds(Strategy1ConfirmedDCA15Base):
    dca_thresholds = (-0.10, -0.18)
    dca_stakes = (100.0, 200.0)
    max_entry_position_adjustment = 2


class Strategy1ConfirmedDCAFull(Strategy1ConfirmedDCA15Base):
    dca_thresholds = (-0.08, -0.13, -0.18, -0.22)
    dca_stakes = (100.0, 200.0, 400.0, 250.0)
    max_entry_position_adjustment = 4


class Strategy1AdaptiveROIBase(Strategy1TriggerVolume100TP15):
    use_custom_roi = True
    roi_atr_multiplier = 1.5
    roi_min = 0.10
    roi_max = 0.15

    def custom_roi(
        self,
        pair: str,
        trade,
        current_time,
        trade_duration: int,
        entry_tag,
        side: str,
        **kwargs,
    ) -> float:
        if self.dp is None:
            return self.roi_max
        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if dataframe is None or dataframe.empty:
            return self.roi_max
        row = dataframe.iloc[-1]
        close = float(row.get("close_15m", 0))
        atr = float(row.get("atr_15m", 0))
        if close <= 0 or atr <= 0:
            return self.roi_max
        target = atr / close * float(trade.leverage) * self.roi_atr_multiplier
        return min(self.roi_max, max(self.roi_min, target))


class Strategy1AdaptiveROI100(Strategy1AdaptiveROIBase):
    roi_atr_multiplier = 1.0


class Strategy1AdaptiveROI150(Strategy1AdaptiveROIBase):
    pass


class Strategy1AdaptiveROI200(Strategy1AdaptiveROIBase):
    roi_atr_multiplier = 2.0


class Strategy1NativeStop25(Strategy1TriggerVolume100TP15):
    """Use Freqtrade's intrabar futures stop instead of a candle-close exit."""

    stoploss = -0.25


class Strategy1NativeStop20(Strategy1NativeStop25):
    stoploss = -0.20


class Strategy1NativeStop30(Strategy1NativeStop25):
    stoploss = -0.30
    stop_roi = -0.30


class Strategy1NativeStop25DCA15(Strategy1ConfirmedDCA15):
    stoploss = -0.25


class Strategy1NativeStop25LongVolume125(Strategy1NativeStop25):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= dataframe["volume"] >= dataframe["volume_sma20"] * 1.25
        return dataframe


class Strategy1NativeStop25LongAge8(Strategy1NativeStop25):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= dataframe["trend_long_age_15m"].between(1, 8)
        return dataframe


class Strategy1NativeStop25LongADX(Strategy1NativeStop25):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= (
            (dataframe["adx_5m"] >= 30.0)
            & (dataframe["adx_15m"] >= 25.0)
        )
        return dataframe


class Strategy1NativeStop22LongADX(Strategy1NativeStop25LongADX):
    stoploss = -0.22


class Strategy1NativeStop23LongADX(Strategy1NativeStop25LongADX):
    stoploss = -0.23


class Strategy1NativeStop24LongADX(Strategy1NativeStop25LongADX):
    stoploss = -0.24


class Strategy1PureNativeStop23LongADX(Strategy1NativeStop23LongADX):
    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        return None


class Strategy1PureNativeStop25LongADX(Strategy1PureNativeStop23LongADX):
    stoploss = -0.25


class Strategy1NativeStop25LongADX5m(Strategy1NativeStop25):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= dataframe["adx_5m"] >= 30.0
        return dataframe


class Strategy1NativeStop25LongADX15m(Strategy1NativeStop25):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= dataframe["adx_15m"] >= 25.0
        return dataframe


class Strategy1NativeStop25LongADX35(Strategy1NativeStop25):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= (
            (dataframe["adx_5m"] >= 35.0)
            & (dataframe["adx_15m"] >= 25.0)
        )
        return dataframe


class Strategy1NativeStop25LongADXDCA15(Strategy1NativeStop25DCA15):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= (
            (dataframe["adx_5m"] >= 30.0)
            & (dataframe["adx_15m"] >= 25.0)
        )
        return dataframe


class Strategy1PairROIBase(Strategy1NativeStop25LongADX):
    use_custom_roi = True
    btc_roi = 0.12
    bnb_roi = 0.12

    def custom_roi(
        self,
        pair: str,
        trade,
        current_time,
        trade_duration: int,
        entry_tag,
        side: str,
        **kwargs,
    ) -> float:
        if pair.startswith("BTC/"):
            return self.btc_roi
        if pair.startswith("BNB/"):
            return self.bnb_roi
        return 0.15


class Strategy1PairROI10(Strategy1PairROIBase):
    btc_roi = 0.10
    bnb_roi = 0.10


class Strategy1PairROI12(Strategy1PairROIBase):
    pass


class Strategy1PairROIBTC10BNB12(Strategy1PairROIBase):
    btc_roi = 0.10


class Strategy1PairROIBTC12BNB10(Strategy1PairROIBase):
    bnb_roi = 0.10


class Strategy1NativeStop25BothADX(Strategy1NativeStop25):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        strength = (dataframe["adx_5m"] >= 30.0) & (dataframe["adx_15m"] >= 25.0)
        dataframe["entry_long_setup"] &= strength
        dataframe["entry_short_setup"] &= strength
        return dataframe


class Strategy1NativeStop25ShortADX(Strategy1NativeStop25):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_short_setup"] &= (
            (dataframe["adx_5m"] >= 30.0)
            & (dataframe["adx_15m"] >= 25.0)
        )
        return dataframe


class Strategy1NativeStop25LongHourly(Strategy1NativeStop25):
    @informative("1h")
    def populate_indicators_1h(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema20"] = ta.EMA(dataframe, timeperiod=20)
        dataframe["ema60"] = ta.EMA(dataframe, timeperiod=60)
        dataframe["long_context"] = (
            (dataframe["close"] > dataframe["ema60"])
            & (dataframe["ema20"] > dataframe["ema60"])
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= dataframe["long_context_1h"]
        return dataframe


class Strategy1NativeStop25LongHourlyVolume125(Strategy1NativeStop25LongHourly):
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_indicators(dataframe, metadata)
        dataframe["entry_long_setup"] &= dataframe["volume"] >= dataframe["volume_sma20"] * 1.25
        return dataframe


class Strategy1NativeStop25TimeExitBase(Strategy1NativeStop25):
    max_loser_minutes = 720

    def custom_exit(
        self,
        pair: str,
        trade,
        current_time,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ):
        risk_exit = super().custom_exit(
            pair,
            trade,
            current_time,
            current_rate,
            current_profit,
            **kwargs,
        )
        if risk_exit:
            return risk_exit
        if (
            current_profit < 0
            and current_time - trade.open_date_utc >= timedelta(minutes=self.max_loser_minutes)
        ):
            return f"time_loss_{self.max_loser_minutes}m"
        return None


class Strategy1NativeStop25TimeExit6h(Strategy1NativeStop25TimeExitBase):
    max_loser_minutes = 360


class Strategy1NativeStop25TimeExit12h(Strategy1NativeStop25TimeExitBase):
    pass


class Strategy1NativeStop25TimeExit24h(Strategy1NativeStop25TimeExitBase):
    max_loser_minutes = 1440
