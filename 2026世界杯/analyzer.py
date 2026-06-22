"""
综合分析引擎 - 综合多维度数据生成比赛分析报告
"""
from datetime import datetime
from typing import Dict, List, Optional
from config import AnalysisWeights
from team_data import TeamData
from odds_analyzer import OddsAnalyzer
from news_sentiment import NewsSentiment
from weather_analysis import WeatherAnalysis


class MatchAnalyzer:
    """多维度比赛分析引擎"""

    def __init__(self):
        self.weights = AnalysisWeights()
        self.weights.validate()
        self.teams = TeamData()
        self.odds = OddsAnalyzer()
        self.news = NewsSentiment()
        self.weather = WeatherAnalysis()

    def analyze(self, team_home: str, team_away: str,
                match_id: str = "") -> Dict:
        """综合分析一场比赛"""
        match_id = match_id or f"{team_home}_vs_{team_away}"

        # 1. 近期状态
        home_form = self.teams.get_form_score(team_home)
        away_form = self.teams.get_form_score(team_away)
        form_diff = home_form - away_form

        # 2. 伤病影响
        home_injury = self.teams.get_injury_impact(team_home)
        away_injury = self.teams.get_injury_impact(team_away)
        injury_diff = away_injury - home_injury  # 正值利好主队

        # 3. 新闻情绪
        home_sentiment = self.news.get_team_sentiment(team_home)
        away_sentiment = self.news.get_team_sentiment(team_away)
        sentiment_diff = home_sentiment - away_sentiment

        # 4. 赔率分析
        odds_analysis = self.odds.get_movement(match_id)

        # 5. 天气影响
        weather_impact = self.weather.get_impact(match_id)

        # 综合评分 (-1 到 1)
        total_score = (
            self.weights.team_form * form_diff +
            self.weights.injuries * injury_diff +
            self.weights.news_sentiment * sentiment_diff +
            self.weights.odds_movement * (
                (odds_analysis["home_prob"] - odds_analysis["away_prob"]) / 100
                if odds_analysis else 0
            ) +
            self.weights.weather * (weather_impact["impact_score"]
                                    if weather_impact else 0) +
            self.weights.home_advantage * 0.1  # 默认微弱主场优势
        )

        # 置信度
        confidence = min(abs(total_score) * 2, 1.0)

        recommendation = self._get_recommendation(total_score, confidence)

        return {
            "match": f"{team_home} vs {team_away}",
            "time": datetime.now().isoformat(),
            "scores": {
                "form_diff": round(form_diff, 2),
                "injury_advantage": round(injury_diff, 2),
                "sentiment_diff": round(sentiment_diff, 2),
                "weather_impact": weather_impact,
            },
            "odds": odds_analysis,
            "total_score": round(total_score, 3),
            "confidence": round(confidence, 2),
            "recommendation": recommendation,
        }

    def _get_recommendation(self, score: float, confidence: float) -> str:
        if confidence < 0.3:
            return "⚠️ 数据不足，建议观望"
        if score > 0.5:
            return "🟢 主队优势明显，值得考虑"
        if score > 0.2:
            return "🟡 主队略占优，谨慎看好"
        if score > -0.2:
            return "⚪ 双方接近，不推荐投注"
        if score > -0.5:
            return "🟡 客队略占优，谨慎看好"
        return "🔴 客队优势明显，值得考虑"

    def batch_analyze(self, matches: List[tuple]) -> List[Dict]:
        """批量分析多场比赛"""
        results = []
        for home, away in matches:
            results.append(self.analyze(home, away))
        results.sort(key=lambda x: abs(x["total_score"]), reverse=True)
        return results


def generate_report(results: List[Dict]) -> str:
    """生成 Markdown 分析报告"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 📊 世界杯比赛分析报告",
        f"**生成时间**: {now}",
        "",
        "---",
        "## 📋 综合推荐排行",
        "",
    ]

    for i, r in enumerate(results, 1):
        conf_stars = "⭐" * int(r["confidence"] * 5)
        lines.extend([
            f"### {i}. {r['match']}",
            f"**评分**: {r['total_score']} | **置信度**: {conf_stars} ({r['confidence']:.0%})",
            f"**建议**: {r['recommendation']}",
            "",
            "| 维度 | 数值 |",
            "|------|------|",
            f"| 状态差 | {r['scores']['form_diff']} |",
            f"| 伤病优势 | {r['scores']['injury_advantage']} |",
            f"| 情绪差 | {r['scores']['sentiment_diff']} |",
            "",
        ])

        if r["odds"]:
            o = r["odds"]
            lines.extend([
                "**最新赔率与概率**:",
                f"- 主胜: {o['latest_odds']['home_win']} (概率 {o['home_prob']}%)",
                f"- 平局: {o['latest_odds']['draw']} (概率 {o['draw_prob']}%)",
                f"- 客胜: {o['latest_odds']['away_win']} (概率 {o['away_prob']}%)",
                f"- 庄家利润率: {o['bookmaker_margin']}%",
                "",
            ])
            if o["signals"]:
                lines.append("**盘口信号**:")
                for s in o["signals"]:
                    lines.append(f"  - {s}")
                lines.append("")

        if r["scores"]["weather_impact"]:
            w = r["scores"]["weather_impact"]
            lines.extend([
                "**天气状况**:",
                f"- 城市: {w['city']}",
                f"- 天气: {w['condition']}",
                f"- 温度: {w['temperature']}°C",
                f"- 影响系数: {w['impact_score']}",
                f"- 建议: {w['advice']}",
                "",
            ])

        lines.append("---")
        lines.append("")

    # 风控提示
    lines.extend([
        "## ⚠️ 风险提示",
        "",
        "1. **彩票/博彩有风险，投注需谨慎**",
        "2. 本分析仅供参考，不构成投注建议",
        "3. 建议设置止损线，不要超过可支配收入的5%",
        "4. 足球比赛存在大量不确定因素，冷门频发",
        "5. 请理性投注，量力而行",
        "",
        "---",
        f"*报告由AI分析引擎自动生成 | {now}*",
    ])

    return "\n".join(lines)
