# Chan Theory Complete | Chanlun Structure Pro

## 当前交付边界

用户已要求完成全部模块。当前各阶段已整合为 `Chan_Theory_Complete.pine`，包含 Core/完整模式、两级结构与信号、报警和 Debug。本文保留架构与阶段契约，实际实现细节和确认口径以 README.md 为准；官方编译与验收结果见 VALIDATION.md。

## 1. 需求分析与需要固定的定义

这是一套依赖图，而不是必须照文字顺序串起来的一条管道：

```text
RawBar → ChanBar → Fractal → Stroke ───────────→ 笔中枢 → L级走势/背驰/信号
                              └→ FeatureElement → Segment
                                                     └→ 线段中枢 → H级走势/背驰/信号
```

特征序列是线段确认的输入，不能在线段已经随意划定后才补画。
两层中枢共用同一算法，但输入分别是冻结笔、冻结线段。图表周期只作为元信息。
更高级递归需要明确“完成走势”的边界后再把它封装为结构输入，不能把中枢矩形直接当成高一级线段。

以下是工程约定，不声称是所有缠论流派的唯一标准：

1. **去包含的确认延迟**：原始 K 线收盘不等于处理后 K 线确认。只有下一根收盘原始 K 线与当前合并尾部不包含，旧尾部才冻结。上层只消费冻结事件。
2. **分型的确认延迟**：三根处理后 K 线全部冻结后，确认中间分型。在第三根还会被合并时，只能是候选。标记位置与确认时刻分开记录。
3. **初始化无方向**：开头可能全部包含，无法从历史确定涨跌。Phase 1 等待首对严格非包含的相邻原始 K 线，用这对 K 线启动；之前不确定的前缀计入 warmupSkipped，不参与分型。此选择舍弃部分起点信息，但不猜方向、不回填已确认结构。若窗口全是包含，输出“等待方向”，不是伪造一根已确认 K 线。
4. **严格笔/新笔**：都禁止两端三 K 分型共享处理后 K 线，中心序号差至少 3。严格笔采用中心距至少 4（两中心在内至少 5 根处理后 K 线）；新笔允许中心距 3，并要求原始映射跨度至少 5 根。用户最少 K 线只能加严。高低区间分离等额外限制单独记录，不用一个模式名称掩盖规则。
5. **冻结笔**：异类分型先形成候选笔；后续同类更极值替换候选终点；出现合格的反向笔候选后锁定上一笔。已冻结笔端点不被未来同类分型更改；若严格条件无法衔接，继续等待，不修复历史来增加信号。
6. **线段确认的两条要求**：无缺口分型可成为结束证据，但用户同时要求反向线段确认，因此默认严格模式还要求从候选端点开始有至少三笔、共同重叠的反向结构。缺口情况另外需要反向特征序列分型二次确认。宽松线段模式只放开“无缺口额外反向三笔等待”，不放开前三笔重叠、特征序列分型和缺口等待。
7. **特征元素方向**：上涨线段抽取下跌笔，元素本身 direction=down，但其包含合并方向依据特征区间序列的高低关系，不能直接取反向笔的方向。等值规则与普通分型共用比较器。
8. **中枢冻结**：三段交集固定 ZD/ZG 与来源 ID；延伸过程改变活动实例的 end/GG/DD。完成时生成冻结快照。把“已成立”与“生命周期已完成”区分开，不能宣称会延长的矩形完全不可变。
9. **中枢离开**：单根价格突破只改变预览；确认结构离开与第一次反向回抽才驱动三类点。进入中枢的回抽使候选失效，不能后续挑一个更好看的回抽补三买。
10. **背驰与一类点**：盘整背驰不自动等于趋势一买卖。同级两个中枢趋势、对应离开段价格极值与力度衰减是必要证据；只有反向结构确认才锁定一类点。
11. **走势类型**：两个同级已成立中枢满足后 ZD > 前 ZG 为上移，后 ZG < 前 ZD 为下移；有交叠不能直接判趋势。一个主要中枢只有在走势边界确认后才叫完成盘整；未完成时显示“盘整进行中/待定”。
12. **面积窗口**：默认比较完整对应结构段的同号柱面积。窗口上限导致一段统计不全时，标记 insufficientHistory 并拒绝确认背驰，不能悄悄用最后 N 根替代完整结构。

## 2. 数据结构

Pine 不使用继承；通过 `type StructureMeta` 组合公共元数据，或对高频 ChanBar 展平字段。所有实体都有：稳定 id、bar_index、timestamp、high、low、direction、confirmed、start_index、end_index、start_time、end_time、confirmed_at_index、confirmed_at_time。

`bar_index/timestamp` 表示结构锚点，范围字段表示覆盖的原始数据；极值来源另存，不能默认高点和低点来自同一根原始 K 线。未来公共 metadata 复制要深拷贝，避免 Pine 引用共享。

