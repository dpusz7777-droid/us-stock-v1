#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 简报生成层。

本模块只负责 LLM 调用、prompt 构建和 JSON 解析；最终展示由 briefing.py 负责。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol


AI_BRIEFING_FIELDS = (
    "account_summary",
    "portfolio_analysis",
    "watchlist_analysis",
    "risk_warning",
    "action_items",
)

MORNING_BRIEFING_FIELDS = (
    "account_summary",
    "portfolio_analysis",
    "market_hotspots",
    "watchlist_analysis",
    "earnings_today",
    "risk_warning",
    "action_items",
)


class LLMClientError(Exception):
    """LLM 客户端异常。"""


class AIBriefingError(Exception):
    """AI 简报生成异常。"""


class LLMClient(Protocol):
    """统一 LLM 客户端接口，后续可扩展 OpenAI、Claude 等实现。"""

    def generate_json(self, prompt: str) -> Mapping[str, Any]:
        """根据 prompt 返回 JSON 对象。"""


@dataclass(frozen=True)
class DeepSeekClient:
    """DeepSeek Chat Completions 客户端。"""

    api_key: str | None = None
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    timeout: int = 30

    def _api_key(self) -> str:
        key = self.api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not key:
            raise LLMClientError("缺少 DEEPSEEK_API_KEY，无法生成 AI 简报。")
        return key

    def generate_json(self, prompt: str) -> Mapping[str, Any]:
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": os.environ.get("DEEPSEEK_MODEL", self.model),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是一个面向美股新手投资者的只读投资简报助手。"
                        "必须返回 JSON 对象，不要返回 Markdown。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw_response = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise LLMClientError(f"DeepSeek API HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise LLMClientError(f"DeepSeek API 网络失败：{exc.reason}") from exc
        except OSError as exc:
            raise LLMClientError(f"DeepSeek API 请求失败：{exc}") from exc

        try:
            document = json.loads(raw_response)
            content = document["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise LLMClientError("DeepSeek API 返回结构异常。") from exc
        try:
            result = json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMClientError("DeepSeek API 未返回有效 JSON 内容。") from exc
        if not isinstance(result, Mapping):
            raise LLMClientError("DeepSeek API JSON 内容必须是对象。")
        return result


def build_ai_prompt(data: Mapping[str, Any]) -> str:
    """构建要求 LLM 返回固定 JSON schema 的 prompt。"""

    data_json = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return (
        "请基于下面的只读美股简报数据，生成中文 AI 分析。\n"
        "用户是投资新手，请使用稳健、保守、易懂的表达。\n"
        "禁止给出自动交易指令，禁止承诺收益，禁止要求系统买入或卖出。\n"
        "只能给出需要人工复核的观察建议。\n\n"
        "必须只返回 JSON 对象，且字段必须完全为：\n"
        "{\n"
        '  "account_summary": "",\n'
        '  "portfolio_analysis": "",\n'
        '  "watchlist_analysis": "",\n'
        '  "risk_warning": "",\n'
        '  "action_items": ""\n'
        "}\n\n"
        "简报数据：\n"
        f"{data_json}"
    )


def build_morning_prompt(data: Mapping[str, Any]) -> str:
    """构建盘前简报 prompt，要求返回固定 JSON schema。"""

    data_json = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    return (
        "请基于下面的只读美股数据，生成中文盘前简报。\n"
        "用户是投资新手，请使用稳健、保守、易懂的表达。\n"
        "重点关注开盘前需要人工复核的账户、持仓、新闻热点、观察池、财报和风险。\n"
        "禁止给出自动交易指令，禁止承诺收益，禁止要求系统买入或卖出。\n"
        "只能给出需要人工复核的观察建议。\n\n"
        "必须只返回 JSON 对象，且字段必须完全为：\n"
        "{\n"
        '  "account_summary": "",\n'
        '  "portfolio_analysis": "",\n'
        '  "market_hotspots": "",\n'
        '  "watchlist_analysis": "",\n'
        '  "earnings_today": "",\n'
        '  "risk_warning": "",\n'
        '  "action_items": ""\n'
        "}\n\n"
        "盘前数据：\n"
        f"{data_json}"
    )


def validate_ai_briefing_result(result: Mapping[str, Any]) -> dict[str, str]:
    """校验并标准化 AI 返回 JSON。"""

    normalized: dict[str, str] = {}
    for field in AI_BRIEFING_FIELDS:
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AIBriefingError(f"AI 返回 JSON 缺少有效字段：{field}")
        normalized[field] = value.strip()
    return normalized


def validate_morning_briefing_result(result: Mapping[str, Any]) -> dict[str, str]:
    """校验并标准化盘前简报 JSON。"""

    normalized: dict[str, str] = {}
    for field in MORNING_BRIEFING_FIELDS:
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AIBriefingError(f"AI 返回 JSON 缺少有效字段：{field}")
        normalized[field] = value.strip()
    return normalized


def generate_ai_briefing(
    data: Mapping[str, Any],
    client: LLMClient | None = None,
) -> dict[str, str]:
    """生成并校验 AI 简报 JSON。"""

    llm_client = client or DeepSeekClient(
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )
    prompt = build_ai_prompt(data)
    try:
        result = llm_client.generate_json(prompt)
    except LLMClientError:
        raise
    except Exception as exc:
        raise LLMClientError(f"LLM 调用失败：{exc}") from exc
    return validate_ai_briefing_result(result)


def generate_morning_briefing(
    data: Mapping[str, Any],
    client: LLMClient | None = None,
) -> dict[str, str]:
    """生成并校验 AI 盘前简报 JSON。"""

    llm_client = client or DeepSeekClient(
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )
    prompt = build_morning_prompt(data)
    try:
        result = llm_client.generate_json(prompt)
    except LLMClientError:
        raise
    except Exception as exc:
        raise LLMClientError(f"LLM 调用失败：{exc}") from exc
    return validate_morning_briefing_result(result)
