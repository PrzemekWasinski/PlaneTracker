import csv
import os
import time
from datetime import datetime


def prune_history(history, max_age_seconds, now=None):
    now = now or time.time()
    cutoff = now - max_age_seconds
    while history and history[0][0] < cutoff:
        history.popleft()


def append_sample(history, value, sample_interval, now=None):
    now = now or time.time()
    if sample_interval <= 0:
        history.append((now, value))
        return

    bucket_time = int(now // sample_interval) * sample_interval
    if history and history[-1][0] == bucket_time:
        history[-1] = (bucket_time, value)
    else:
        history.append((bucket_time, value))


def append_directional_hit(history, bearing_deg, sample_interval, sector_count, now=None):
    now = now or time.time()
    sector_width = 360.0 / max(1, sector_count)
    bucket_time = int(now // sample_interval) * sample_interval if sample_interval > 0 else now
    sector_index = int((bearing_deg % 360) // sector_width) % sector_count

    if history and history[-1][0] == bucket_time:
        counts = history[-1][1]
    else:
        counts = [0] * sector_count
        history.append((bucket_time, counts))

    counts[sector_index] += 1


def aggregate_directional_hits(history, sector_count, now=None, time_window_seconds=24 * 60 * 60):
    now = now or time.time()
    cutoff = now - time_window_seconds
    totals = [0] * sector_count

    for timestamp, counts in history:
        if timestamp < cutoff:
            continue
        for index, count in enumerate(counts[:sector_count]):
            totals[index] += count

    return totals


def get_top_graph_history_path(history_dir, now=None):
    return os.path.join(history_dir, 'graph_history.csv')


def load_top_graph_history(active_count_history, total_seen_history, history_dir, history_seconds, now=None):
    now = now or time.time()
    cutoff = now - history_seconds
    history_path = get_top_graph_history_path(history_dir, now)
    active_count_history.clear()
    total_seen_history.clear()
    top_graph_last_bucket = None

    if not os.path.exists(history_path):
        return top_graph_last_bucket

    try:
        with open(history_path, 'r', newline='', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                try:
                    bucket_time = datetime.strptime(row['timestamp'], '%Y-%m-%d %H:%M:%S').timestamp()
                    active_value = int(row['active_count'])
                    total_value = int(row['total_seen'])
                except (KeyError, TypeError, ValueError):
                    continue

                if bucket_time < cutoff:
                    continue

                active_count_history.append((bucket_time, active_value))
                total_seen_history.append((bucket_time, total_value))

        if active_count_history:
            top_graph_last_bucket = active_count_history[-1][0]
    except (FileNotFoundError, PermissionError, OSError, csv.Error):
        pass

    prune_history(active_count_history, history_seconds, now)
    prune_history(total_seen_history, history_seconds, now)
    return top_graph_last_bucket


def clear_top_graph_history(history_dir, now=None):
    history_path = get_top_graph_history_path(history_dir, now)
    lock_path = history_path + '.lock'

    try:
        if os.path.exists(history_path):
            os.remove(history_path)
        if os.path.exists(lock_path):
            os.remove(lock_path)
        return True
    except OSError:
        return False


def persist_top_graph_sample(active_count_history, total_seen_history, active_count, total_seen, history_dir, top_graph_last_bucket, sample_interval, history_seconds, now=None):
    now = now or time.time()
    bucket_time = int(now // sample_interval) * sample_interval
    history_path = get_top_graph_history_path(history_dir, now)

    append_sample(active_count_history, active_count, sample_interval, now)
    prune_history(active_count_history, history_seconds, now)
    append_sample(total_seen_history, total_seen, sample_interval, now)
    prune_history(total_seen_history, history_seconds, now)

    if top_graph_last_bucket == bucket_time:
        return top_graph_last_bucket

    try:
        os.makedirs(history_dir, exist_ok=True)
        file_exists = os.path.exists(history_path)

        with open(history_path, 'a', newline='', encoding='utf-8') as file:
            fieldnames = ['timestamp', 'active_count', 'total_seen']
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow({
                'timestamp': datetime.fromtimestamp(bucket_time).strftime('%Y-%m-%d %H:%M:%S'),
                'active_count': int(active_count),
                'total_seen': int(total_seen),
            })
    except (PermissionError, OSError, csv.Error):
        return top_graph_last_bucket

    return bucket_time

