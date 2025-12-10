"""
Helper functions for calculating player performance metrics.

This module provides functions for:
- Sprint detection from tracking data
- Phase enrichment for tactical context
- PySpark aggregations for player-level metrics
"""

import pandas as pd
import numpy as np
from pyspark.sql import DataFrame as SparkDataFrame
from pyspark.sql import functions as F
from src.eda import explode_player_tracking, calculate_distances

TRACKING_FPS = 10
SPRINT_THRESHOLD_KMH = 24.5
MAX_PHYSICAL_SPEED_KMH = 36.0
TELEPORT_THRESHOLD_M = 1.5  # >1.5m per frame ≈ teleport at 10fps


def detect_sprints(
    tracking_df: pd.DataFrame,
    match_id: str,
    fps: int = TRACKING_FPS,
    threshold_kmh: float = SPRINT_THRESHOLD_KMH,
) -> pd.DataFrame:
    """
    Detect discrete sprint events from tracking data.
    
    Conservative approach:
    - Heavy smoothing to remove artifacts
    - Realistic speed caps based on PSV99 data
    - Strict validation of sprint characteristics
    """
    
    player_frames = explode_player_tracking(tracking_df)
    player_frames = player_frames.sort_values(["player_id", "frame"]).reset_index(drop=True)

    sprints_list = []
    smooth_window = 11  # Longer window for more aggressive smoothing

    for player_id in player_frames["player_id"].dropna().unique():
        pdf = player_frames[player_frames["player_id"] == player_id].copy()
        if len(pdf) < smooth_window:
            continue

        # Calculate distances and speeds
        distances = calculate_distances(pdf)
        
        # Remove teleports (>1.0m per frame = >36 km/h)
        teleport_mask = distances > 1.0
        distances = distances.mask(teleport_mask, np.nan)
        
        # Convert to km/h
        speeds_ms = distances * fps
        speeds_kmh = speeds_ms * 3.6
        
        # First pass: cap at 32 km/h (reasonable PSV99 range)
        speeds_kmh = speeds_kmh.clip(upper=32.0)
        
        # Heavy smoothing: rolling median then rolling mean
        speeds_smooth = (
            speeds_kmh.rolling(window=smooth_window, center=True, min_periods=1)
            .median()
        )
        speeds_smooth = (
            speeds_smooth.rolling(window=7, center=True, min_periods=1)
            .mean()
        )
        
        pdf["speed_smooth"] = speeds_smooth
        
        # Detect sprint frames
        pdf["is_sprinting"] = pdf["speed_smooth"].fillna(0) >= threshold_kmh
        
        # Group consecutive sprint frames
        pdf["sprint_group"] = (
            pdf["is_sprinting"] != pdf["is_sprinting"].shift()
        ).cumsum()
        
        sprint_groups = pdf[pdf["is_sprinting"]].groupby("sprint_group")
        
        for _, sprint in sprint_groups:
            if len(sprint) < 6:  # Minimum 0.6s
                continue
            
            frame_start = int(sprint["frame"].min())
            frame_end = int(sprint["frame"].max())
            mid_frame = int((frame_start + frame_end) / 2)
            
            duration_s = (frame_end - frame_start + 1) / fps
            
            # Get smoothed speeds for this sprint
            sprint_speeds = sprint["speed_smooth"].dropna()
            if sprint_speeds.empty or len(sprint_speeds) < 4:
                continue
            
            # Use conservative percentiles
            avg_speed_kmh = float(sprint_speeds.mean())
            max_speed_kmh = float(sprint_speeds.quantile(0.90))  # 90th percentile
            
            # Distance from average speed
            distance_m = (avg_speed_kmh / 3.6) * duration_s
            
            # Realistic validation based on PSV99 data:
            # - Average sprint speed should be 25-29 km/h (sustained effort)
            # - Max sprint speed should be 26-31 km/h (brief peak)
            if avg_speed_kmh < 24.5 or avg_speed_kmh > 29:
                continue
            if max_speed_kmh < 26.0 or max_speed_kmh > 33.0:
                continue
            if distance_m < 7.0:  # Meaningful sprint distance, as SkillCorner defines sprint velocity as 7 m/s
                continue
            
            sprints_list.append({
                "match_id": match_id,
                "player_id": player_id,
                "frame_start": frame_start,
                "frame_end": frame_end,
                "mid_frame": mid_frame,
                "duration_s": duration_s,
                "distance_m": distance_m,
                "avg_sprint_speed_kmh": avg_speed_kmh,
                "max_sprint_speed_kmh": max_speed_kmh,
            })
    
    sprints_df = pd.DataFrame(sprints_list)
    if not sprints_df.empty:
        sprints_df["sprint_id"] = range(len(sprints_df))
    
    return sprints_df


