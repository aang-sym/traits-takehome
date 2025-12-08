"""
Helper functions for exploratory data analysis.

These functions process raw tracking data (nested JSONL structure)
and calculate player-level metrics like distance and speed.
"""

import pandas as pd
import numpy as np
from typing import Optional

# Constants
TRACKING_FPS = 10  # Frames per second
METERS_TO_KM = 1000
SECONDS_TO_HOURS = 3600


def explode_player_tracking(tracking_df: pd.DataFrame) -> pd.DataFrame:
    """
    Flatten nested player_data from tracking DataFrame.
    Returns one row per player per frame.
    """
    rows = []

    for idx, row in tracking_df.iterrows():
        frame = row["frame"]
        timestamp = row["timestamp"]
        period = row["period"]

        # player_data is a list of dicts
        if isinstance(row["player_data"], list):
            for player in row["player_data"]:
                if isinstance(player, dict):
                    rows.append(
                        {
                            "frame": frame,
                            "timestamp": timestamp,
                            "period": period,
                            "player_id": player.get("player_id"),
                            "x": player.get("x"),
                            "y": player.get("y"),
                            "is_detected": player.get("is_detected"),
                        }
                    )

    return pd.DataFrame(rows)


def calculate_distances(player_tracking: pd.DataFrame) -> pd.Series:
    """
    Calculate Euclidean distance between consecutive frames.
    Returns distances in meters (NaN for first frame).
    
    Note: Sorted by frame first, otherwise distances will be wrong.
    """
    # Sort by frame to ensure chronological order
    sorted_df = player_tracking.sort_values("frame").copy()

    # Calculate position differences
    dx = sorted_df["x"].diff()
    dy = sorted_df["y"].diff()

    # Euclidean distance
    distances = np.sqrt(dx**2 + dy**2)

    return distances


def calculate_speeds(
    player_tracking: pd.DataFrame, fps: int = TRACKING_FPS
) -> pd.Series:
    """
    Calculate instantaneous speed (km/h) from position deltas.
    
    Note: Gaps in tracking may cause spikes - filter those out upstream.
    """
    distances = calculate_distances(player_tracking)

    # Time between frames in seconds
    time_delta = 1.0 / fps

    # Speed in m/s, convert to km/h
    speeds_ms = distances / time_delta
    speeds_kmh = speeds_ms * (SECONDS_TO_HOURS / METERS_TO_KM)  # * 3.6

    return speeds_kmh


def get_player_summary(
    player_tracking: pd.DataFrame,
    player_id: int,
    minutes_played_lookup: dict[int, float] | None = None,
    fps: int = 10,
) -> dict:
    """
    Calculate summary stats for a single player: distance, avg/max speed, minutes.
    Uses official minutes_played from metadata if available, falls back to tracking.
    """

    player_data = player_tracking[player_tracking["player_id"] == player_id].copy()

    if len(player_data) == 0:
        return {
            "player_id": player_id,
            "distance_km": 0.0,
            "avg_speed_kmh": 0.0,
            "max_speed_kmh": 0.0,
            "frames_tracked": 0,
            "minutes_played": 0.0,
        }

    distances = calculate_distances(player_data)
    speeds = calculate_speeds(player_data)

    # Filter out NaNs and obviously impossible speeds
    valid_speeds = speeds[(speeds > 0) & (speeds < 40)]

    # Minutes played from metadata if available, else from tracking
    if minutes_played_lookup and player_id in minutes_played_lookup:
        minutes_played = minutes_played_lookup[player_id]
    else:
        on_pitch_frames = player_data["is_detected"].fillna(False).sum()
        minutes_played = on_pitch_frames / (fps * 60)

    total_distance_km = distances.sum() / METERS_TO_KM
    hours_played = minutes_played / 60
    avg_speed_kmh = total_distance_km / hours_played if hours_played > 0 else 0.0

    return {
        "player_id": player_id,
        "distance_km": total_distance_km,
        "avg_speed_kmh": avg_speed_kmh,
        # Use robust max instead of raw single-frame max
        "max_speed_kmh": clean_max_speed_kmh(valid_speeds),
        "frames_tracked": len(player_data),
        "minutes_played": minutes_played,
    }
    
