from plane_tracker.web.state import aircraft_chart_points


def test_short_outages_preserve_history_with_zero_baseline():
    points = [{"timestamp": 100, "altitude": 9000, "hits": 120},
              {"timestamp": 400, "altitude": 8000, "hits": 90}]
    result = aircraft_chart_points(points)
    assert result[0] == points[0]
    assert result[-1] == points[-1]
    assert [p["hits"] for p in result] == [120, 0, 0, 90]
    assert result[1]["timestamp"] == 160
    assert result[2]["timestamp"] < 400
    assert result[1]["altitude"] is None


def test_hourly_encounters_are_still_separate():
    points = [{"timestamp": 100, "altitude": 9000, "hits": 120},
              {"timestamp": 4000, "altitude": 8000, "hits": 90}]
    assert aircraft_chart_points(points) == points[1:]


def test_regular_heartbeat_does_not_create_false_silence():
    points = [{"timestamp": t, "altitude": 9000, "hits": 120} for t in range(100, 500, 60)]
    assert aircraft_chart_points(points) == points
