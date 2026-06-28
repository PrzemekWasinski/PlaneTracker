#  Options: "daily" | "weekly" | "monthly" | "all_time"
MODE = "daily"

import os
import glob
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from datetime import date, timedelta

HISTORY_DIR = os.path.dirname(os.path.abspath(__file__))

PALETTE = [
    "#5B8BD1", "#E87040", "#4CAF50", "#9C6BDE", "#E8B840",
    "#E05C7F", "#40B8E8", "#7FBF7F", "#BF7F40", "#7F7FBF",
    "#D1A05B", "#50C8B0",
]

CATEGORY_LABELS = {
    "A1": "Light",      "A2": "Small",       "A3": "Large",
    "A4": "High Vortex","A5": "Heavy",       "A6": "High Perf.",
    "A7": "Rotorcraft", "B1": "Glider",      "B2": "Balloon",
    "B4": "Skydiver",   "C1": "Surface Veh.","C2": "Service Veh.",
    "C3": "Fixed Obst.","D1": "UAV",         "D8": "Space",
}


#Data loading

def csv_path(d: date) -> str:
    return os.path.join(HISTORY_DIR, f"{d}.csv")


def collect_files(mode: str) -> list[str]:
    today = date.today()
    if mode == "daily":
        p = csv_path(today)
        if os.path.exists(p):
            return [p]
        # fall back to most recent file
        all_files = sorted(glob.glob(os.path.join(HISTORY_DIR, "????-??-??.csv")))
        return [all_files[-1]] if all_files else []
    if mode == "weekly":
        return [csv_path(today - timedelta(days=i)) for i in range(7)
                if os.path.exists(csv_path(today - timedelta(days=i)))]
    if mode == "monthly":
        return [csv_path(today - timedelta(days=i)) for i in range(30)
                if os.path.exists(csv_path(today - timedelta(days=i)))]
    if mode == "all_time":
        return sorted(glob.glob(os.path.join(HISTORY_DIR, "????-??-??.csv")))
    raise ValueError(f"Unknown mode: {mode!r}")


NUMERIC_COLS = [
    "altitude", "alt_geom", "speed", "mach", "baro_rate", "geom_rate",
    "ias", "tas", "lat", "lon", "messages", "rssi", "roll", "oat", "tat",
]


def load_data(files: list[str]) -> pd.DataFrame:
    parts = []
    for f in files:
        try:
            parts.append(pd.read_csv(f, low_memory=False))
        except Exception as e:
            print(f"  Warning: could not read {f}: {e}")
    if not parts:
        raise FileNotFoundError("No valid CSV data found.")
    df = pd.concat(parts, ignore_index=True)

    # Coerce numeric columns — raw data uses '-' for missing
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].replace("-", pd.NA), errors="coerce")

    # Parse timestamps
    for col in ("first_seen", "last_seen"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # Clean string columns
    for col in ("owner", "manufacturer", "model", "category", "emergency", "registration"):
        if col in df.columns:
            df[col] = df[col].replace(["-", "none", "None", ""], pd.NA)

    # Deduplicate across days
    if "icao" in df.columns and "first_seen" in df.columns:
        df = df.drop_duplicates(subset=["icao", "first_seen"])

    return df


#Plot helpers

def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(labelsize=7)


def plot_top_bar(ax, series: pd.Series, title: str, color: str, top_n: int = 10):
    data = series.dropna().value_counts().head(top_n).sort_values()
    if data.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontweight="bold", pad=6)
        return
    bars = ax.barh(data.index, data.values, color=color, edgecolor="none", height=0.7)
    ax.set_title(title, fontweight="bold", pad=6, fontsize=9)
    ax.set_xlabel("Count", fontsize=7)
    for bar, val in zip(bars, data.values):
        ax.text(bar.get_width() + max(data.values) * 0.01,
                bar.get_y() + bar.get_height() / 2,
                str(val), va="center", fontsize=6.5)
    ax.set_xlim(0, data.values.max() * 1.18)
    _style(ax)


def plot_pie(ax, series: pd.Series, title: str, min_pct: float = 2.0):
    data = series.dropna().value_counts()
    if data.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontweight="bold", pad=6)
        return
    total = data.sum()
    small = data[data / total * 100 < min_pct]
    if len(small) > 1:
        data = data[data / total * 100 >= min_pct]
        data["Other"] = small.sum()
    colors = PALETTE[: len(data)]
    wedges, texts, autotexts = ax.pie(
        data.values, labels=data.index, autopct="%1.1f%%",
        colors=colors, startangle=90,
        wedgeprops={"linewidth": 0.5, "edgecolor": "white"},
        textprops={"fontsize": 6.5},
    )
    for at in autotexts:
        at.set_fontsize(6)
    ax.set_title(title, fontweight="bold", pad=6, fontsize=9)