def clean_max_speed_kmh(
    speeds: pd.Series,
    window: int = 3,
    upper_cap: float = 40.0,
    quantile: float = 0.99,
) -> float:
    """
    Robust max sprint speed using rolling median and 99th percentile.
    Filters to realistic range (0-40 km/h) to avoid single-frame spikes.
    """
    if speeds is None:
        return 0.0

    valid = speeds.dropna()
    valid = valid[(valid > 0) & (valid < upper_cap)]

    if valid.empty:
        return 0.0

    smoothed = valid.rolling(window=window, center=True, min_periods=1).median()

    # Use a high percentile to mirror the idea behind psv99 and
    # avoid single-frame outliers.
    return float(smoothed.quantile(quantile))


def enrich_with_physical(df: pd.DataFrame,
                         physical_context: pd.DataFrame,
                         cols: list[str]) -> pd.DataFrame:
    """Merge per-player dataframe with physical aggregates on player_id.

    Excludes players for whom all requested physical columns are NaN.
    """
    cols_to_keep = ["player_id"] + cols

    context_trimmed = (
        physical_context[cols_to_keep]
        .drop_duplicates("player_id")  # <- one row per player_id
    )

    merged = df.merge(context_trimmed, on="player_id", how="left")

    # Identify players with no physical aggregates in the requested cols
    missing_mask = merged[cols].isna().all(axis=1)
    missing_ids = merged.loc[missing_mask, "player_id"].unique()

    if len(missing_ids) > 0:
        print(
            f"Excluding {len(missing_ids)} players with no physical aggregates: "
            f"{list(missing_ids)}"
        )

    return merged.loc[~missing_mask].copy()

def sample_players_by_position(
    physical_context: pd.DataFrame,
    player_tracking: pd.DataFrame,
    n_per_group: int = 2,
) -> list[int]:
    """
    Return up to n_per_group player_ids per position_group that
    actually appear in the given match tracking data.
    """
    return (
        physical_context[["player_id", "position_group"]]
        .dropna(subset=["position_group"])
        .drop_duplicates("player_id")
        .merge(
            player_tracking[["player_id"]].drop_duplicates(),
            on="player_id",
            how="inner",
        )
        .sort_values(["position_group", "player_id"])
        .groupby("position_group")
        .head(n_per_group)["player_id"]
        .tolist()
    )
    
def summarise_match_distance(
    player_tracking: pd.DataFrame,
    player_ids: list[int],
    match_meta: dict | None = None,
    fps: int = 10,
) -> pd.DataFrame:
    """
    Compute total distance and metres-per-minute for each player using
    official minutes_played from match metadata when available, falling
    back to tracking-derived minutes if needed.
    """

    # Build lookup only if metadata provided
    minutes_played_lookup = {}
    if match_meta is not None:
        minutes_played_lookup = {
            p["id"]: p.get("playing_time", {}).get("total", {}).get("minutes_played")
            for p in match_meta.get("players", [])
            if p.get("playing_time") and p["playing_time"].get("total")
        }

    rows = []

    for pid in player_ids:
        df_player = player_tracking[player_tracking["player_id"] == pid]
        if df_player.empty:
            continue

        dists = calculate_distances(df_player)
        total_distance_m = dists.sum()

        # Prefer official minutes played
        minutes_match = minutes_played_lookup.get(pid)

        # Fallback to tracking frames
        if minutes_match is None:
            frames_detected = df_player["is_detected"].fillna(False).sum()
            minutes_match = frames_detected / (fps * 60)

        meters_per_min = (
            total_distance_m / minutes_match if minutes_match > 0 else np.nan
        )

        rows.append({
            "player_id": pid,
            "total_distance_m_match": total_distance_m,
            "total_distance_km_match": total_distance_m / 1000,
            "meters_per_minute_match": meters_per_min,
            "minutes_match": minutes_match,
        })

    return pd.DataFrame(rows)
