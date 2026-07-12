# -*- coding: utf-8 -*-
"""portfolio_service 第一阶段核心逻辑测试。

测试只使用内存数据，不访问网络，也不读取或修改项目中的 JSON 文件。
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from portfolio_service import (
    PortfolioCalculationError,
    PortfolioValidationError,
    UnsupportedTransactionError,
    apply_market_prices,
    build_portfolio_state,
    load_portfolio,
    validate_portfolio,
)


D = Decimal


def opening_position(
    transaction_id: str,
    symbol: str,
    shares: str,
    price: str,
    effective_at: str = "2026-06-22T17:15:41Z",
) -> dict:
    return {
        "transaction_id": transaction_id,
        "external_id": None,
        "transaction_type": "OPENING_POSITION",
        "symbol": symbol,
        "shares": D(shares),
        "price": D(price),
        "amount": None,
        "fees": D("0"),
        "executed_at": None,
        "effective_at": effective_at,
        "recorded_at": effective_at,
        "source": "legacy_migration",
        "note": "期初持仓，不代表原始逐笔成交记录。",
    }


def normal_transaction(
    transaction_id: str,
    transaction_type: str,
    symbol: str,
    shares: str,
    price: str,
    fees: str = "0",
    executed_at: str = "2026-06-23T14:00:00Z",
) -> dict:
    return {
        "transaction_id": transaction_id,
        "external_id": None,
        "transaction_type": transaction_type,
        "symbol": symbol,
        "shares": D(shares),
        "price": D(price),
        "amount": None,
        "fees": D(fees),
        "executed_at": executed_at,
        "effective_at": None,
        "recorded_at": executed_at,
        "source": "manual",
        "note": "测试交易",
    }


def document(
    transactions: list[dict],
    cash_status: str = "unknown",
    version: str = "1.1",
    account_extra: dict | None = None,
) -> dict:
    account = {
        "account_id": "test_account",
        "account_name": "测试账户",
        "broker": "test",
        "base_currency": "USD",
        "cash_status": cash_status,
        "created_at": "2026-06-22T17:00:00Z",
        "updated_at": "2026-06-22T17:00:00Z",
    }
    if account_extra:
        account.update(account_extra)
    return {
        "schema_version": version,
        "account": account,
        "settings": {
            "stop_loss_pct": D("8"),
            "target_profit_pct": D("25"),
            "max_single_position_pct": D("20"),
        },
        "transactions": transactions,
    }


class PortfolioServiceTests(unittest.TestCase):
    def test_opening_positions_match_confirmed_candidate(self) -> None:
        data = document(
            [
                opening_position("txn_001", "SOFI", "59", "17.50"),
                opening_position("txn_002", "SPCX", "2", "202"),
            ]
        )

        state = build_portfolio_state(data)

        self.assertEqual(state.positions["SOFI"].shares, D("59"))
        self.assertEqual(state.positions["SOFI"].avg_cost, D("17.50"))
        self.assertEqual(state.positions["SOFI"].cost_basis, D("1032.50"))
        self.assertEqual(state.positions["SPCX"].shares, D("2"))
        self.assertEqual(state.positions["SPCX"].avg_cost, D("202"))
        self.assertEqual(state.positions["SPCX"].cost_basis, D("404"))
        self.assertEqual(state.total_cost_basis, D("1436.50"))
        self.assertEqual(state.realized_pnl, D("0"))

    def test_unknown_cash_never_becomes_zero(self) -> None:
        state = build_portfolio_state(
            document([opening_position("txn_001", "SOFI", "59", "17.50")])
        )

        self.assertEqual(state.cash_status, "unknown")
        self.assertIsNone(state.cash)
        self.assertIsNone(state.total_equity)
        self.assertIsNone(state.buying_power)

    def test_known_cash_returns_decimal_cash_change(self) -> None:
        state = build_portfolio_state(
            document(
                [opening_position("txn_001", "SOFI", "2", "10")],
                cash_status="known",
            )
        )

        self.assertEqual(state.cash, D("0"))
        self.assertEqual(state.buying_power, D("0"))

    def test_known_cash_uses_account_cash_and_buying_power(self) -> None:
        state = build_portfolio_state(
            document(
                [
                    opening_position("txn_001", "SOFI", "2", "10"),
                    normal_transaction("txn_002", "BUY", "SOFI", "1", "12"),
                ],
                cash_status="known",
                account_extra={"cash": D("1000"), "buying_power": D("900")},
            )
        )

        self.assertEqual(state.cash, D("988"))
        self.assertEqual(state.buying_power, D("900"))

    def test_account_cash_overrides_unknown_cash_status(self) -> None:
        state = build_portfolio_state(
            document(
                [opening_position("txn_001", "SOFI", "2", "10")],
                cash_status="unknown",
                account_extra={"cash": D("1000")},
            )
        )

        self.assertEqual(state.cash_status, "known")
        self.assertEqual(state.cash, D("1000"))
        self.assertEqual(state.buying_power, D("1000"))

    def test_account_cash_and_buying_power_validate_as_numbers(self) -> None:
        with self.assertRaisesRegex(PortfolioValidationError, "account.cash"):
            validate_portfolio(
                document([], cash_status="known", account_extra={"cash": "1000"})
            )

    def test_load_portfolio_migrates_legacy_cash_without_writing_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            schema_path = root / "portfolio_migrated_candidate.json"
            legacy_path = root / "portfolio.json"
            schema_data = document(
                [opening_position("txn_001", "SOFI", "2", "10")],
                cash_status="unknown",
            )
            schema_path.write_text(
                json.dumps(schema_data, ensure_ascii=False, default=float),
                encoding="utf-8",
            )
            legacy_path.write_text(
                json.dumps({"positions": [], "cash": 2000.0}, ensure_ascii=False),
                encoding="utf-8",
            )
            schema_before = schema_path.read_bytes()
            legacy_before = legacy_path.read_bytes()

            loaded = load_portfolio(schema_path)
            state = build_portfolio_state(loaded)

            self.assertEqual(loaded["account"]["cash_status"], "known")
            self.assertEqual(loaded["account"]["cash"], D("2000.0"))
            self.assertEqual(loaded["account"]["buying_power"], D("2000.0"))
            self.assertEqual(state.cash, D("2000.0"))
            self.assertEqual(state.buying_power, D("2000.0"))
            self.assertEqual(schema_path.read_bytes(), schema_before)
            self.assertEqual(legacy_path.read_bytes(), legacy_before)

    def test_buy_uses_weighted_average_and_fees(self) -> None:
        state = build_portfolio_state(
            document(
                [
                    opening_position("txn_001", "SOFI", "10", "10"),
                    normal_transaction("txn_002", "BUY", "SOFI", "5", "13", "1"),
                ]
            )
        )

        position = state.positions["SOFI"]
        self.assertEqual(position.shares, D("15"))
        self.assertEqual(position.cost_basis, D("166"))
        self.assertEqual(position.avg_cost, D("166") / D("15"))
        self.assertEqual(state.cash_change_since_tracking, D("-66"))
        self.assertIsNone(state.cash)

    def test_partial_sell_calculates_realized_pnl(self) -> None:
        state = build_portfolio_state(
            document(
                [
                    opening_position("txn_001", "SOFI", "10", "10"),
                    normal_transaction("txn_002", "SELL", "SOFI", "4", "15", "1"),
                ]
            )
        )

        position = state.positions["SOFI"]
        self.assertEqual(position.shares, D("6"))
        self.assertEqual(position.cost_basis, D("60"))
        self.assertEqual(position.avg_cost, D("10"))
        self.assertEqual(position.realized_pnl, D("19"))
        self.assertEqual(state.realized_pnl, D("19"))
        self.assertEqual(state.cash_change_since_tracking, D("59"))

    def test_full_sell_removes_open_position(self) -> None:
        state = build_portfolio_state(
            document(
                [
                    opening_position("txn_001", "SPCX", "2", "202"),
                    normal_transaction("txn_002", "SELL", "SPCX", "2", "210"),
                ]
            )
        )

        self.assertNotIn("SPCX", state.positions)
        self.assertEqual(state.realized_pnl, D("16"))

    def test_sell_more_than_holding_is_rejected(self) -> None:
        data = document(
            [
                opening_position("txn_001", "SOFI", "2", "10"),
                normal_transaction("txn_002", "SELL", "SOFI", "3", "11"),
            ]
        )

        with self.assertRaisesRegex(PortfolioCalculationError, "超过当前持股"):
            build_portfolio_state(data)

    def test_unsupported_transaction_type_is_explicit(self) -> None:
        unsupported = normal_transaction("txn_001", "DIVIDEND", "SOFI", "1", "1")

        with self.assertRaisesRegex(UnsupportedTransactionError, "暂未支持"):
            build_portfolio_state(document([unsupported]))

    def test_opening_position_requires_legacy_source(self) -> None:
        transaction = opening_position("txn_001", "SOFI", "1", "10")
        transaction["source"] = "manual"

        with self.assertRaisesRegex(PortfolioValidationError, "legacy_migration"):
            validate_portfolio(document([transaction]))

    def test_schema_version_must_be_1_1(self) -> None:
        with self.assertRaisesRegex(PortfolioValidationError, "只支持 1.1"):
            validate_portfolio(document([], version="1.0"))

    def test_transactions_are_sorted_by_event_recorded_and_id(self) -> None:
        # 输入中 SELL 故意放在 OPENING_POSITION 前面；时间排序后应能正确卖出。
        sell = normal_transaction(
            "txn_003",
            "SELL",
            "SOFI",
            "1",
            "12",
            executed_at="2026-06-23T00:00:00Z",
        )
        opening = opening_position(
            "txn_001",
            "SOFI",
            "2",
            "10",
            effective_at="2026-06-22T00:00:00Z",
        )

        state = build_portfolio_state(document([sell, opening]))

        self.assertEqual(state.positions["SOFI"].shares, D("1"))
        self.assertEqual(state.realized_pnl, D("2"))

    def test_market_prices_calculate_values_with_decimal(self) -> None:
        state = build_portfolio_state(
            document(
                [
                    opening_position("txn_001", "SOFI", "59", "17.50"),
                    opening_position("txn_002", "SPCX", "2", "202"),
                ]
            )
        )

        priced = apply_market_prices(
            state,
            {
                "SOFI": {
                    "price": D("18.25"),
                    "price_as_of": "2026-07-10T12:00:00Z",
                    "source": "test_provider",
                },
                "SPCX": {
                    "price": D("182.875"),
                    "price_as_of": "2026-07-10T12:00:00Z",
                    "source": "test_provider",
                },
            },
        )

        self.assertEqual(priced.positions["SOFI"].market_value, D("1076.75"))
        self.assertEqual(priced.positions["SOFI"].unrealized_pnl, D("44.25"))
        self.assertEqual(priced.positions["SPCX"].market_value, D("365.750"))
        self.assertIsNone(priced.total_market_value)
        self.assertIsNone(priced.total_unrealized_pnl)
        self.assertIsNone(priced.total_equity)
        self.assertIsNone(priced.cash)
        self.assertIsNone(priced.buying_power)

    def test_known_cash_total_equity_and_buying_power_survive_prices(self) -> None:
        state = build_portfolio_state(
            document(
                [opening_position("txn_001", "SOFI", "2", "10")],
                cash_status="known",
                account_extra={"cash": D("1000"), "buying_power": D("850")},
            )
        )

        priced = apply_market_prices(state, {"SOFI": {
            "price": D("12"),
            "price_as_of": "2026-07-10T12:00:00Z",
            "source": "test_provider",
        }})

        self.assertEqual(priced.cash, D("1000"))
        self.assertEqual(priced.buying_power, D("850"))
        self.assertEqual(priced.total_market_value, D("24"))
        self.assertEqual(priced.total_equity, D("1024"))

    def test_missing_price_makes_totals_incomplete(self) -> None:
        state = build_portfolio_state(
            document(
                [
                    opening_position("txn_001", "SOFI", "1", "10"),
                    opening_position("txn_002", "SPCX", "1", "20"),
                ]
            )
        )

        priced = apply_market_prices(state, {"SOFI": D("12")})

        self.assertFalse(priced.prices_complete)
        self.assertIsNone(priced.total_market_value)
        self.assertIsNone(priced.total_unrealized_pnl)

    def test_decimal_fractional_shares_keep_precision(self) -> None:
        state = build_portfolio_state(
            document([opening_position("txn_001", "SPY", "0.1325", "754.34")])
        )

        self.assertEqual(state.positions["SPY"].cost_basis, D("99.950050"))

    def test_input_document_is_not_modified(self) -> None:
        data = document(
            [
                normal_transaction("txn_002", "BUY", "SOFI", "1", "12"),
                opening_position("txn_001", "SOFI", "2", "10"),
            ]
        )
        original = copy.deepcopy(data)

        build_portfolio_state(data)

        self.assertEqual(data, original)


if __name__ == "__main__":
    unittest.main()