| 类型 | 专有字段和证据 |
|---|---|
| ChanBar | seq、high_index/time、low_index/time、raw_count、范围结束收盘时间；尾部可变，冻结对象只读 |
| Fractal | top/bottom、left/middle/right ChanBar ID、price、center_seq、候选/确认时刻 |
| Stroke | start/end Fractal ID、processed_count、raw_count、确认触发 Fractal ID、Momentum |
| FeatureElement | source Stroke ID 区间、极值对应笔 ID、merged_count、gap_before、所属候选 Segment ID |
| Segment | start/end Stroke ID、笔数、特征分型三元素 ID、has_gap、secondary_confirmation_id、end_reason |
| ZhongShu | level、seed 三个输入 ID、ZD/ZG、GG/DD、state、last_member_id、departure_id、retest_id |
| Move | level、同级中枢 ID 范围、trend/range/unknown、起止边界确认依据 |
| Momentum | 正/负柱面积、DIF 正/负极值、柱峰值、bar_count、price_change、统计是否完整 |
| Divergence | level、comparison 两个同向结构 ID、两个中枢 ID、指标比值、kind、state、reason |
| Signal | level、class 1/2/3、side、state、pivot_id、divergence_id、前置一类点 ID、key_price、retest_id、reason |
| Event | kind、source_id、event_index/time、level、去重键；报警使用 event 时间而非端点时间 |

方向枚举：unknown/up/down。生命周期枚举：candidate/confirmed/invalidated。
结构实体存数据；线、框、标签存 Renderer 的有界池，不混入确认算法。
数组位置不是结构身份：截断/环形覆盖后 ID 仍唯一，引用解析失败返回缺失而非读错数据。

## 3. 状态机

**包含引擎**

```text
等待首根 → 等待方向
等待方向 + 包含 → 替换临时种子，累加跳过数量
等待方向 + 非包含 → 冻结种子、建立方向、创建尾部
方向已知 + 包含 → 按方向修改尾部范围与来源映射
方向已知 + 非包含 → 冻结尾部、产生一次事件、更新方向、创建新尾部
```

关闭去包含时，原始 K 线一对一输出，也保留一根确认延迟，统一下游接口。
主状态只在 `barstate.isconfirmed` 前进；当前未收盘 K 线不参与 Phase 1。

**分型/笔**：分型 `candidate → confirmed/invalidated`；笔 `seekingStart → extendingCandidate → locked`。相同类型只替换活动端点。更晚不满足条件的分型不撤销冻结历史。

**线段**：`seekingTriple → extending → endCandidate → waitingReverse / waitingGapConfirmation → locked`。每加入一条冻结笔，先检查延伸极值，再更新反向特征序列。候选被原方向新极值破坏时，取消候选并重建活动尾部特征证据。不得从当前缺少足够证据推断历史线段已结束。候选区缓存达到上限时暂停该层，显示不足，不强制切段。

**中枢**：`forming → confirmed → extending → leavingUp/Down → retestingUp/Down`。回抽入枢回到 extending；回抽严格不入枢且反向结构冻结则形成三类点并 completed。活动中枢保留进入/离开证据，形成新中枢必须从旧中枢之后的有效结构起算，不能每三段重复建框。

**信号**：`Candidate → Confirmed` 或 `Candidate → Invalidated`；Confirmed 为终态，后续止损属于另一个事件。二类点用已确认一类点建立一次性追踪器：等待反弹 → 等待首次回撤 → 成功/失败；首次失败不能用第二次回撤冒充二类点。

## 4. 函数接口契约

下表是逻辑接口设计，具体代码将事件分发与共享状态合并在对应引擎方法中，文件结构见 README.md。

| 接口 | 输入 → 输出 / 副作用 |
|---|---|
| contains(aHi,aLo,bHi,bLo) | 两区间 → bool；含相等 |
| relation(aHi,aLo,bHi,bLo) | 两区间 → Direction；严格双端同向才非 unknown |
| mergeTail(tail,raw,direction) | 只改变未冻结尾部，更新双极值原始映射 |
| InclusionEngine.ingest(raw,enabled) | 收盘原始 K → 新冻结 ChanBar 或 na；一次最多一个事件 |
| FractalEngine.onBar(frozenBar) | 冻结 K → Fractal 事件；只检查最新三根 |
| StrokeEngine.onFractal(fractal) | 确认分型 → 候选更替/冻结笔事件 |
| FeatureEngine.onStroke(stroke,segmentDirection) | 反向冻结笔 → 去包含特征尾部/特征分型事件 |
| SegmentEngine.onStroke(stroke) | 冻结笔 → 延伸/结束候选/冻结线段事件；内部调用 FeatureEngine |
| PivotEngine.onLeg(leg,level) | 冻结笔或线段的统一 Leg 视图 → 中枢生命周期事件 |
| MoveEngine.onPivot(event) | 同级中枢 + 已确认边界 → 走势状态 |
| MomentumEngine.onRaw(raw,dif,hist) | 按原始边界累积；不能把分型确认后的柱混入端点前面积 |
| DivergenceEngine.onMove(event,momentum) | 比较同级同向离开结构 → 背驰生命周期事件 |
| SignalEngine.onStructure(event) | 同级走势/背驰/回抽 + 前置信号 → 买卖点事件 |
| Renderer.onEvent(event) | 更新有限对象池；候选变淡/虚线、确认转实线 |
| Alerts.onEvent(event) | 当根事件布尔脉冲；同级同结构同状态只发一次 |
| Diagnostics.validate(engine) | 不变量/证据表；失败阻止该层向上传播 |

