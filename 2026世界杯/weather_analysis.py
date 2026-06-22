"""
天气分析 - 比赛城市天气数据评估
"""
import json
from datetime import datetime
from typing import Dict, Optional


class WeatherAnalysis:
    """天气对比赛的影响分析"""

    # 天气对足球比赛的影响系数
    WEATHER_IMPACT = {
        "clear": 0.0,       # 晴天 — 无影响
        "cloudy": 0.0,      # 多云 — 无影响
        "rain_light": -0.05,   # 小雨 — 轻微影响
        "rain_heavy": -0.15,   # 大雨 — 明显影响，不利于技术型球队
        "storm": -0.25,        # 暴风雨 — 严重影响
        "snow": -0.30,         # 下雪 — 严重影响
        "hot": -0.10,          # 高温>35°C — 影响体能
        "cold": -0.05,         # 低温<5°C — 轻微影响
        "windy": -0.08,        # 大风 — 影响长传和高球
    }

    def __init__(self, filepath: str = "data/weather.json"):
        self.filepath = filepath
        self._data: Dict = self._load()

    def _load(self) -> Dict:
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"forecasts": {}, "last_updated": None}

    def save(self) -> None:
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)

    def update_forecast(self, match_id: str, city: str,
                        condition: str, temperature: float,
                        humidity: int, wind_speed: float) -> None:
        self._data["forecasts"][match_id] = {
            "city": city,
            "condition": condition,
            "temperature": temperature,
            "humidity": humidity,
            "wind_speed": wind_speed,
            "impact_score": self.WEATHER_IMPACT.get(condition, 0),
            "updated_at": datetime.now().isoformat(),
        }
        self._data["last_updated"] = datetime.now().isoformat()

    def get_impact(self, match_id: str) -> Optional[Dict]:
        forecast = self._data["forecasts"].get(match_id)
        if not forecast:
            return None

        impact = forecast["impact_score"]
        advice = "比赛条件正常"
        if impact < -0.2:
            advice = "极端天气！强烈建议关注比赛是否延期"
        elif impact < -0.1:
            advice = "天气条件不佳，可能影响技术型球队发挥"
        elif impact < -0.05:
            advice = "轻微天气影响，关注球队适应能力"

        return {
            "city": forecast["city"],
            "condition": forecast["condition"],
            "temperature": forecast["temperature"],
            "impact_score": impact,
            "advice": advice,
        }
