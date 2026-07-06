#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""测试 Windows 自动运行每日决策报告相关脚本。

测试点
------
1. bat 文件存在
2. install ps1 文件存在
3. uninstall ps1 文件存在
4. check ps1 文件存在
5. 文档存在
6. bat 内容包含 run_daily_decision_report.py
7. bat 内容包含 daily_decision_task.log
8. 健康检查脚本可运行或至少文件存在并包含关键检查逻辑
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── 文件路径 ──────────────────────────────────────────────────
BAT_PATH = PROJECT_ROOT / "scripts" / "windows" / "run_daily_decision_report.bat"
INSTALL_PS1 = PROJECT_ROOT / "scripts" / "windows" / "install_daily_decision_task.ps1"
UNINSTALL_PS1 = PROJECT_ROOT / "scripts" / "windows" / "uninstall_daily_decision_task.ps1"
CHECK_PS1 = PROJECT_ROOT / "scripts" / "windows" / "check_daily_decision_task.ps1"
HEALTH_CHECK = PROJECT_ROOT / "scripts" / "check_daily_decision_ready.py"
DOC_PATH = PROJECT_ROOT / "docs" / "windows_daily_decision_task.md"


# ═══════════════════════════════════════════════════════════════
# Test 1: bat 文件存在
# ═══════════════════════════════════════════════════════════════
def test_bat_file_exists() -> None:
    """run_daily_decision_report.bat 文件应存在。"""
    assert BAT_PATH.exists(), f"文件不存在: {BAT_PATH}"
    assert BAT_PATH.is_file()


# ═══════════════════════════════════════════════════════════════
# Test 2: install ps1 文件存在
# ═══════════════════════════════════════════════════════════════
def test_install_ps1_exists() -> None:
    """install_daily_decision_task.ps1 文件应存在。"""
    assert INSTALL_PS1.exists(), f"文件不存在: {INSTALL_PS1}"
    assert INSTALL_PS1.is_file()


# ═══════════════════════════════════════════════════════════════
# Test 3: uninstall ps1 文件存在
# ═══════════════════════════════════════════════════════════════
def test_uninstall_ps1_exists() -> None:
    """uninstall_daily_decision_task.ps1 文件应存在。"""
    assert UNINSTALL_PS1.exists(), f"文件不存在: {UNINSTALL_PS1}"
    assert UNINSTALL_PS1.is_file()


# ═══════════════════════════════════════════════════════════════
# Test 4: check ps1 文件存在
# ═══════════════════════════════════════════════════════════════
def test_check_ps1_exists() -> None:
    """check_daily_decision_task.ps1 文件应存在。"""
    assert CHECK_PS1.exists(), f"文件不存在: {CHECK_PS1}"
    assert CHECK_PS1.is_file()


# ═══════════════════════════════════════════════════════════════
# Test 5: 文档存在
# ═══════════════════════════════════════════════════════════════
def test_doc_exists() -> None:
    """windows_daily_decision_task.md 文档应存在。"""
    assert DOC_PATH.exists(), f"文件不存在: {DOC_PATH}"
    assert DOC_PATH.is_file()
    # 文档应有内容
    content = DOC_PATH.read_text(encoding="utf-8")
    assert len(content) > 100, "文档内容过短"


def test_doc_contains_install_instructions() -> None:
    """文档应包含安装说明。"""
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "安装" in content, "文档应包含安装说明"


def test_doc_contains_uninstall_instructions() -> None:
    """文档应包含卸载说明。"""
    content = DOC_PATH.read_text(encoding="utf-8")
    assert "卸载" in content, "文档应包含卸载说明"


# ═══════════════════════════════════════════════════════════════
# Test 6: bat 内容包含 run_daily_decision_report.py
# ═══════════════════════════════════════════════════════════════
def test_bat_contains_report_script() -> None:
    """bat 文件应包含 run_daily_decision_report.py。"""
    content = BAT_PATH.read_text(encoding="utf-8")
    assert "run_daily_decision_report" in content, (
        "bat 应引用 run_daily_decision_report.py"
    )


# ═══════════════════════════════════════════════════════════════
# Test 7: bat 内容包含 daily_decision_task.log
# ═══════════════════════════════════════════════════════════════
def test_bat_contains_log_file() -> None:
    """bat 文件应包含 daily_decision_task.log。"""
    content = BAT_PATH.read_text(encoding="utf-8")
    assert "daily_decision_task.log" in content, (
        "bat 应引用 daily_decision_task.log"
    )


