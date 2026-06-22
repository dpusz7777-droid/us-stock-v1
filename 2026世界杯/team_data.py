"""
球队基础数据管理 - 手动维护球队信息
"""
import json
from typing import Dict, Optional


class TeamData:
    """球队信息管理"""

    def __init__(self, filepath: str = "data/teams.json"):
        self.filepath = filepath
        self._data: Dict = self._load()

    def _load(self) -> Dict:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def save(self) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def update_team(self, name: str, info: dict) -> None:
        self._data[name] = info

    def get_team(self, name: str) -> Optional[Dict]:
        return self._data.get(name)

    def set_form(self, name: str, recent_results: list[str]) -> None:
        """设置近期战绩，如 ["W", "W", "L", "D", "W"]"""
        if name not in self._data:
            self._data[name] = {}
        self._data[name]["form"] = recent_results
        wins = recent_results.count("W")
        draws = recent_results.count("D")
        losses = recent_results.count("L")
        total = len(recent_results)
        self._data[name]["form_score"] = round((wins * 3 + draws) / (total * 3), 2)

    def set_injuries(self, name: str, injured: list[str], questionable: list[str]) -> None:
        if name not in self._data:
            self._data[name] = {}
        self._data[name]["injured"] = injured
        self._data[name]["questionable"] = questionable
        total_players = self._data[name].get("squad_size", 26)
        self._data[name]["injury_impact"] = round(
            (len(injured) * 1.0 + len(questionable) * 0.5) / total_players, 2
        )

    def set_head_to_head(self, team1: str, team2: str, record: dict) -> None:
        """历史交锋记录"""
        key = f"h2h_{team1}_vs_{team2}"
        self._data[key] = record

    def get_form_score(self, name: str) -> float:
        return self._data.get(name, {}).get("form_score", 0.5)

    def get_injury_impact(self, name: str) -> float:
        return self._data.get(name, {}).get("injury_impact", 0.0)

    def list_all_teams(self) -> list:
        return [k for k in self._data if not k.startswith("h2h_")]
