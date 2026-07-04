# -*- coding: utf-8 -*-
"""Instrument registry tests."""

from __future__ import annotations

import unittest

from instrument_registry import get_instrument, load_instrument_registry


class InstrumentRegistryTests(unittest.TestCase):
    def test_registry_contains_confirmed_core_holdings(self) -> None:
        registry = load_instrument_registry()

        self.assertEqual(registry["NVDA"].display_name, "NVIDIA Corporation")
        self.assertEqual(registry["NVDA"].asset_type, "common_stock")
        self.assertEqual(registry["SOFI"].asset_type, "common_stock")

    def test_spcx_is_not_labeled_as_etf_or_unconfirmed_spacex_guess(self) -> None:
        spcx = get_instrument("SPCX")

        self.assertIsNotNone(spcx)
        self.assertEqual(spcx.asset_type, "common_stock")
        self.assertEqual(spcx.verification_status, "confirmed")
        self.assertNotEqual(spcx.asset_type, "etf")


if __name__ == "__main__":
    unittest.main()
