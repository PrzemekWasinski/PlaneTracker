import bisect
import csv
import os

_COLOURS = [
    None,
    (255, 255, 255),  # 1  - white
    (255, 255, 255),  # 2  - white
    (255, 255, 255),  # 3  - white
    (0, 255, 0),      # 4  - green
    (0, 255, 0),      # 5  - green
    (255, 255, 0),    # 6  - yellow
    (255, 255, 0),    # 7  - yellow
    (255, 0, 0),      # 8  - red
    (255, 0, 0),      # 9  - red
    (255, 0, 255),    # 10 - magenta
]


def _percentile_to_rating(p):
    # p=1.0 → most common in history, p=0.0 → rarest in history
    if p >= 0.90: return 1   # white  – top 10% most common
    if p >= 0.50: return 4   # green  – above median (50th–90th)
    if p >= 0.20: return 6   # yellow – below median (20th–50th)
    if p >= 0.05: return 8   # red    – rare (5th–20th)
    return 10                # magenta – very rare / unseen


def build_model_counts(history_dir='./flight_history'):
    counts = {}
    if not os.path.isdir(history_dir):
        return counts
    for fname in sorted(os.listdir(history_dir)):
        if not fname.endswith('.csv'):
            continue
        fpath = os.path.join(history_dir, fname)
        try:
            with open(fpath, 'r', newline='', encoding='utf-8') as f:
                for row in csv.DictReader(f):
                    model = (row.get('model') or '').strip()
                    if model and model != '-':
                        counts[model] = counts.get(model, 0) + 1
        except Exception:
            continue
    return counts


def compute_ratings(model_counts):
    """Rank every model by percentile within the known distribution → rating 1–10."""
    if not model_counts:
        return {}
    sorted_counts = sorted(model_counts.values())
    n = len(sorted_counts)
    ratings = {}
    for model, count in model_counts.items():
        lo = bisect.bisect_left(sorted_counts, count)
        hi = bisect.bisect_right(sorted_counts, count)
        percentile = (lo + hi) / 2 / n  # midpoint handles ties: all equal → 0.5
        ratings[model] = _percentile_to_rating(percentile)
    return ratings


def get_rarity_rating(model, model_ratings):
    if not model or model == '-':
        return 1
    return model_ratings.get(model, 10)  # never seen in history → rarest


def get_rarity_colour(rating):
    return _COLOURS[max(1, min(10, int(rating)))]
