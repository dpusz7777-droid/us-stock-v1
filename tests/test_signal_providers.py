import random
from datetime import datetime

from providers.base_provider import SignalProvider
from providers.realtime_sim_provider import SYMBOLS, RealtimeSimProvider
from scripts.realtime_signal_worker import TickSignalConverter, vote, weighted_average
from strategies import MeanReversionStrategy, MomentumStrategy


def test_realtime_sim_provider_returns_dynamic_market_ticks():
    provider = RealtimeSimProvider(random.Random(42))

    assert isinstance(provider, SignalProvider)
    assert provider.source == "realtime_sim"

    ticks = [provider.next_tick() for _ in range(10)]

    assert all(tick["symbol"] in SYMBOLS for tick in ticks)
    assert all(100.0 <= tick["price"] <= 300.0 for tick in ticks)
    assert all(1_000 <= tick["volume"] <= 100_000 for tick in ticks)
    assert all(tick["source"] == "realtime_sim" for tick in ticks)
    assert len({tick["symbol"] for tick in ticks}) > 1
    assert len({tick["price"] for tick in ticks}) == len(ticks)
    assert len({tick["volume"] for tick in ticks}) == len(ticks)
    assert [datetime.fromisoformat(tick["timestamp"]) for tick in ticks] == sorted(
        datetime.fromisoformat(tick["timestamp"]) for tick in ticks
    )


def test_tick_to_signal_runs_multiple_strategies_and_preserves_schema():
    provider = RealtimeSimProvider(random.Random(7))
    converter = TickSignalConverter(
        [
            MomentumStrategy(random.Random(11)),
            MeanReversionStrategy(),
        ]
    )

    signals = [converter.convert(provider.next_tick()) for _ in range(21)]

    assert len(converter.strategies) == 2
    assert len({signal["action"] for signal in signals}) >= 2
    assert len({signal["score"] for signal in signals}) > 1
    assert {
        "symbol",
        "price",
        "volume",
        "timestamp",
        "action",
        "score",
        "source",
        "signal_ok",
        "exec_ok",
        "delta",
    } <= signals[0].keys()


def test_fusion_vote_and_average():
    results = [
        {"action": "BUY", "score": 80},
        {"action": "SELL", "score": 40},
    ]
    assert vote(results) == "HOLD"
    assert weighted_average(results) == 60
    assert vote(
        [
            {"action": "BUY", "score": 70},
            {"action": "BUY", "score": 50},
            {"action": "SELL", "score": 90},
        ]
    ) == "BUY"
