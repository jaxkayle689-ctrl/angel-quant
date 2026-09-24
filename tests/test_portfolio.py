from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from binance_quant.portfolio import PortfolioConfig, PortfolioStore, default_portfolio


class PortfolioTests(unittest.TestCase):
    def test_default_portfolio_allocates_five_independent_projects(self) -> None:
        portfolio = default_portfolio()

        self.assertEqual(portfolio.initial_capital, 5000)
        self.assertEqual(portfolio.allocated_capital, 5000)
        self.assertEqual(portfolio.max_concurrent_positions, 5)
        self.assertEqual(len(portfolio.active_projects), 5)
        self.assertEqual(len({project.symbol for project in portfolio.active_projects}), 5)
        self.assertTrue(all(project.initial_stake == 50 for project in portfolio.active_projects))

    def test_portfolio_rejects_budget_above_capital(self) -> None:
        payload = default_portfolio().to_dict()
        payload["projects"][0]["budget"] = 1001

        with self.assertRaisesRegex(ValueError, "超过组合本金"):
            PortfolioConfig.from_payload(payload)

    def test_portfolio_rejects_duplicate_symbols(self) -> None:
        payload = default_portfolio().to_dict()
        payload["projects"][1]["symbol"] = payload["projects"][0]["symbol"]

        with self.assertRaisesRegex(ValueError, "重复配置"):
            PortfolioConfig.from_payload(payload)

    def test_portfolio_rejects_first_stake_above_project_budget(self) -> None:
        payload = default_portfolio().to_dict()
        payload["projects"][0]["initial_stake"] = 1500

        with self.assertRaisesRegex(ValueError, "首仓"):
            PortfolioConfig.from_payload(payload)

    def test_store_updates_same_portfolio_without_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portfolios.json"
            store = PortfolioStore(path)
            portfolio = default_portfolio()
            store.save(portfolio)
            store.save(portfolio)
            records = store.list()
            raw = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(len(records), 1)
        self.assertNotIn("api_key", json.dumps(raw))
        self.assertNotIn("api_secret", json.dumps(raw))


if __name__ == "__main__":
    unittest.main()