def plot_histogram(ax, series: pd.Series, title: str, color: str, xlabel: str,
                   bins: int = 25, log_y: bool = False):
    data = series.dropna()
    if data.empty:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontweight="bold", pad=6)
        return
    ax.hist(data, bins=bins, color=color, edgecolor="white", linewidth=0.3)
    if log_y:
        ax.set_yscale("log")
    ax.set_title(title, fontweight="bold", pad=6, fontsize=9)
    ax.set_xlabel(xlabel, fontsize=7)
    ax.set_ylabel("Count", fontsize=7)
    _style(ax)


def plot_hourly(ax, df: pd.DataFrame, title: str):
    if "first_seen" not in df.columns or df["first_seen"].isna().all():
        ax.text(0.5, 0.5, "No timestamp data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontweight="bold", pad=6)
        return
    df = df.dropna(subset=["first_seen"])
    hourly = df["first_seen"].dt.hour.value_counts().sort_index().reindex(range(24), fill_value=0)
    ax.bar(hourly.index, hourly.values, color=PALETTE[0], edgecolor="white", linewidth=0.3)
    ax.set_title(title, fontweight="bold", pad=6, fontsize=9)
    ax.set_xlabel("Hour of Day (UTC)", fontsize=7)
    ax.set_ylabel("Flights Observed", fontsize=7)
    ax.set_xticks(range(0, 24, 2))
    _style(ax)


def plot_alt_bands(ax, df: pd.DataFrame, title: str):
    if "altitude" not in df.columns:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontweight="bold", pad=6)
        return
    bins = [0, 5000, 10000, 18000, 28000, 38000, 55000, float("inf")]
    labels = ["<5k", "5-10k", "10-18k", "18-28k", "28-38k", "38-55k", "55k+"]
    data = pd.cut(df["altitude"].dropna(), bins=bins, labels=labels)
    counts = data.value_counts().reindex(labels, fill_value=0)
    bars = ax.bar(counts.index, counts.values, color=PALETTE[4], edgecolor="white", linewidth=0.3)
    ax.set_title(title, fontweight="bold", pad=6, fontsize=9)
    ax.set_xlabel("Altitude Band (ft)", fontsize=7)
    ax.set_ylabel("Count", fontsize=7)
    for bar, val in zip(bars, counts.values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + counts.values.max() * 0.01,
                    str(val), ha="center", fontsize=6.5)
    _style(ax)


def plot_climb_descent(ax, df: pd.DataFrame, title: str):
    if "baro_rate" not in df.columns:
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        ax.set_title(title, fontweight="bold", pad=6)
        return
    data = df["baro_rate"].dropna()
    bins = [-float("inf"), -500, -64, 64, 500, float("inf")]
    labels = ["Descending", "Slow Descent", "Level", "Slow Climb", "Climbing"]
    cats = pd.cut(data, bins=bins, labels=labels)
    counts = cats.value_counts().reindex(labels, fill_value=0)
    colors_vr = [PALETTE[1], "#F5A070", PALETTE[2], "#70C870", PALETTE[0]]
    bars = ax.bar(counts.index, counts.values, color=colors_vr, edgecolor="white", linewidth=0.3)
    ax.set_title(title, fontweight="bold", pad=6, fontsize=9)
    ax.set_xlabel("Vertical State", fontsize=7)
    ax.set_ylabel("Count", fontsize=7)
    ax.tick_params(axis="x", labelsize=6.5)
    for bar, val in zip(bars, counts.values):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + counts.values.max() * 0.01,
                    str(val), ha="center", fontsize=6.5)
    _style(ax)


