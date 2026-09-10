import bisect
import csv
import os

_COLOURS = [
    None,
    (255, 255, 255),
    (255, 255, 255),
    (255, 255, 255),
    (255, 255, 0),
    (255, 255, 0),
    (0, 255, 0),
    (0, 255, 0),
    (255, 0, 0),
    (255, 0, 0),
    (255, 0, 255),
]


#Map model frequency percentiles to display tiers
def _percentile_to_rating(p):

    if p >= 0.93: return 1
    if p >= 0.88: return 4
    if p >= 0.70: return 6
    if p >= 0.10: return 8
    return 10


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
    if not model_counts:
        return {}
    sorted_counts = sorted(model_counts.values())
    n = len(sorted_counts)
    ratings = {}
    for model, count in model_counts.items():
        lo = bisect.bisect_left(sorted_counts, count)
        hi = bisect.bisect_right(sorted_counts, count)
        percentile = (lo + hi) / 2 / n
        ratings[model] = _percentile_to_rating(percentile)
    return ratings


def get_rarity_rating(model, model_ratings):
    if not model or model == '-':
        return 1
    return model_ratings.get(model, 10)


def get_rarity_colour(rating):
    return _COLOURS[max(1, min(10, int(rating)))]
