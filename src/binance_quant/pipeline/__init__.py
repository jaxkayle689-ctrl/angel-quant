"""重构架构 v1(snap-shot / contract / hardgate / registry / channels 五层)。

设计文档:output/ta-arch-20260924/stage3/智能交易工作台架构设计文档.docx

分层:
- snapshot   技术分析快照引擎(确定性计算,三通道共用地基)
- contract   订单票契约与五档评级
- hardgate   硬闸门(纯规则,不可关闭)
- registry   策略信号可插拔注册表
- ordergen   规则订单生成器(快速通道)
- llm        LLM provider 抽象与规则共识兜底
- debate     多空辩论/交易员/风控辩论/PM 终审
- memory     决策记忆日志与教训回注
- cards      策略卡片构建(深度通道产物)
- channels   快速/标准/深度三通道运行器
"""

__version__ = "0.1.0"