def plot_summary(ax, df: pd.DataFrame, mode: str, files_count: int):
    ax.axis("off")
    total       = len(df)
    airlines    = df["owner"].nunique() if "owner" in df.columns else 0
    models      = df["model"].nunique() if "model" in df.columns else 0
    mfrs        = df["manufacturer"].nunique() if "manufacturer" in df.columns else 0
    emergencies = (df["emergency"].notna()).sum() if "emergency" in df.columns else 0
    avg_alt     = df["altitude"].mean() if "altitude" in df.columns else 0
    max_alt     = df["altitude"].max() if "altitude" in df.columns else 0
    avg_speed   = df["speed"].mean() if "speed" in df.columns else 0
    max_speed   = df["speed"].max() if "speed" in df.columns else 0
    avg_mach    = df["mach"].mean() if "mach" in df.columns else 0

    mode_label = {"daily": "Today", "weekly": "Last 7 Days",
                  "monthly": "Last 30 Days", "all_time": "All Time"}.get(mode, mode)

    lines = [
        f"  {mode_label}",
        "",
        f"  Total Flights     {total:>8,}",
        f"  Unique Airlines   {airlines:>8,}",
        f"  Unique Models     {models:>8,}",
        f"  Manufacturers     {mfrs:>8,}",
        f"  Emergencies       {emergencies:>8,}",
        "",
        f"  Avg Altitude      {avg_alt:>7,.0f} ft",
        f"  Max Altitude      {max_alt:>7,.0f} ft",
        f"  Avg Speed         {avg_speed:>7,.0f} kts",
        f"  Max Speed         {max_speed:>7,.0f} kts",
        f"  Avg Mach          {avg_mach:>10.3f}",
        "",
        f"  Files loaded      {files_count:>8}",
    ]
    text = "\n".join(lines)
    ax.text(0.05, 0.97, text, transform=ax.transAxes, va="top",
            fontsize=9, fontfamily="monospace",
            bbox=dict(boxstyle="round,pad=0.6", facecolor="#EEF2FF",
                      edgecolor="#99AADD", linewidth=1.2))
    ax.set_title("Summary", fontweight="bold", pad=6, fontsize=9)


#Main 

def main():
    print(f"[stats] Mode: {MODE}")
    files = collect_files(MODE)
    if not files:
        print(f"Error: no CSV files found for mode '{MODE}' in {HISTORY_DIR}")
        return
    print(f"[stats] Loading {len(files)} file(s)…")
    df = load_data(files)
    print(f"[stats] {len(df):,} flight records loaded")

    df["cat_label"] = df["category"].map(CATEGORY_LABELS).fillna(df.get("category", pd.Series(dtype=str)))

    fig = plt.figure(figsize=(22, 16), facecolor="#F8F9FA")
    mode_label = {"daily": "Today", "weekly": "Last 7 Days",
                  "monthly": "Last 30 Days", "all_time": "All Time"}.get(MODE, MODE)
    fig.suptitle(f"Flight Statistics — {mode_label}",
                 fontsize=20, fontweight="bold", y=0.99, color="#1A1A2E")

    gs = gridspec.GridSpec(3, 4, figure=fig, hspace=0.60, wspace=0.48,
                           top=0.94, bottom=0.06, left=0.06, right=0.97)

    #Row 0 ──
    ax_airlines = fig.add_subplot(gs[0, 0])
    ax_models   = fig.add_subplot(gs[0, 1])
    ax_mfr      = fig.add_subplot(gs[0, 2])
    ax_cat      = fig.add_subplot(gs[0, 3])

    plot_top_bar(ax_airlines, df["owner"],       "Top 10 Airlines",        PALETTE[0])
    plot_top_bar(ax_models,   df["model"],        "Top 10 Aircraft Models", PALETTE[1])
    plot_pie(ax_mfr,          df["manufacturer"], "Manufacturers")
    plot_top_bar(ax_cat,      df["cat_label"],    "Aircraft Categories",    PALETTE[3], top_n=8)

    #Row 1 ──
    ax_alt_bands = fig.add_subplot(gs[1, 0])
    ax_speed     = fig.add_subplot(gs[1, 1])
    ax_mach      = fig.add_subplot(gs[1, 2])
    ax_vr        = fig.add_subplot(gs[1, 3])

    plot_alt_bands(   ax_alt_bands, df, "Altitude Bands")
    plot_histogram(   ax_speed,     df["speed"], "Speed Distribution", PALETTE[2], "Speed (kts)")
    plot_histogram(   ax_mach,      df["mach"],  "Mach Distribution",  PALETTE[5], "Mach Number", bins=20)
    plot_climb_descent(ax_vr,       df,          "Climb / Descent State")

    #Row 2 ──
    ax_hourly  = fig.add_subplot(gs[2, 0:3])
    ax_summary = fig.add_subplot(gs[2, 3])

    plot_hourly( ax_hourly,  df, "Hourly Traffic (UTC)")
    plot_summary(ax_summary, df, MODE, len(files))

    fig.patch.set_linewidth(0)
    plt.show()


if __name__ == "__main__":
    main()
