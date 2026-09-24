import json
import time
from unittest.mock import patch

from plane_tracker.web.state import LiveState


def state(tmp_path):
    return LiveState('unused', (0, 0), tmp_path, tmp_path / 'cache.json', 'unused')


def plane(icao='ABC123', messages=100, lat=1, lon=0, **extra):
    return dict(hex=icao, messages=messages, lat=lat, lon=lon, seen_pos=0, **extra)


def ingest(s, t, *planes):
    s.ingest({'aircraft': list(planes)}, t, now=t)


def test_position_hits_ignore_raw_counters_and_duplicate_positions(tmp_path):
    s = state(tmp_path)
    t = time.time()
    ingest(s, t, plane(), plane('DEF456', lon=1, lat=0))
    assert s.snapshot(t)['polar']['total'] == 2
    unchanged = plane(messages=5000)
    unchanged['seen_pos'] = 1
    ingest(s, t+1, unchanged)
    assert s.snapshot(t+1)['aircraft'][0]['positionHits'] == 1
    ingest(s, t+2, plane(messages=9000))  # new timestamp, same coordinates
    ingest(s, t+2, plane(messages=9000))
    assert s.snapshot(t+2)['aircraft'][0]['positionHits'] == 2
    assert s.snapshot(t+2)['polar']['bins'][0] == 2
    assert s.snapshot(t+2)['polar']['bins'][9] == 1
    assert s.snapshot(t+904)['polar']['total'] == 0


def test_missing_position_age_and_missing_coordinates_are_not_hits(tmp_path):
    s = state(tmp_path)
    t = time.time()
    missing_age = plane(); missing_age.pop('seen_pos'); missing_age['seen'] = 0
    ingest(s, t, missing_age, plane('DEF456', lat=None, lon=None))
    assert s.snapshot(t)['polar']['total'] == 0


def test_enrichment_updates_live_summary_cache_and_survives_reload(tmp_path):
    s = state(tmp_path)
    t = time.time()
    ingest(s, t, plane(), plane('DEF456'))
    assert s.snapshot(t)['stats']['unknownModels'] == 2
    result = dict(owner='Example Air', model='A320', manufacturer='Airbus', registration='G-TEST')
    with patch('plane_tracker.web.state.fetch_plane_info', return_value=result) as fetch:
        s._metadata_once(t)
        s._metadata_once(t+1)
        s._metadata_once(t+2)
        assert fetch.call_count == 2
    s.reload_history()
    ingest(s, t+3, plane(t='A20N'), plane('DEF456'))
    snap = s.snapshot(t+3)
    assert snap['stats']['airlines'] == 1
    assert snap['stats']['models'] == 1
    assert snap['stats']['unknownModels'] == 0
    assert snap['aircraft'][0]['model'] == 'A320'
    assert json.loads((tmp_path/'cache.json').read_text())['ABC123']['owner'] == 'Example Air'
    assert s.snapshot(t+40)['stats']['models'] == 1


def test_api_failure_backs_off_all_lookups(tmp_path):
    s = state(tmp_path)
    t = time.time()
    ingest(s, t, plane(), plane('DEF456'))
    with patch('plane_tracker.web.state.fetch_plane_info', return_value={'last_api_error': t}) as fetch:
        s._metadata_once(t)
        s._metadata_once(t+1)
        assert fetch.call_count == 1
    assert s.snapshot(t)['stats']['unknownOperators'] == 2


def test_day_persists_and_midnight_resets_even_without_receiver(tmp_path):
    from datetime import datetime, timedelta
    s = state(tmp_path)
    t = time.time()
    ingest(s, t, plane(alt_baro=35000), plane('DEF456', alt_baro=24000))
    s.save_daily()
    restarted = state(tmp_path)
    assert restarted.snapshot(t)['stats']['total'] == 2
    ingest(restarted, t+1, plane(alt_baro=10000))
    assert restarted.snapshot(t+1)['stats']['highest'] == 35000
    tomorrow = datetime.combine(datetime.fromtimestamp(t).date()+timedelta(days=1), datetime.min.time()).timestamp()
    assert restarted.snapshot(tomorrow)['stats']['total'] == 0
    restarted.save_daily()
    content = (tmp_path/'web_stats'/'current_day.csv').read_text()
    assert 'ABC123' not in content


def test_hits_persist_without_importing_legacy_messages_and_graphs_sample(tmp_path):
    s = state(tmp_path)
    t = time.time()
    s.history['ABC123'] = {'messages': '999999'}
    ingest(s, t, plane(messages=999999, alt_baro=12000))
    s.save_daily()
    restored = state(tmp_path)
    same = plane(messages=1000000, alt_baro=13000); same['seen_pos'] = 1
    ingest(restored, t+1, same)
    assert restored.snapshot(t+1)['aircraft'][0]['positionHits'] == 1
    ingest(restored, t+61, plane(messages=1500000, alt_baro=14000))
    snap = restored.snapshot(t+61)
    assert snap['stats']['maxHits'] == 2
    assert len(snap['history']) == 2
    assert snap['history'][-1]['altitude'] == 14000
    assert snap['history'][-1]['hits'] == 1


