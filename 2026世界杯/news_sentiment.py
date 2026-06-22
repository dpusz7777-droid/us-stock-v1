"""
新闻情绪分析 - 追踪球队相关新闻和社交媒体情绪
"""
import json
from datetime import datetime
from typing import Dict, List, Optional


class NewsSentiment:
    """新闻与社交媒体情绪分析"""

    def __init__(self, filepath: str = "data/news.json"):
        self.filepath = filepath
        self._data: Dict = self._load()

    def _load(self) -> Dict:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"articles": [], "last_updated": None}

    def save(self) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def add_article(self, team: str, title: str, summary: str,
                    sentiment: str, source: str = "") -> None:
        """
        添加新闻条目
        sentiment: "positive" / "negative" / "neutral"
        """
        self._data["articles"].append({
            "team": team,
            "title": title,
            "summary": summary,
            "sentiment": sentiment,
            "source": source,
            "timestamp": datetime.now().isoformat(),
        })
        self._data["last_updated"] = datetime.now().isoformat()

    def get_team_sentiment(self, team: str, hours: int = 24) -> float:
        """
        计算球队近期情绪得分
        返回 -1.0 (极负面) 到 1.0 (极正面)
        """
        from datetime import timedelta
        cutoff = datetime.now() - timedelta(hours=hours)

        articles = [
            a for a in self._data["articles"]
            if a["team"] == team
            and datetime.fromisoformat(a["timestamp"]) > cutoff
        ]
        if not articles:
            return 0.0

        scores = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}
        total = sum(scores.get(a["sentiment"], 0) for a in articles)
        return round(total / len(articles), 2)

    def get_team_news_summary(self, team: str, limit: int = 5) -> List[Dict]:
        return [
            a for a in self._data["articles"]
            if a["team"] == team
        ][-limit:]

    def get_hot_topics(self, top_n: int = 5) -> List[Dict]:
        """获取最热门的球队话题"""
        from collections import Counter
        team_counts = Counter(a["team"] for a in self._data["articles"]
                             if a["sentiment"] != "neutral")
        return team_counts.most_common(top_n)