def enrich_sprints_with_phases(
    sprints_df: pd.DataFrame,
    phases_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Join sprints to phases using mid_frame and create tactical context flags.
    
    Adds to each sprint:
    - Phase type (build_up, create, finish, etc.)
    - Team in/out of possession
    - Shot/goal outcome flags
    - Spatial context (third, channel)
    - Derived flags (is_high_value_phase, is_attacking_sprint)
    
    Uses mid_frame to avoid edge cases where sprint spans multiple phases.
    """
    enriched_sprints = []
    
    for _, sprint in sprints_df.iterrows():
        match_id = sprint['match_id']
        mid_frame = sprint['mid_frame']
        
        # Find matching phase
        phase_match = phases_df[
            (phases_df['match_id'] == match_id) &
            (phases_df['frame_start'] <= mid_frame) &
            (phases_df['frame_end'] >= mid_frame)
        ]
        
        if len(phase_match) == 0:
            # Sprint not in any phase - keep sprint but null phase fields
            sprint_dict = sprint.to_dict()
            sprint_dict.update({
                'team_in_possession_phase_type': None,
                'team_out_of_possession_phase_type': None,
                'team_in_possession_id': None,
                'possession_lead_to_shot': False,
                'possession_lead_to_goal': False,
                'third_end': None,
                'channel_end': None,
            })
        else:
            phase = phase_match.iloc[0]
            sprint_dict = sprint.to_dict()
            sprint_dict.update({
                'team_in_possession_phase_type': phase['team_in_possession_phase_type'],
                'team_out_of_possession_phase_type': phase['team_out_of_possession_phase_type'],
                'team_in_possession_id': phase['team_in_possession_id'],
                'possession_lead_to_shot': phase.get('team_possession_lead_to_shot', False),
                'possession_lead_to_goal': phase.get('team_possession_lead_to_goal', False),
                'third_end': phase.get('third_end'),
                'channel_end': phase.get('channel_end'),
            })
        
        enriched_sprints.append(sprint_dict)
    
    enriched_df = pd.DataFrame(enriched_sprints)
    
    # Create derived flags
    high_value_phases = {'create', 'finish', 'quick_break', 'transition'}
    
    enriched_df['is_high_value_phase'] = (
        enriched_df['team_in_possession_phase_type'].isin(high_value_phases)
    )
    
    # Need team_id to determine attacking vs defensive
    # This will be added after merge with player_metadata
    
    return enriched_df


def add_sprint_context_flags(sprints_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add attacking/defensive flags after team_id is available.
    Must be called after joining with player_metadata.
    """
    sprints_df['is_attacking_sprint'] = (
        sprints_df['team_id'] == sprints_df['team_in_possession_id']
    )
    sprints_df['is_defensive_sprint'] = ~sprints_df['is_attacking_sprint']
    
    sprints_df['in_attacking_third'] = (
        sprints_df['third_end'] == 'attacking_third'
    )
    
    return sprints_df


def aggregate_player_sprints(
    sprints_sdf: SparkDataFrame,
    player_meta_sdf: SparkDataFrame,
    min_minutes: float = 30.0,
) -> SparkDataFrame:
    """
    Aggregate sprint-level data to player-level metrics using PySpark.
    
    Returns one row per player per match with:
    - Volume metrics (sprint_count, sprints_per_90, distance)
    - Context quality (high_value_sprint_pct, attacking_sprint_pct)
    - Outcome linkage (sprints_in_shot_possessions_pct)
    - Spatial metrics (sprints_in_attacking_third_pct)
    
    Args:
        sprints_sdf: Sprint events with phase context
        player_meta_sdf: Player metadata with minutes_played
        min_minutes: Minimum minutes to include player
    """
    # Group by player-match
    group_cols = ['match_id', 'player_id']
    
    player_sprints = sprints_sdf.groupBy(group_cols).agg(
        F.count('sprint_id').alias('sprint_count'),
        F.sum('distance_m').alias('sprint_distance_m'),
        F.mean('avg_sprint_speed_kmh').alias('avg_sprint_speed_kmh'),
        F.mean('max_sprint_speed_kmh').alias('max_sprint_speed_kmh'),
        
        # Context quality metrics (convert bool to int for mean)
        F.mean(F.col('is_high_value_phase').cast('int')).alias('high_value_sprint_pct'),
        F.mean(F.col('is_attacking_sprint').cast('int')).alias('attacking_sprint_pct'),
        F.mean(F.col('is_defensive_sprint').cast('int')).alias('defensive_sprint_pct'),
        
        # Outcome linkage
        F.mean(F.col('possession_lead_to_shot').cast('int')).alias('sprints_in_shot_possessions_pct'),
        F.mean(F.col('possession_lead_to_goal').cast('int')).alias('sprints_in_goal_possessions_pct'),
        
        # Spatial context
        F.mean(F.col('in_attacking_third').cast('int')).alias('sprints_in_attacking_third_pct'),
    )
    
    # Join with player metadata to get minutes_played and position
    player_sprints = player_sprints.join(
        player_meta_sdf,
        on=['match_id', 'player_id'],
        how='left'
    )
    
    # Calculate per-90 metrics
    player_sprints = player_sprints.withColumn(
        'sprints_per_90',
        (F.col('sprint_count') * 90) / F.col('minutes_played')
    )
    
    player_sprints = player_sprints.withColumn(
        'sprint_distance_per_90',
        (F.col('sprint_distance_m') * 90) / F.col('minutes_played')
    )
    
    player_sprints = player_sprints.withColumn(
        'high_value_sprints_per_90',
        F.col('sprints_per_90') * F.col('high_value_sprint_pct')
    )
    
    # Filter minimum minutes
    player_sprints = player_sprints.filter(F.col('minutes_played') >= min_minutes)
    
    # Select and order columns
    output_cols = [
        'match_id', 'player_id', 'player_short_name', 'team_id', 'team_name',
        'position_group', 'role_name', 'minutes_played',
        'sprint_count', 'sprints_per_90', 'sprint_distance_m', 'sprint_distance_per_90',
        'avg_sprint_speed_kmh', 'max_sprint_speed_kmh',
        'high_value_sprint_pct', 'attacking_sprint_pct', 'defensive_sprint_pct',
        'sprints_in_shot_possessions_pct', 'sprints_in_goal_possessions_pct',
        'sprints_in_attacking_third_pct',
        'high_value_sprints_per_90',
    ]
    
    return player_sprints.select(*output_cols)

def aggregate_off_ball_runs(
    runs_sdf: SparkDataFrame,
    player_meta_sdf: SparkDataFrame,
    min_minutes: float = 10.0,
    min_runs: int = 3,
) -> SparkDataFrame:
    """
    Aggregate off-ball runs to player-match level using PySpark.
        
    Returns volume, threat quality, and basic physical / directional metrics.
    Phase-of-play context is kept at event level only (no per-player finish/create %).
    """

    group_cols = ["match_id", "player_id"]

    player_runs = runs_sdf.groupBy(group_cols).agg(
        F.count("event_id").alias("run_count"),

        # Threat metrics
        F.mean("xthreat").alias("avg_xthreat"),
        F.max("xthreat").alias("max_xthreat"),

        # Quality / danger
        F.mean(F.col("dangerous").cast("int")).alias("high_value_run_pct"),

        # Physical & style
        F.mean("speed_avg").alias("avg_run_speed"),
        F.mean("n_opponents_overtaken").alias("avg_opponents_beaten"),

        # Simple directional breakdown via subtype (if present)
        F.mean(
            (F.col("event_subtype") == "run_ahead").cast("int")
        ).alias("runs_ahead"),
        F.mean(
            (F.col("event_subtype") == "run_behind").cast("int")
        ).alias("runs_behind"),
    )

    # Join player metadata (minutes, position, team info, etc.)
    player_runs = player_runs.join(
        player_meta_sdf,
        on=["match_id", "player_id"],
        how="left",
    )

    # Per-90 metrics
    player_runs = player_runs.withColumn(
        "runs_per_90",
        (F.col("run_count") / F.col("minutes_played")) * 90.0,
    )

    player_runs = player_runs.withColumn(
        "high_value_runs_per_90",
        F.col("runs_per_90") * F.col("high_value_run_pct"),
    )

    player_runs = player_runs.withColumn(
        "threat_per_90",
        F.col("runs_per_90") * F.col("avg_xthreat"),
    )

    # Filter out tiny samples
    player_runs = player_runs.filter(
        (F.col("minutes_played") >= min_minutes) &
        (F.col("run_count") >= min_runs)
    )

    # Final column order – only keep columns that actually exist
    desired_cols = [
        # keys
        "match_id", "player_id",

        # run metrics
        "run_count", "runs_per_90",
        "avg_xthreat", "max_xthreat", "threat_per_90",
        "high_value_run_pct", "high_value_runs_per_90",
        "avg_run_speed", "avg_opponents_beaten",
        "runs_ahead", "runs_behind",

        # metadata (will be subsetted to those that exist)
        "team_player_id", "trackable_object", "team_id", "team_name",
        "shirt_number", "player_short_name", "first_name", "last_name",
        "position_group", "role_name", "role_acronym",
        "minutes_played", "minutes_played_regular",
        "start_frame", "end_frame", "start_time", "end_time",
        "started", "yellow_card", "red_card", "goals", "own_goals",
        "injured", "birthday", "gender",
    ]

    existing_cols = [c for c in desired_cols if c in player_runs.columns]

    return player_runs.select(*existing_cols)

def aggregate_pressing_impact(
    pressing_sdf: SparkDataFrame,
    player_meta_sdf: SparkDataFrame,
    min_minutes: float = 30.0,
    min_actions: int = 3,
) -> SparkDataFrame:
    """
    Aggregate pressing actions to player-match level using PySpark.
    
    Uses actual possession outcomes:
    - direct_regain: Pressing player wins ball immediately
    - indirect_regain: Team wins ball shortly after press
    - direct/indirect_disruption: Press forces error or poor decision
    
    Success = any regain or disruption
    """
    
    group_cols = ['match_id', 'player_id']
    
    player_pressing = pressing_sdf.groupBy(group_cols).agg(
        F.count('event_id').alias('pressing_action_count'),
        
        # Regain metrics
        F.sum(F.col('direct_regain').cast('int')).alias('direct_regain_count'),
        F.sum(F.col('indirect_regain').cast('int')).alias('indirect_regain_count'),
        F.sum(F.col('any_regain').cast('int')).alias('total_regain_count'),
        F.mean(F.col('any_regain').cast('int')).alias('regain_rate'),
        
        # Disruption metrics
        F.sum(F.col('direct_disruption').cast('int')).alias('direct_disruption_count'),
        F.sum(F.col('indirect_disruption').cast('int')).alias('indirect_disruption_count'),
        F.sum(F.col('any_disruption').cast('int')).alias('total_disruption_count'),
        F.mean(F.col('any_disruption').cast('int')).alias('disruption_rate'),
        
        # Overall success
        F.sum(F.col('successful_press').cast('int')).alias('successful_press_count'),
        F.mean(F.col('successful_press').cast('int')).alias('press_success_rate'),
        
        # Outcome quality
        F.sum(F.col('lead_to_shot').cast('int')).alias('presses_leading_to_shot'),
        F.sum(F.col('lead_to_goal').cast('int')).alias('presses_leading_to_goal'),
        F.mean(F.col('lead_to_shot').cast('int')).alias('shot_creation_rate'),
        
        # Phase breakdown
        F.sum(
            F.when(F.col('team_out_of_possession_phase_type') == 'high_block', 1).otherwise(0)
        ).alias('high_block_press_count'),
        F.sum(
            F.when(F.col('team_out_of_possession_phase_type') == 'medium_block', 1).otherwise(0)
        ).alias('medium_block_press_count'),
        F.sum(
            F.when(F.col('team_out_of_possession_phase_type') == 'low_block', 1).otherwise(0)
        ).alias('low_block_press_count'),
        
        # Counter-pressing
        F.sum(
            F.when(F.col('event_subtype') == 'counter_press', 1).otherwise(0)
        ).alias('counter_press_count'),
    )
    
    # Join metadata
    player_pressing = player_pressing.join(
        player_meta_sdf,
        on=['match_id', 'player_id'],
        how='left'
    )
    
    # Per-90 metrics
    player_pressing = player_pressing.withColumn(
        'pressing_actions_per_90',
        (F.col('pressing_action_count') * 90) / F.col('minutes_played')
    )
    
    player_pressing = player_pressing.withColumn(
        'regains_per_90',
        (F.col('total_regain_count') * 90) / F.col('minutes_played')
    )
    
    player_pressing = player_pressing.withColumn(
        'successful_presses_per_90',
        (F.col('successful_press_count') * 90) / F.col('minutes_played')
    )
    
    player_pressing = player_pressing.withColumn(
        'counter_presses_per_90',
        (F.col('counter_press_count') * 90) / F.col('minutes_played')
    )
    
    # Filter minimum volume
    player_pressing = player_pressing.filter(
        (F.col('minutes_played') >= min_minutes) &
        (F.col('pressing_action_count') >= min_actions)
    )
    
    # Select output columns
    output_cols = [
        'match_id', 'player_id', 'player_short_name', 'team_id', 'team_name',
        'position_group', 'role_name', 'minutes_played',
        'pressing_action_count', 'pressing_actions_per_90',
        'press_success_rate', 'regain_rate', 'disruption_rate',
        'successful_press_count', 'successful_presses_per_90',
        'total_regain_count', 'regains_per_90',
        'direct_regain_count', 'indirect_regain_count',
        'total_disruption_count', 'direct_disruption_count', 'indirect_disruption_count',
        'presses_leading_to_shot', 'presses_leading_to_goal', 'shot_creation_rate',
        'high_block_press_count', 'medium_block_press_count', 'low_block_press_count',
        'counter_press_count', 'counter_presses_per_90',
    ]
    
    return player_pressing.select(*[c for c in output_cols if c in player_pressing.columns])