调度顺序：MACD 每根调用 → 收盘 ingest → 新冻结 K 才更新分型 → 新冻结笔才更新线段与笔中枢 → 新冻结线段才更新线段中枢 → 走势/背驰/信号 → 事件渲染与报警。候选通道独立，不把预览写进冻结数组。

## 5. Pine v6 限制与处理办法

- 实时 K 线会 rollback。核心用 `var` 保存状态，只在收盘提交；不用 `varip` 制造历史回放无法重现的逐 tick 确认。[执行模型](https://www.tradingview.com/pine-script-docs/language/execution-model/)
- UDT/array 是引用类型。对象赋值不是数据复制；冻结 ChanBar 用 `.copy()`，当前所有字段为值类型。未来嵌套数组必须独立复制。[对象](https://www.tradingview.com/pine-script-docs/language/objects/)
- 方法可修改传入对象字段，不能直接重新赋值全局标量。引擎状态放进 UDT，事件作为返回值；`plot/alertcondition` 在全局调用。[类型系统](https://www.tradingview.com/pine-script-docs/language/type-system/)
- 线、框、标签各最多 500 ID；plot count 上限 64，`alertcondition` 也占用。完整版本拟预算 440 条线、360 框、440 标签，报警预留 24 plot count。
- 单根 K 的循环限 500ms，整段运行时间另有限额；集合最多 100,000 元素。核心增量 O(1)，未完成特征片段只在候选变化时有限回放，不能每根扫描全历史。[平台限制](https://www.tradingview.com/pine-script-docs/writing/limitations/)
- Phase 1 用时间坐标画范围框，避免老结构超过 bar_index 绘制范围；最多复用 200 个历史范围框和 1 个候选框。算法环形缓存和显示对象池分开。
- 最大历史长度控制本次加载起点和缓存容量，不能保证换起点、改参数、复权或数据商修订后结果相同。实时运行不逐根移动初始化起点；重新加载后的起点可能改变。要求跨重载严格一致时，使用固定时间起点模式。
- Pine 不适合无限层级递归和无限保存完整证据。先完成两级核心，额外级别以同接口显式实例化；证据缓存不足时报告 unknown，不造信号。
- 本地 Python 测试不是 TradingView 编译器。最终“无编译 error”必须由 Pine Editor 实测，不能用语法审查或第三方解释器代替。

## 6. 开发与逐层验收计划

| Phase | 交付 | 进入下一层的门槛 |
|---|---|---|
| 1 | 去包含、映射、环形缓存、显示、内置自检 | 双向包含/连包/等值/反转/启动/关闭模式；前缀冻结不变；TradingView 编译与回放 |
| 2 | 严格/等值分型与候选 | 三根皆冻结；等值无双重顶底；右邻合并不提前确认 |
| 3 | 两种笔模式 | 同类极值更新、分型不共用、有效跨度、冻结不改 |
| 4 | 线段候选与延伸骨架 | 前三笔共同重叠；5/7/9 笔可延伸；不输出未经 Phase 5 证明的确认线段 |
| 5 | 特征包含/分型/缺口二次确认 | 无缺口、缺口、候选破坏、反向段确认；逐笔证据可查 |
| 6 | 笔中枢 | 100→120→105→115 得 ZD=105/ZG=115；延伸不重复建枢 |
| 7 | 线段中枢 | 同算法重复 Phase 6；来源必须三条冻结线段；嵌套显示 |
| 8 | 走势类型与边界 | 一枢完成盘整；两枢分离趋势；交叠不能判趋势 |
| 9 | MACD 区间统计与两类背驰 | 创新低+负面积减小；未创新低拒绝；统计不足拒绝 |
| 10 | 一类点状态机 | 趋势离开+背驰+反向确认；单纯最低价拒绝 |
| 11 | 二类点状态机 | 前置一类点、反弹、首次回抽、不破；无一类点拒绝 |
| 12 | 三类点状态机 | 100–110→130→115 成立；回105拒绝；突破自身拒绝 |
| 13 | 19 项报警与去重 | 12 类买卖候选/确认、双向背驰、双向离开、回枢、新笔、新段；确认当根触发 |
| 14 | 完整 Dashboard/Debug/外观 | 每个判定能回溯 source ID、数值比较与确认时间；无信号有原因 |
| 15 | 对象预算/性能/回放回归 | 500/1000/2000/5000 历史；显示开关不改算法；重放前缀不变 |

每层有三道检查：确定性例子 → 对抗/随机不变量 → TradingView 编译及 Bar Replay。
前一层未通过时，下一层仅设计、不发布确认结果。Phase 4 和 5 联合构成线段的发布门槛。

## 7. 当前验证记录

所有实现阶段已整合。先运行各模块规格用例，再在 TradingView 中验证完整脚本和生产引擎断言。详细实测状态、样本周期和未穷尽的回放矩阵见 VALIDATION.md。不能用本地测试代替官方编译，也不能用一个行情样本证明所有市场边界正确。
