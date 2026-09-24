"""Community strategies executed by the isolated Freqtrade runtime."""
from ..strategy_api import Strategy

SPECS = (
    ('community_genetic', 'GeneticEngineV1 · 因果修正版', 'GeneticEngineV1', 'AngelGenetic', (),
     '遗传条件组合；修正全样本归一化的未来数据泄漏。原作者收益不适用于此版本。'),
    ('community_trend', 'TrendFollowingV2 · 趋势跟随', 'TrendFollowingStrategyV2', 'AngelTrend', ('1h',),
     '5分钟 EMA 突破、OBV 与已收盘1小时趋势过滤。'),
    ('community_ewo', 'EwoMomentumV1 · 动量回调', 'EwoMomentumV1', 'AngelEwo', (),
     'EWO 与 RSI 筛选回调；使用原版 ROI、移动止损和止损规则。'),
)


class CommunityStrategy(Strategy):
    def __init__(self, spec):
        self.strategy_id, self.name, self.upstream, strategy_class, self.required_intervals, detail = spec
        self.description = detail + ' Binance 永续只做多适配，默认1倍；通过策略验证/模拟盘使用。尚未独立验证收益。'
        self.primary_interval = '5m'
        self.capabilities = ('long', 'portfolio', 'backtest', 'dry_run')
        self.automation_defaults = {'leverage': 1}
        self.backtest_adapter = {'engine': 'freqtrade', 'strategy_class': strategy_class, 'supports_dry_run': True,
                                 'supports_portfolio': True, 'default_leverage': 1}

    def generate(self, frame, parameters):
        raise ValueError('此策略由 Freqtrade 执行，请使用策略验证或模拟盘；不支持原生信号交易接口。')

    def normalized_parameters(self, values=None):
        if values:
            raise ValueError('社区策略当前使用固定指标参数；可在组合中设置首仓、预算和杠杆。')
        return {}

    def metadata(self):
        value = super().metadata()
        value.update(source_url='https://github.com/ceyhanmolla/freqtrade-strategies/blob/main/' + self.upstream + '.py',
                     validation_status='待独立验证', license_note='上游未声明许可证，仅供本地研究，重新分发前需确认许可。')
        return value
