from backtest.metrics import calculate_metrics
from backtest.microstructure import MarketMicrostructure


def test_microstructure_is_noisy_reproducible_and_can_shock():
    rows = [{
        "cycle_id": f"{index:06d}",
        "symbol": "AAPL",
        "price": 100.0 + index,
        "timestamp": f"T{index}",
        "regime": "trending_up",
    } for index in range(20)]

    first = MarketMicrostructure(seed=7, shock_probability=1.0).generate(rows)
    second = MarketMicrostructure(seed=7, shock_probability=1.0).generate(rows)

    assert first == second
    assert len({row["price"] for row in first}) > 1
    assert all(0.5 <= row["microstructure"]["noise_std"] <= 1.5 for row in first)
    assert all(row["microstructure"]["shock_event"] for row in first)


def test_signal_accuracy_and_edge_follow_future_price_direction():
    curve = [
        {
            "symbol": "AAPL", "price": 100, "action": "BUY",
            "equity": 100000, "regime": "trending_up",
        },
        {
            "symbol": "AAPL", "price": 110, "action": "SELL",
            "equity": 101000, "regime": "trending_up",
        },
        {
            "symbol": "AAPL", "price": 105, "action": "HOLD",
            "equity": 101000, "regime": "sideways",
        },
    ]

    metrics = calculate_metrics(curve, [], 100000)

    assert metrics["signal_accuracy"] == 1.0
    assert metrics["edge_per_trade"] > 0
