from __future__ import annotations

"""决策记忆:每次决策落盘 jsonl,复盘后回注「历史教训」给 PM。

- record():   记录一次完成的决策(评级/票据/快照哈希/通道/时间)
- record_outcome():  之后回算的已实现盈亏(人工或定时任务回填)
- past_context():    同代码最近 N 次决策 + 已实现盈亏教训,生成注入 PM 的文本
"""

import json
import time
from pathlib import Path
from typing import Any


class DecisionMemory:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._outcomes_path = self.path.with_suffix(".outcomes.jsonl")

    def record(self, entry: dict[str, Any]) -> None:
        entry = dict(entry)
        entry.setdefault("time", time.time())
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def record_outcome(self, entry: dict[str, Any]) -> None:
        entry = dict(entry)
        entry.setdefault("time", time.time())
        with self._outcomes_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _read(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def recent(self, symbol: str, limit: int = 5) -> list[dict[str, Any]]:
        matches = [r for r in self._read(self.path) if r.get("symbol") == symbol]
        return matches[-limit:]

    def outcomes(self, symbol: str, limit: int = 10) -> list[dict[str, Any]]:
        matches = [r for r in self._read(self._outcomes_path) if r.get("symbol") == symbol]
        return matches[-limit:]

    def past_context(self, symbol: str, limit: int = 5) -> str:
        """注入 PM prompt 的历史教训文本。"""
        lines: list[str] = []
        for record in self.recent(symbol, limit):
            rating = record.get("rating", "?")
            when = time.strftime("%Y-%m-%d %H:%M", time.localtime(float(record.get("time", 0))))
            direction = (record.get("ticket") or {}).get("direction", "-")
            lines.append(f"- {when} 评级 {rating} 方向 {direction} 通道 {record.get('channel', '?')}")
        outcome_records = self.outcomes(symbol, limit)
        if outcome_records:
            wins = [o for o in outcome_records if float(o.get("pnl_pct", 0)) > 0]
            losses = [o for o in outcome_records if float(o.get("pnl_pct", 0)) <= 0]
            total = sum(float(o.get("pnl_pct", 0)) for o in outcome_records)
            lines.append(
                f"近 {len(outcome_records)} 笔已实现盈亏 {total:+.2f}%"
                f"(胜 {len(wins)} 负 {len(losses)})"
            )
            worst = min(outcome_records, key=lambda o: float(o.get("pnl_pct", 0)))
            if worst.get("note"):
                lines.append(f"最差一笔教训:{worst['note']}")
        if not lines:
            return "无该标的历史决策记录。"
        return "\n".join(lines)
