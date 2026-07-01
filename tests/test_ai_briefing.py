# -*- coding: utf-8 -*-
"""AI 简报 LLM 层测试。"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from ai_briefing import (
    AIBriefingError,
    DeepSeekClient,
    LLMClientError,
    build_ai_prompt,
    build_morning_prompt,
    generate_ai_briefing,
    generate_morning_briefing,
    validate_ai_briefing_result,
    validate_morning_briefing_result,
)


VALID_AI_RESULT = {
    "account_summary": "账户摘要",
    "portfolio_analysis": "持仓分析",
    "watchlist_analysis": "观察池分析",
    "risk_warning": "风险提示",
    "action_items": "今日操作建议",
}

VALID_MORNING_RESULT = {
    "account_summary": "账户摘要",
    "portfolio_analysis": "持仓分析",
    "market_hotspots": "市场热点",
    "watchlist_analysis": "观察池分析",
    "earnings_today": "今日财报",
    "risk_warning": "风险提示",
    "action_items": "今日操作建议",
}


class AIBriefingTests(unittest.TestCase):
    def test_build_ai_prompt_requires_json_and_read_only_guidance(self) -> None:
        prompt = build_ai_prompt(
            {
                "account": {"total_equity": "125"},
                "positions": [{"symbol": "SOFI"}],
                "watchlist": ["NVDA"],
                "news": [{"symbol": "NVDA", "title": "headline"}],
                "earnings": [{"symbol": "NVDA", "earnings_date": "TBD"}],
            }
        )

        self.assertIn("必须只返回 JSON 对象", prompt)
        self.assertIn("account_summary", prompt)
        self.assertIn("portfolio_analysis", prompt)
        self.assertIn("watchlist_analysis", prompt)
        self.assertIn("risk_warning", prompt)
        self.assertIn("action_items", prompt)
        self.assertIn("禁止给出自动交易指令", prompt)
        self.assertIn("SOFI", prompt)
        self.assertIn("NVDA", prompt)

    def test_validate_ai_briefing_result_requires_all_fields(self) -> None:
        with self.assertRaisesRegex(AIBriefingError, "risk_warning"):
            validate_ai_briefing_result(
                {
                    "account_summary": "账户摘要",
                    "portfolio_analysis": "持仓分析",
                    "watchlist_analysis": "观察池分析",
                    "action_items": "今日操作建议",
                }
            )

    def test_build_morning_prompt_requires_morning_json_fields(self) -> None:
        prompt = build_morning_prompt(
            {
                "account": {"total_equity": "125"},
                "positions": [{"symbol": "SOFI"}],
                "watchlist": ["NVDA"],
                "news": [{"symbol": "NVDA", "title": "headline"}],
                "earnings": [{"symbol": "NVDA", "earnings_date": "TBD"}],
            }
        )

        self.assertIn("盘前简报", prompt)
        self.assertIn("account_summary", prompt)
        self.assertIn("portfolio_analysis", prompt)
        self.assertIn("market_hotspots", prompt)
        self.assertIn("watchlist_analysis", prompt)
        self.assertIn("earnings_today", prompt)
        self.assertIn("risk_warning", prompt)
        self.assertIn("action_items", prompt)
        self.assertIn("禁止给出自动交易指令", prompt)

    def test_validate_morning_briefing_result_requires_all_fields(self) -> None:
        incomplete = dict(VALID_MORNING_RESULT)
        del incomplete["market_hotspots"]

        with self.assertRaisesRegex(AIBriefingError, "market_hotspots"):
            validate_morning_briefing_result(incomplete)

    def test_generate_ai_briefing_uses_llm_client_json(self) -> None:
        class FakeLLMClient:
            def __init__(self) -> None:
                self.prompt = ""

            def generate_json(self, prompt: str) -> dict[str, str]:
                self.prompt = prompt
                return dict(VALID_AI_RESULT)

        client = FakeLLMClient()
        result = generate_ai_briefing({"watchlist": ["NVDA"]}, client=client)

        self.assertEqual(result, VALID_AI_RESULT)
        self.assertIn("NVDA", client.prompt)

    def test_generate_morning_briefing_uses_llm_client_json(self) -> None:
        class FakeLLMClient:
            def __init__(self) -> None:
                self.prompt = ""

            def generate_json(self, prompt: str) -> dict[str, str]:
                self.prompt = prompt
                return dict(VALID_MORNING_RESULT)

        client = FakeLLMClient()
        result = generate_morning_briefing({"watchlist": ["NVDA"]}, client=client)

        self.assertEqual(result, VALID_MORNING_RESULT)
        self.assertIn("NVDA", client.prompt)
        self.assertIn("market_hotspots", client.prompt)

    def test_deepseek_client_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(LLMClientError, "DEEPSEEK_API_KEY"):
                DeepSeekClient().generate_json("prompt")


if __name__ == "__main__":
    unittest.main()