# ═══════════════════════════════════════════════════════════════
# Test 8: bat 内容包含项目目录
# ═══════════════════════════════════════════════════════════════
def test_bat_contains_project_dir() -> None:
    """bat 文件应包含项目目录路径。"""
    content = BAT_PATH.read_text(encoding="utf-8")
    assert "美股V1" in content, "bat 应包含项目目录"
    assert "PROJECT_DIR" in content or "cd /d" in content, (
        "bat 应切换目录"
    )


# ═══════════════════════════════════════════════════════════════
# Test 9: bat 包含时间戳写入
# ═══════════════════════════════════════════════════════════════
def test_bat_contains_timestamp() -> None:
    """bat 文件应包含时间戳记录。"""
    content = BAT_PATH.read_text(encoding="utf-8")
    assert "TIMESTAMP" in content or "wmic" in content, (
        "bat 应记录时间戳"
    )


# ═══════════════════════════════════════════════════════════════
# Test 10: install ps1 包含关键内容
# ═══════════════════════════════════════════════════════════════
def test_install_ps1_contains_task_name() -> None:
    """install ps1 应包含任务名称。"""
    content = INSTALL_PS1.read_text(encoding="utf-8")
    assert "北极星每日决策报告" in content


def test_install_ps1_contains_batch_script() -> None:
    """install ps1 应引用 bat 脚本。"""
    content = INSTALL_PS1.read_text(encoding="utf-8")
    assert "run_daily_decision_report.bat" in content


# ═══════════════════════════════════════════════════════════════
# Test 11: uninstall ps1 包含关键内容
# ═══════════════════════════════════════════════════════════════
def test_uninstall_ps1_contains_task_name() -> None:
    """uninstall ps1 应包含任务名称。"""
    content = UNINSTALL_PS1.read_text(encoding="utf-8")
    assert "北极星每日决策报告" in content


def test_uninstall_ps1_contains_unregister() -> None:
    """uninstall ps1 应包含 Unregister-ScheduledTask。"""
    content = UNINSTALL_PS1.read_text(encoding="utf-8")
    assert "Unregister-ScheduledTask" in content


# ═══════════════════════════════════════════════════════════════
# Test 12: check ps1 包含关键内容
# ═══════════════════════════════════════════════════════════════
def test_check_ps1_contains_task_name() -> None:
    """check ps1 应包含任务名称。"""
    content = CHECK_PS1.read_text(encoding="utf-8")
    assert "北极星每日决策报告" in content


def test_check_ps1_contains_next_run_time() -> None:
    """check ps1 应检查下一次运行时间。"""
    content = CHECK_PS1.read_text(encoding="utf-8")
    assert "NextRunTime" in content or "下一次" in content


# ═══════════════════════════════════════════════════════════════
# Test 13: 健康检查脚本可导入
# ═══════════════════════════════════════════════════════════════
def test_health_check_file_exists() -> None:
    """check_daily_decision_ready.py 文件应存在。"""
    assert HEALTH_CHECK.exists(), f"文件不存在: {HEALTH_CHECK}"


def test_health_check_contains_check_items() -> None:
    """健康检查应包含关键检查项。"""
    content = HEALTH_CHECK.read_text(encoding="utf-8")
    keywords = ["watchlist", "network_config", "daily_decision_report", "yfinance"]
    for kw in keywords:
        assert kw in content, f"健康检查应包含检查项: {kw}"


def test_health_check_contains_conclusion() -> None:
    """健康检查应包含中文结论。"""
    content = HEALTH_CHECK.read_text(encoding="utf-8")
    assert "可以安装" in content or "不建议安装" in content


# ═══════════════════════════════════════════════════════════════
# Test 14: Windows 脚本目录可列出
# ═══════════════════════════════════════════════════════════════
def test_windows_scripts_directory() -> None:
    """scripts/windows/ 目录下应有 4 个文件。"""
    win_dir = PROJECT_ROOT / "scripts" / "windows"
    assert win_dir.exists()
    files = list(win_dir.iterdir())
    assert len(files) >= 4, f"应有至少 4 个文件，当前 {len(files)}"
    names = [f.name for f in files]
    assert "run_daily_decision_report.bat" in names
    assert "install_daily_decision_task.ps1" in names
    assert "uninstall_daily_decision_task.ps1" in names
    assert "check_daily_decision_task.ps1" in names