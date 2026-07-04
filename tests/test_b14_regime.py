from backtest.regime_generator import (
    REGIMES,
    RegimeGenerator,
    apply_regime_score_bias,
)


def test_regime_generator_creates_three_twenty_cycle_blocks():
    rows = [{
        "cycle_id": "000100",
        "symbol": "AAPL",
        "price": 200.0,
        "timestamp": "2026-01-01T00:00:00+00:00",
        "action": "HOLD",
        "score": 50,
    }]

    generated = RegimeGenerator(seed=42).generate(rows)

    assert len(generated) == 60
    blocks = [
        {row["regime"] for row in generated[start:start + 20]}
        for start in (0, 20, 40)
    ]
    assert all(len(block) == 1 for block in blocks)
    assert {next(iter(block)) for block in blocks} == set(REGIMES)
    assert len({row["price"] for row in generated}) > 10


def test_regime_score_biases():
    assert apply_regime_score_bias({
        "regime": "trending_up", "action": "BUY", "score": 50
    })["score"] == 70
    assert apply_regime_score_bias({
        "regime": "trending_up", "action": "SELL", "score": 50
    })["score"] == 40
    assert apply_regime_score_bias({
        "regime": "trending_down", "action": "SELL", "score": 50
    })["score"] == 70
    assert apply_regime_score_bias({
        "regime": "trending_down", "action": "BUY", "score": 50
    })["score"] == 40
    assert apply_regime_score_bias({
        "regime": "sideways", "action": "HOLD", "score": 50
    })["score"] == 65
