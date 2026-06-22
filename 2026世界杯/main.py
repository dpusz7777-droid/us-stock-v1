"""
2026世界杯分析系统 - 主程序
支持交互式分析和数据管理
"""
import os
import sys
from datetime import datetime

from analyzer import MatchAnalyzer, generate_report
from team_data import TeamData
from odds_analyzer import OddsAnalyzer
from news_sentiment import NewsSentiment
from weather_analysis import WeatherAnalysis


def ensure_data_dir():
    os.makedirs("data", exist_ok=True)


def cmd_update_teams():
    """更新球队数据"""
    td = TeamData()
    print("=== 更新球队数据 ===")
    name = input("球队名称: ").strip()
    if not name:
        return
    print("输入近期战绩 (W/D/L，空格分隔，如: W W L D W):")
    results = input().strip().upper().split()
    td.set_form(name, results)
    print("伤病球员 (逗号分隔):")
    injured = [s.strip() for s in input().strip().split(",") if s.strip()]
    print("出战成疑球员 (逗号分隔):")
    questionable = [s.strip() for s in input().strip().split(",") if s.strip()]
    td.set_injuries(name, injured, questionable)
    td.save()
    print(f"✅ {name} 数据已更新")


def cmd_add_odds():
    """添加赔率数据"""
    oa = OddsAnalyzer()
    print("=== 添加赔率快照 ===")
    match_id = input("比赛ID (如: 巴西_vs_阿根廷): ").strip()
    try:
        h = float(input("主胜赔率: "))
        d = float(input("平局赔率: "))
        a = float(input("客胜赔率: "))
    except ValueError:
        print("❌ 请输入有效数字")
        return
    source = input("数据来源 (可选): ").strip()
    oa.add_snapshot(match_id, h, d, a, source)
    oa.save()
    print(f"✅ {match_id} 赔率已添加")


def cmd_add_news():
    """添加新闻"""
    ns = NewsSentiment()
    print("=== 添加新闻/情报 ===")
    team = input("相关球队: ").strip()
    title = input("新闻标题: ").strip()
    summary = input("摘要: ").strip()
    print("情绪 (positive/negative/neutral):")
    sentiment = input().strip().lower()
    if sentiment not in ("positive", "negative", "neutral"):
        sentiment = "neutral"
    source = input("来源 (可选): ").strip()
    ns.add_article(team, title, summary, sentiment, source)
    ns.save()
    print(f"✅ 新闻已添加")


def cmd_analyze():
    """综合分析"""
    ensure_data_dir()
    ma = MatchAnalyzer()
    print("=== 综合分析 ===")
    print("输入比赛 (格式: 主队 客队，每行一场，空行结束):")
    matches = []
    while True:
        line = input().strip()
        if not line:
            break
        parts = line.split()
        if len(parts) >= 2:
            matches.append((parts[0], parts[1]))
    if not matches:
        print("❌ 未输入有效比赛")
        return
    results = ma.batch_analyze(matches)
    report = generate_report(results)
    with open("analysis_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n✅ 报告已保存到 analysis_report.md")


def cmd_add_weather():
    """添加天气数据"""
    wa = WeatherAnalysis()
    print("=== 添加天气数据 ===")
    match_id = input("比赛ID: ").strip()
    city = input("城市: ").strip()
    print("天气条件 (clear/cloudy/rain_light/rain_heavy/storm/hot/cold/windy):")
    condition = input().strip().lower()
    try:
        temp = float(input("温度 (°C): "))
        humidity = int(input("湿度 (%): "))
        wind = float(input("风速 (km/h): "))
    except ValueError:
        print("❌ 请输入有效数字")
        return
    wa.update_forecast(match_id, city, condition, temp, humidity, wind)
    wa.save()
    print(f"✅ 天气数据已添加")


def cmd_quick_analyze():
    """快速分析 - 输入两队名称立即出结果"""
    ma = MatchAnalyzer()
    print("=== 快速分析 ===")
    home = input("主队: ").strip()
    away = input("客队: ").strip()
    if not home or not away:
        return
    result = ma.analyze(home, away)
    report = generate_report([result])
    with open("analysis_report.md", "w", encoding="utf-8") as f:
        f.write(report)
    print(report)
    print(f"\n✅ 报告已保存到 analysis_report.md")


def main():
    ensure_data_dir()
    print("=" * 50)
    print("  🏆 2026世界杯综合分析系统")
    print("=" * 50)
    print(f"  当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print()
    print("  功能菜单:")
    print("  1. 📊 综合分析多场比赛")
    print("  2. ⚡ 快速分析一场比赛")
    print("  3. 🏃 更新球队数据")
    print("  4. 📈 添加赔率快照")
    print("  5. 📰 添加新闻/情报")
    print("  6. 🌤️  添加天气数据")
    print("  0. 退出")
    print()

    actions = {
        "1": cmd_analyze,
        "2": cmd_quick_analyze,
        "3": cmd_update_teams,
        "4": cmd_add_odds,
        "5": cmd_add_news,
        "6": cmd_add_weather,
    }

    while True:
        choice = input("\n请选择操作: ").strip()
        if choice == "0":
            print("👋 再见！")
            break
        action = actions.get(choice)
        if action:
            action()
        else:
            print("❌ 无效选择")


if __name__ == "__main__":
    main()