def test_nearby_hourly_unique_radius_and_restart(tmp_path):
    from datetime import datetime
    s = state(tmp_path)
    t = datetime.now().replace(minute=0, second=0, microsecond=0).timestamp()+10
    ingest(s, t, plane(lat=.1), plane('DEF456', lat=.2))
    ingest(s, t+1, plane(lat=.1))
    assert s.snapshot(t+1)['nearbyHourly'][0]['nearby'] == 1
    s.save_daily()
    restored = state(tmp_path)
    assert restored.snapshot(t+1)['nearbyHourly'][0]['nearby'] == 1
    assert restored.snapshot(t+1)['stats']['total'] == 2


def test_aircraft_graphs_do_not_mix_targets(tmp_path):
    s = state(tmp_path)
    t = time.time()
    ingest(s,t,plane(alt_baro=10000),plane('DEF456',alt_baro=20000))
    ingest(s,t+59,plane(alt_baro=11000))
    ingest(s,t+60,plane(alt_baro=12000),plane('DEF456',alt_baro=21000))
    planes = {p['icao']:p for p in s.snapshot(t+60)['aircraft']}
    assert planes['ABC123']['history'][-1]['altitude'] == 12000
    assert planes['ABC123']['history'][-1]['hits'] == 2
    assert planes['DEF456']['history'][-1]['altitude'] == 21000
    assert planes['DEF456']['history'][-1]['hits'] == 1


def test_graphs_capture_changes_between_minute_samples(tmp_path):
    s = state(tmp_path)
    t = time.time()
    ingest(s, t, plane(alt_baro=10000))
    ingest(s, t+1, plane(alt_baro=10100), plane('DEF456', alt_baro=20000))
    snap = s.snapshot(t+1)
    assert [(p['active'], p['total']) for p in snap['history']] == [(1, 1), (2, 2)]
    aircraft = {p['icao']: p for p in snap['aircraft']}
    assert [p['altitude'] for p in aircraft['ABC123']['history']] == [10000, 10100]
    ingest(s, t+2, plane(alt_baro=10100), plane('DEF456', alt_baro=20000))
    assert len(s.snapshot(t+2)['history']) == 2
    assert len(s.aircraft_history['ABC123']) == 3
    ingest(s, t+33, plane(alt_baro=10200))
    assert s.snapshot(t+33)['history'][-1]['active'] == 1
    assert s.snapshot(t+33)['history'][-1]['total'] == 2
    assert s.aircraft_history['ABC123'][-1]['altitude'] == 10200

def test_polar_counts_only_new_positions_within_one_minute(tmp_path):
    s = state(tmp_path)
    t = time.time()
    ingest(s, t, plane(messages=10000))
    ingest(s, t+1, {**plane(messages=20000), 'seen_pos': 1})
    assert s.snapshot(t+1)['polar']['total'] == 1
    ingest(s, t+2, plane(messages=30000), plane('DEF456', lat=None, lon=None))
    assert s.snapshot(t+2)['polar']['total'] == 2
    assert s.snapshot(t+2)['polar']['windowSeconds'] == 60
    assert s.snapshot(t+60)['polar']['total'] == 1
    assert s.snapshot(t+62)['polar']['total'] == 0


def test_metadata_retries_unknown_and_partial_results_fairly(tmp_path):
    s = state(tmp_path)
    t = time.time()
    s.metadata['ABC123'] = dict(manufacturer='Unknown', model='Unknown', owner='N/A', registration='null')
    ingest(s, t, plane(), plane('DEF456'))
    with patch('plane_tracker.web.state.fetch_plane_info', return_value={'last_api_error': t}) as fetch:
        s._metadata_once(t)
        assert fetch.call_args.args == ('ABC123',)
    ingest(s, t+61, plane(), plane('DEF456'))
    with patch('plane_tracker.web.state.fetch_plane_info', return_value={'manufacturer': 'Airbus'}) as fetch:
        s._metadata_once(t+61)
        assert fetch.call_args.args == ('DEF456',)
    assert s.lookup_after['DEF456'] == t+361
    with patch('plane_tracker.web.state.fetch_plane_info', return_value=None):
        s._metadata_once(t+62)
    assert s.lookup_after['ABC123'] == t+362
    ingest(s, t+363, plane(), plane('DEF456'))
    details = dict(manufacturer='Airbus', model='A320', owner='Example Air', registration='G-TEST')
    with patch('plane_tracker.web.state.fetch_plane_info', return_value=details):
        s._metadata_once(t+363)
        s._metadata_once(t+364)
    assert s.snapshot(t+364)['stats']['unknownOperators'] == 0
    assert s.snapshot(t+364)['stats']['unknownModels'] == 0
