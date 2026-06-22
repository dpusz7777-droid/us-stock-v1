"""
2026世界杯分析系统 - 配置文件
"""
from dataclasses import dataclass, field
from typing import Dict, List

# ========== 分组信息（2026世界杯48队12组） ==========
GROUPS: Dict[str, List[str]] = {
    "A组": ["球队A1", "球队A2", "球队A3", "球队A4"],
    "B组": ["球队B1", "球队B2", "球队B3", "球队B4"],
    "C组": ["球队C1", "球队C2", "球队C3", "球队C4"],
    "D组": ["球队D1", "球队D2", "球队D3", "球队D4"],
    "E组": ["球队E1", "球队E2", "球队E3", "球队E4"],
    "F组": ["球队F1", "球队F2", "球队F3", "球队F4"],
    "G组": ["球队G1", "球队G2", "球队G3", "球队G4"],
    "H组": ["球队H1", "球队H2", "球队H3", "球队H4"],
    "I组": ["球队I1", "球队I2", "球队I3", "球队I4"],
    "J组": ["球队J1", "球队J2", "球队J3", "球队J4"],
    "K组": ["球队K1", "球队K2", "球队K3", "球队K4"],
    "L组": ["球队L1", "球队L2", "球队L3", "球队L4"],
}

# ========== 分析权重配置 ==========
@dataclass
class AnalysisWeights:
    """各维度分析权重（总和 = 1.0）"""
    team_form: float = 0.20       # 近期状态
    head_to_head: float = 0.10    # 历史交锋
    news_sentiment: float = 0.10  # 新闻情绪
    injuries: float = 0.15        # 伤病情况
    odds_movement: float = 0.15   # 赔率变动
    weather: float = 0.05         # 天气影响
    home_advantage: float = 0.10  # 主客场/中立场地
    market_volume: float = 0.15   # 市场交易量

    def validate(self):
        total = sum([
            self.team_form, self.head_to_head, self.news_sentiment,
            self.injuries, self.odds_movement, self.weather,
            self.home_advantage, self.market_volume
        ])
        assert abs(total - 1.0) < 0.01, f"权重之和应为1.0，当前为{total}"


# ========== 文件路径 ==========
DATA_DIR = "data"
TEAMS_FILE = f"{DATA_DIR}/teams.json"
MATCHES_FILE = f"{DATA_DIR}/matches.json"
ODDS_FILE = f"{DATA_DIR}/odds.json"
NEWS_FILE = f"{DATA_DIR}/news.json"
WEATHER_FILE = f"{DATA_DIR}/weather.json"
REPORT_FILE = "analysis_report.md"

# ========== 比赛阶段 ==========
STAGES = ["小组赛", "1/16决赛", "1/8决赛", "1/4决赛", "半决赛", "三四名决赛", "决赛"]
