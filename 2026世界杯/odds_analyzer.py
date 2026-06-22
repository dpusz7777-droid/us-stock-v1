"""
赔率分析 - 追踪盘口变动、市场热度
"""
import json
from datetime import datetime
from typing import Dict, List, Optional


class OddsAnalyzer:
    """赔率变动分析与市场情绪判断"""

    def __init__(self, filepath: str = "data/odds.json"):
        self.filepath = filepath
        self._odds: Dict = self._load()

    def _load(self) -> Dict:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"matches": {}, "last_updated": None}

    def save(self) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._odds, f, ensure_ascii=False, indent=2)

    def add_snapshot(self, match_id: str,
                     home_win: float, draw: float, away_win: float,
                     source: str = "") -> None:
        """添加赔率快照"""
        if match_id not in self._odds["matches"]:
            self._odds["matches"][match_id] = {"snapshots": []}
        self._odds["matches"][match_id]["snapshots"].append({
            "time": datetime.now().isoformat(),
            "home_win": home_win,
            "draw": draw,
            "away_win": away_win,
            "source": source,
        })
        self._odds["last_updated"] = datetime.now().isoformat()

    def get_movement(self, match_id: str) -> Optional[Dict]:
        """分析赔率变动趋势"""
        snaps = self._odds["matches"].get(match_id, {}).get("snapshots", [])
        if len(snaps) < 2:
            return None
        first, last = snaps[0], snaps[-1]
        home_change = last["home_win"] - first["home_win"]
        away_change = last["away_win"] - first["away_win"]
        draw_change = last["draw"] - first["draw"]

        # 赔率下降 => 热度上升
        signals = []
        if home_change < -0.1:
            signals.append(f"主胜热度上升(赔率↓{abs(home_change):.2f})")
        if away_change < -0.1:
            signals.append(f"客胜热度上升(赔率↓{abs(away_change):.2f})")
        if draw_change < -0.1:
            signals.append("平局热度上升")

        # 计算隐含概率
        def implied_prob(odd: float) -> float:
            return round(1 / odd * 100, 1) if odd > 0 else 0

        fair_total = 1 / last["home_win"] + 1 / last["draw"] + 1 / last["away_win"]
        margin = round((fair_total - 1) * 100, 2)

        return {
            "latest_odds": last,
            "home_prob": implied_prob(last["home_win"]),
            "draw_prob": implied_prob(last["draw"]),
            "away_prob": implied_prob(last["away_win"]),
            "home_change": round(home_change, 2),
            "away_change": round(away_change, 2),
            "draw_change": round(draw_change, 2),
            "signals": signals,
            "bookmaker_margin": margin,
            "snapshot_count": len(snaps),
        }

    def get_highest_value(self, matches: List[str]) -> List[Dict]:
        """找出最有价值的投注选项（高赔率+高概率）"""
        results = []
        for mid in matches:
            analysis = self.get_movement(mid)
            if analysis:
                results.append({
                    "match": mid,
                    "home_value": analysis["home_prob"] / (
                        1 / analysis["latest_odds"]["home_win"]
                    ) if analysis["latest_odds"]["home_win"] > 0 else 0,
                    "draw_value": analysis["draw_prob"] / (
                        1 / analysis["latest_odds"]["draw"]
                    ) if analysis["latest_odds"]["draw"] > 0 else 0,
                    "away_value": analysis["away_prob"] / (
                        1 / analysis["latest_odds"]["away_win"]
                    ) if analysis["latest_odds"]["away_win"] > 0 else 0,
                })
        return sorted(results, key=lambda x: max(
            x["home_value"], x["draw_value"], x["away_value"]
        ), reverse=True)
