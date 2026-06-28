"""The scoring model is pure arithmetic — fully testable without a network."""
from netdoctor.score import build_scorecard, grade_for, perf_score, stability_score


def test_perf_score_is_monotonic_and_bounded():
    assert perf_score(10) > perf_score(200) > perf_score(2000)
    assert perf_score(0) == 100.0
    assert 0 <= perf_score(9999) <= 10


def test_stability_rewards_low_jitter():
    steady = stability_score(jitter_ms=5, avg_ms=100)
    jumpy = stability_score(jitter_ms=120, avg_ms=100)
    assert steady > jumpy
    assert steady == 100.0


def test_grade_boundaries():
    assert grade_for(99) == "A+"
    assert grade_for(91) == "A-"
    assert grade_for(78) == "C+"
    assert grade_for(75) == "C"
    assert grade_for(10) == "F"


def test_fast_reliable_host_grades_high():
    samples = [(True, 40.0)] * 20
    card = build_scorecard([], samples)
    assert card.reachability == 100.0
    assert card.success_rate == 100.0
    assert card.grade.startswith("A")
    assert card.throughput_rps == 25.0       # 1000 / 40ms
    assert card.lat_p95 == 40.0


def test_partial_failures_lower_reachability():
    samples = [(True, 50.0), (True, 60.0), (False, None), (False, None)]
    card = build_scorecard([], samples)
    assert card.reachability == 50.0
    assert card.n_ok == 2 and card.n_total == 4


def test_unreachable_host_is_F():
    card = build_scorecard([], [(False, None)] * 5)
    assert card.reachability == 0.0
    assert card.performance == 0.0
    assert card.grade == "F"
    assert card.throughput_rps is None


def test_jitter_is_computed_over_samples():
    card = build_scorecard([], [(True, 100.0), (True, 100.0), (True, 100.0)])
    assert card.jitter_ms == 0.0
    assert card.stability == 100.0
