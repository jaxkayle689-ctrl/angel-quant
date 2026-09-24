# 完整版验证计划与证据分级

日期：2026-09-09。此文档是验收规格；只有最终 `VALIDATION.md` 中记录了实际结果的项目才算通过。Python 规格测试、第三方语法解析、源码检查和 TradingView 官方运行结果分别记录，不能互相代替。

## 1. 可重复的本地检查

1. 重新拼接 `modules/*.pine`，确认最终脚本只有一个 `//@version=6` 和 `indicator()`。为待验证文件记录 SHA-256，编译后修改源码必须重新编译。
2. 运行 `python3 chanlun/tests/check_pine.py chanlun/Chan_Theory_Complete.pine`。检查括号、项目 `f_*` 函数引用和声明先后、UDT 构造参数数量、局部块中的全局绘图调用及少数明确的 v6 违例。`REVIEW` 是人工复核提示，不是已证实错误；通过也不证明 Pine 的类型推导、运行安全或计算正确。
3. 运行 `python3 -m unittest discover -s chanlun/tests -v`，逐项记录测试所属的规格或生产引擎；既有包含处理 14 项测试属于 Python 数值规格。
4. 可使用独立第三方语法解析器作为额外检查。当前选择 [Pynescript 官方项目](https://github.com/elbakramer/pynescript)，固定提交 `0b9b4d0b0cd40d7d98c939830ccd06527a90c4d5`，安装在 `/tmp/chanlun-pine-validation-env`。它提供 AST 解析，并不执行 TradingView 类型检查、服务端优化或图表运行。PyPI 的旧 `0.1.0` 在原 Phase 1 上触发自身异常，因此不用于结论；此次使用提交中的 `0.3.0` ANTLR 实现。

```sh
/tmp/chanlun-pine-validation-env/bin/pynescript parse-and-dump chanlun/Chan_Theory_Complete.pine > /tmp/chanlun-complete-ast.txt
```

PineTS 也是独立实现，其项目将原生 Pine v5/v6 入口标记为 experimental；本项目不以其运行结果替代官方编译。[PineTS 官方 README](https://github.com/luxalgo/pinets)

## 2. 官方语言约束复核

- UDT 可以包含 UDT、enum 和 array。引用类型可通过方法修改字段/集合，函数不能重新绑定参数或全局变量。自定义方法的首参数必须显式注明类型；`plot*`、`alertcondition` 等全局专用函数不得放入函数体。[类型系统](https://www.tradingview.com/pine-script-docs/language/type-system/) · [函数](https://www.tradingview.com/pine-script-docs/language/user-defined-functions/) · [方法](https://www.tradingview.com/pine-script-docs/language/methods/)
- `UDT.copy()` 是浅拷贝。冻结历史前必须复制引用字段；例如 Leg 中的 Meta、Momentum，不能仅复制外壳。[对象](https://www.tradingview.com/pine-script-docs/language/objects/)
- v6 的 `and/or` 惰性求值可用于访问前守卫；`for` 的终点每次迭代重算，遍历中增删集合时必须分析终止性。`obj.field[n]` 不能直接读取 UDT 字段历史；bool 不接受 `na`。[v6 迁移说明](https://www.tradingview.com/pine-script-docs/migration-guides/to-pine-version-6/)
- 空数组上 `get/shift/pop` 必须有有效路径约束。UDT 数组复制仍共享内部对象；数组有 100,000 元素上限。[数组](https://www.tradingview.com/pine-script-docs/language/arrays/)
- 官方当前限制：每种 line/box/label 最多 500 个 ID，设为 `na` 仍占 ID；64 个 plot counts（包含 `alertcondition`）；每循环每根 K 线 500 ms、全历史执行 20/40 秒；每脚本最多 100,256 个 IL token。字符数、源码行数或本地速度不能证明符合这些运行限制。[限制](https://www.tradingview.com/pine-script-docs/writing/limitations/)

## 3. 结构验收用例

| 范围 | 输入及反例 | 必须观察到的行为 |
|---|---|---|
| 包含 | 连续向上/向下包含、等高等低、起始无方向、价格缺口 | 极值来源与原始 K 一致；未知方向前缀明确统计；后继非包含 K 收盘后才冻结前尾部 |
| 分型 | 三处理 K 顶/底、平顶平底、右 K 尚可被包含改变 | 严格/非严格规则区分明确；候选可撤销；确认仅消费冻结 K |
| 笔 | 连续同类分型、中心距离边界、共用 K、极值扩大、过短反向 | 同类保留更极端候选；不合法反向不锁定前笔；已冻结笔端点与时间不变 |
| 线段 | 特征序列连续包含、无缺口顶/底分型、缺口及二次确认、假突破 | 特征序列来自反向笔；不能固定每三笔切段；缺口证据不足保持候选；输出笔区间连续 |
| 中枢 | 三相邻腿有正宽交集、仅接触边界、连续延伸、离开返回、多个独立中枢 | ZD < ZG；初始核心范围与延伸外沿区分；状态迁移和终结时间明确；不能把三个端点当完整中枢 |
| 背驰 | 同向结构创新高/低且动量减弱、价格未创新极值、动量增强、缺采样 | 只有比较证据完整才确认；指标算法开关真实改变比较条件；候选和确认时间分离 |
| 一类 | 离开结构、可比前腿、背驰证据、反向确认不足 | 候选/确认/失效生命周期与 source_id 可追踪；不提前冒充确认 |
| 二类 | 一类之后反弹回调、回踩突破一类极值、跳过任意中间腿 | 依赖有效一类及规定次序；破坏关键极值后失效；不能见回调就标二类 |
| 三类 | 中枢离开后的首次反向返回、触碰/进入核心、后续返回 | 只在返回终结后确认；不得回到核心；关联原中枢并保留边界证据 |
| 双层级 | 同一笔数据形成线段；分别消费冻结笔/线段 | L/H 结构独立，ID 不混用；标注说明结构层级，并非 `request.security` 多周期 |
| 警报 | 同 bar 多层级事件、候选修改/失效、历史回填 | 只对新增确认事件发出一次；提供确认时点，不能把历史端点误当实时可交易时点 |

## 4. 前缀不变性与压力测试

每个合成或市场数据前缀执行以下比较：保存所有 `confirmed` 对象的值快照；追加未来数据后，对仍保留的相同 ID 比较端点、边界、来源 ID、确认时刻和历史状态。候选尾部可以变化；已确认结构不能被悄悄改写。缓存裁剪应只删除超出保留窗口的记录，并明确展示实际保留数量。

补充极端情况：0/1/2 根数据、常数价格、无成交量、长单边、重复价格、负价格、密集波动、启动 MACD 的 `na`、超过动量面积窗口、缓存绕回、连续运行 5,000 根以上。分别检查算法缓存和图形对象池都保持有界；所有显示开关关闭后算法仍能输出一致的确认事件。

## 5. TradingView 发布前验证

1. 在用户已登录的 TradingView 新建独立指标，不覆盖其他脚本。粘贴与 SHA-256 对应的完整最终源码，保存后添加图表。记录日期、品种、周期、输入和所有编译错误/警告。
2. 开启内置断言，确认实际生产方法执行成功；出现 runtime.error 必须修复并重做对应测试。
3. 用足够历史的标准蜡烛图验证 1/5/15/60 分钟、日线；测试完整/Core、严格/新笔、线段严格/宽松、缺口开关、三个背驰算法与 500/2,000/5,000 历史长度。是否能加载所需品种历史取决于当前账户与数据源，缺少样本单列。
4. 用 Bar Replay 从固定开始时间向前逐根推进，重点记录：候选变化、正式确认当根、新事件只出现一次、重新加载后固定输入前缀一致。不能用刷新前后不同滚动起点的数据宣称算法重绘。
5. 全开绘图/Debug 的压力图表运行无数组、历史索引、图形 ID 或时间超限错误；仪表盘计算数量与图上对象预算一致。

若只取得编译成功，应明确写“官方编译通过，回放矩阵未完成”；若有局部运行，写明样本，不扩大成所有市场/周期通过。
