from plane_tracker.web.state import LiveState


def test_polar_windows_expire_at_their_boundaries():
    state = LiveState("unused", (51, 0), "unused", metadata_enabled=False)
    now = 100000
    for age, sector, count in [(86400, 0, 10), (86399, 1, 20), (60, 2, 30), (59, 3, 40), (0, 4, 50)]:
        bins = [0] * 36
        bins[sector] = count
        state._append_polar(now - age, bins)
    day = state._polar(now)
    minute = state._polar(now, 60)
    assert day["total"] == 140
    assert minute["total"] == 90
    assert minute["bins"][2] == 0
    assert minute["bins"][3:5] == [40, 50]
    assert day["windowSeconds"] == 86400
    assert minute["windowSeconds"] == 60
    assert state._polar(now)["total"] == 140
    assert state._polar(now + 60, 60)["total"] == 0


def test_snapshot_exposes_both_polar_windows_even_without_receiver():
    state = LiveState("unused", (51, 0), "unused", metadata_enabled=False)
    snapshot = state.snapshot()
    assert snapshot["polar"]["total"] == 0
    assert snapshot["polarMinute"]["total"] == 0
    assert len(snapshot["polarMinute"]["bins"]) == 36
