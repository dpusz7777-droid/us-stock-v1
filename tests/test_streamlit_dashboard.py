import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import dashboard
from price_provider import PriceProviderError, PriceQuote


def portfolio_document() -> dict:
    return {
        "schema_version": "1.1",
        "account": {
            "cash_status": "known",
            "cash": 1000,
            "buying_power": 750,
        },
        "transactions": [
            {
                "transaction_id": "opening-aapl",
                "external_id": None,
                "transaction_type": "OPENING_POSITION",
                "symbol": "AAPL",
                "shares": 2,
                "price": 100,
                "amount": None,
                "fees": 0,
                "executed_at": None,
                "effective_at": "2026-01-01T00:00:00Z",
                "recorded_at": "2026-01-01T00:00:00Z",
                "source": "legacy_migration",
                "note": "",
            }
        ],
    }


class DashboardDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "portfolio.json"
        self.path.write_text(json.dumps(portfolio_document()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_builds_dashboard_from_existing_portfolio_logic(self) -> None:
        class Provider:
            def get_quote(self, symbol: str) -> PriceQuote:
                return PriceQuote(
                    symbol=symbol,
                    price=Decimal("120"),
                    previous_close=Decimal("118"),
                    source="test",
                    price_as_of="2026-07-03T12:00:00Z",
                )

        with patch.object(
            dashboard,
            "recent_reports",
            return_value=[{"date": "2026-07-03", "type": "evening", "file_path": "r.md"}],
        ):
            data = dashboard.build_dashboard_data(self.path, provider=Provider())

        self.assertIsNone(data.error)
        self.assertEqual(data.positions[0]["股票"], "AAPL")
        self.assertEqual(data.positions[0]["现价"], 120.0)
        self.assertEqual(data.positions[0]["盈亏"], 40.0)
        self.assertEqual(data.state.cash, Decimal("1000"))
        self.assertEqual(len(data.reports), 1)

    def test_price_failure_keeps_dashboard_available_with_reason(self) -> None:
        class FailingProvider:
            def get_quote(self, symbol: str) -> PriceQuote:
                raise PriceProviderError("行情服务超时")

        data = dashboard.build_dashboard_data(self.path, provider=FailingProvider())

        self.assertIsNone(data.error)
        self.assertIsNotNone(data.state)
        self.assertIsNone(data.positions[0]["现价"])
        self.assertIn("行情服务超时", data.price_warnings[0])

    def test_invalid_portfolio_returns_ui_error_instead_of_raising(self) -> None:
        self.path.write_text("{}", encoding="utf-8")

        data = dashboard.build_dashboard_data(self.path)

        self.assertIsNone(data.state)
        self.assertIn("持仓读取失败", data.error)


if __name__ == "__main__":
    unittest.main()
