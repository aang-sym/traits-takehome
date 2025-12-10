"""
Helper functions and widgets for player performance visualisation.
"""

import pandas as pd
import matplotlib.pyplot as plt
import ipywidgets as widgets
from ipywidgets import Dropdown, IntSlider
import plotly.graph_objects as go
from IPython.display import display


def get_eligible_players(df, metric_family, min_minutes, min_volume, metric_families):
    """Filter to players with sufficient minutes and event volume."""
    cfg = metric_families[metric_family]
    metrics = cfg["metrics"]
    volume_col = cfg["volume_col"]
    
    subset = df.copy()
    subset = subset[subset["minutes_played"] >= min_minutes]
    subset = subset[subset[volume_col] >= min_volume]
    subset = subset.dropna(subset=metrics, how="all")
    
    return subset


def add_percentiles(eligible_df, metric_family, cohort_mode, metric_families):
    """Add percentile columns for each metric based on cohort grouping."""
    cfg = metric_families[metric_family]
    metrics = cfg["metrics"]
    df_pct = eligible_df.copy()
    
    # Determine grouping keys
    if cohort_mode == "All players":
        group_keys = None
    elif cohort_mode == "Same position_group":
        group_keys = ["position_group"]
    elif cohort_mode == "Same team":
        group_keys = ["team_name"]
    elif cohort_mode == "Same team and position_group":
        group_keys = ["team_name", "position_group"]
    else:
        raise ValueError("Unknown cohort_mode")
    
    # Compute percentiles
    for m in metrics:
        if group_keys is None:
            ranks = df_pct[m].rank(pct=True)
        else:
            ranks = df_pct.groupby(group_keys)[m].rank(pct=True)
        df_pct[m + "_pctile"] = (ranks * 100).round(1)
    
    return df_pct


def get_comparison_baseline(df_pct, player_row, comparison_target, metric_family, metric_families):
    """
    Build a comparison baseline (average) based on target type.
    Returns a dict-like row with same structure as player_row.
    
    KEY FIX: For averages, we need to:
    1. Take mean of RAW metric values (not percentiles)
    2. Calculate where that mean sits as a percentile within the cohort
    """
    cfg = metric_families[metric_family]
    metrics = cfg["metrics"]
    
    if comparison_target == "Position-group average":
        mask = df_pct['position_group'] == player_row['position_group']
        cohort = df_pct[mask]
        label = f"{player_row['position_group']} avg"
        
    elif comparison_target == "Team average":
        mask = df_pct['team_name'] == player_row['team_name']
        cohort = df_pct[mask]
        label = f"{player_row['team_name']} avg"
        
    elif comparison_target == "Team + position-group average":
        mask = (df_pct['position_group'] == player_row['position_group']) & \
               (df_pct['team_name'] == player_row['team_name'])
        cohort = df_pct[mask]
        label = f"{player_row['team_name']} {player_row['position_group']} avg"
    else:
        return None, None
    
    # Build baseline with RAW means
    baseline = {}
    for m in metrics:
        # Mean of raw metric values
        baseline[m] = cohort[m].mean()
        
        # Calculate percentile: where does this mean sit in the cohort distribution?
        raw_values = cohort[m].dropna()
        if len(raw_values) > 0:
            # Count how many values are <= the mean
            pct_below = (raw_values <= baseline[m]).sum() / len(raw_values)
            baseline[m + '_pctile'] = round(pct_below * 100, 1)
        else:
            baseline[m + '_pctile'] = 50.0  # Fallback
    
    return pd.Series(baseline), label


def build_data_quality_table(df, metric_families, min_minutes_default):
    """Show which position groups have the strongest data per metric family."""
    summary_rows = []

    for family_name, cfg in metric_families.items():
        volume_col = cfg["volume_col"]
        min_volume = cfg["min_volume_default"]

        # Use family-level eligibility
        eligible = get_eligible_players(df, family_name, min_minutes_default, min_volume, metric_families)

        if eligible.empty:
            continue

        grouped = eligible.groupby("position_group").agg(
            player_count=("player_id", "nunique"),
            mean_volume=(volume_col, "mean"),
        )

        # Simple robustness score: more players * more events
        grouped["score"] = grouped["player_count"] * grouped["mean_volume"]

        best_row = grouped.sort_values("score", ascending=False).iloc[0]
        best_position_group = best_row.name  # index label = position_group

        summary_rows.append({
            "metric_family": family_name,
            "best_position_group": best_position_group,
            "player_count": int(best_row["player_count"]),
            "mean_volume": round(best_row["mean_volume"], 1),
        })

    return pd.DataFrame(summary_rows)


def build_position_group_performance_summary(df, metric_families, min_minutes_default):
    """Show best performing position groups for each metric within each family."""
    all_summaries = {}
    
    for family_name, cfg in metric_families.items():
        metrics = cfg["metrics"]
        volume_col = cfg["volume_col"]
        min_volume = cfg["min_volume_default"]

        eligible = get_eligible_players(df, family_name, min_minutes_default, min_volume, metric_families)

        summary_rows = []

        for metric in metrics:
            grouped = eligible.groupby("position_group").agg(
                player_count=("player_id", "nunique"),
                total_volume=(volume_col, "sum"),
                mean_volume=(volume_col, "mean"),
                mean_metric=(metric, "mean"),
                median_metric=(metric, "median"),
            )

            if len(grouped) == 0:
                continue

            # Rank groups purely by mean metric
            best_row = grouped.sort_values("mean_metric", ascending=False).iloc[0]
            best_group = best_row.name

            summary_rows.append({
                "metric": metric,
                "best_position_group": best_group,
                "player_count": int(best_row["player_count"]),
                "total_volume": round(best_row["total_volume"], 1),
                "mean_volume": round(best_row["mean_volume"], 1),
                "mean_metric": round(best_row["mean_metric"], 3),
                "median_metric": round(best_row["median_metric"], 3),
                "weighted_metric": round(best_row["mean_metric"], 3),
                "score_type": "mean",
            })

        all_summaries[family_name] = pd.DataFrame(summary_rows)
    
    return all_summaries


def create_comparison_widget(df, metric_families, min_minutes_default, min_sprints_default):
    """Main interactive player comparison interface."""
    
    # UI controls
    metric_dropdown = Dropdown(
        options=list(metric_families.keys()),
        value="Sprints",
        description="Metric:"
    )
    
    cohort_dropdown = Dropdown(
        options=["All players", "Same position_group", "Same team", "Same team and position_group"],
        value="Same position_group",
        description="Cohort:"
    )
    
    position_dropdown = Dropdown(
        options=["All position groups"],
        description="Position:"
    )
    
    min_minutes_slider = IntSlider(
        min=30, max=90, step=15,
        value=min_minutes_default,
        description="Min mins:"
    )
    
    min_volume_slider = IntSlider(
        min=1, max=20, step=1,
        value=min_sprints_default,
        description="Min volume:"
    )
    
    comparison_dropdown = Dropdown(
        options=[
            "Individual player",
            "Position-group average",
            "Team average", 
            "Team + position-group average"
        ],
        value="Individual player",
        description="Compare to:"
    )
    
    player1_dropdown = Dropdown(options=[], description="Player 1:")
    player2_dropdown = Dropdown(options=[], description="Player 2:")
    
    output = widgets.Output()
    
    # Flags to control callback storms
    updating_filters = {"active": False}
    suppress_plot = {"active": False}
    initializing = {"active": True}
    
    def update_filters(*args):
        """Update dependent dropdowns when filters change."""
        if updating_filters["active"]:
            return
        updating_filters["active"] = True
        
        try:
            metric_family = metric_dropdown.value
            min_minutes = min_minutes_slider.value
            min_volume = min_volume_slider.value
            position_filter = position_dropdown.value
            
            # Update min_volume default without causing another filter run
            default_min_vol = metric_families[metric_family]["min_volume_default"]
            if min_volume_slider.value != default_min_vol:
                min_volume_slider.value = default_min_vol
            
            # Get eligible players
            eligible = get_eligible_players(df, metric_family, min_minutes, min_volume_slider.value, metric_families)
            
            # Update position filter options
            positions = ["All position groups"] + sorted(eligible['position_group'].unique())
            position_dropdown.options = positions
            
            # Apply position filter
            if position_filter != "All position groups" and position_filter in eligible['position_group'].values:
                eligible = eligible[eligible['position_group'] == position_filter]
            
            # Update player dropdowns safely
            players = sorted(eligible['player_short_name'].unique())
            
            suppress_plot["active"] = True
            try:
                player1_dropdown.value = None
                player2_dropdown.value = None

                player1_dropdown.options = players
                player2_dropdown.options = players
                
                if len(players) > 0:
                    player1_dropdown.value = players[0]
                    if len(players) > 1:
                        player2_dropdown.value = players[1]
                    else:
                        player2_dropdown.value = players[0]
            finally:
                suppress_plot["active"] = False
        
        finally:
            updating_filters["active"] = False
        
        # Only plot if we're not initializing
        if not initializing["active"]:
            update_plot()
    
    def update_plot(*args):
        """Render the comparison plot."""
        if suppress_plot["active"] or initializing["active"]:
            return
        
        with output:
            output.clear_output(wait=True)
            
            metric_family = metric_dropdown.value
            cohort_mode = cohort_dropdown.value
            min_minutes = min_minutes_slider.value
            min_volume = min_volume_slider.value
            position_filter = position_dropdown.value
            comparison_target = comparison_dropdown.value
            player1_name = player1_dropdown.value
            player2_name = player2_dropdown.value
            
            if not player1_name or not player2_name:
                return
            
            # Get eligible subset
            eligible = get_eligible_players(df, metric_family, min_minutes, min_volume, metric_families)
            if position_filter != "All position groups":
                eligible = eligible[eligible['position_group'] == position_filter]
            
            # Add percentiles
            df_pct = add_percentiles(eligible, metric_family, cohort_mode, metric_families)
            
            # Get player data
            p1_matches = df_pct[df_pct['player_short_name'] == player1_name]
            if len(p1_matches) == 0:
                print(f"No data for {player1_name}")
                return
            p1 = p1_matches.iloc[0]
            
            # Get comparison target
            if comparison_target == "Individual player":
                p2_matches = df_pct[df_pct['player_short_name'] == player2_name]
                if len(p2_matches) == 0:
                    print(f"No data for {player2_name}")
                    return
                p2 = p2_matches.iloc[0]
                p2_label = player2_name
                p2_data = p2
            else:
                p2_data, p2_label = get_comparison_baseline(df_pct, p1, comparison_target, metric_family, metric_families)
            
            # Build plot - radar only
            cfg = metric_families[metric_family]
            metrics = cfg["metrics"]
            
            fig = go.Figure()
            
            # Radar chart
            categories = [m.replace('_', ' ').title() for m in metrics]
            
            fig.add_trace(go.Scatterpolar(
                r=[p1[m + '_pctile'] for m in metrics],
                theta=categories,
                fill='toself',
                name=player1_name,
                line=dict(width=2)
            ))
            
            fig.add_trace(go.Scatterpolar(
                r=[p2_data[m + '_pctile'] for m in metrics],
                theta=categories,
                fill='toself',
                name=p2_label,
                line=dict(width=2)
            ))
            
            # Layout
            fig.update_layout(
                title_text=(
                    f"{player1_name} vs {p2_label}"
                    f"<br><sub>Cohort: {cohort_mode} | "
                    f"{player1_name}: {p1['minutes_played']:.0f} mins, "
                    f"{p1[cfg['volume_col']]:.0f} events</sub>"
                ),
                height=550,
                showlegend=True,
                polar=dict(radialaxis=dict(range=[0, 100], showticklabels=True))
            )
            
            fig.show()
    
    # Wire up interactions
    metric_dropdown.observe(update_filters, 'value')
    min_minutes_slider.observe(update_filters, 'value')
    min_volume_slider.observe(update_filters, 'value')
    position_dropdown.observe(update_filters, 'value')
    
    comparison_dropdown.observe(update_plot, 'value')
    cohort_dropdown.observe(update_plot, 'value')
    player1_dropdown.observe(update_plot, 'value')
    player2_dropdown.observe(update_plot, 'value')
    
    # Initial setup with blocking
    initializing["active"] = True
    update_filters()
    initializing["active"] = False
    update_plot()
    
    # Layout
    controls = widgets.VBox([
        widgets.HBox([metric_dropdown, cohort_dropdown]),
        widgets.HBox([position_dropdown, comparison_dropdown]),
        widgets.HBox([min_minutes_slider, min_volume_slider]),
        widgets.HBox([player1_dropdown, player2_dropdown])
    ])
    
    display(controls, output)


def build_performance_scatter(df, metric_families):
    """Interactive scatter plot showing player performance across key metrics."""
    
    # Use same filters as heatmap for consistency
    min_minutes = 60
    
    # Get players eligible for each metric family with their percentiles
    family_dfs = {}
    
    for family_name, cfg in metric_families.items():
        eligible = get_eligible_players(df, family_name, min_minutes, cfg["min_volume_default"], metric_families)
        eligible = add_percentiles(eligible, family_name, "Same position_group", metric_families)
        
        # Aggregate to player level - keep raw values AND percentiles
        raw_metrics = cfg["metrics"]
        pctile_cols = [m + '_pctile' for m in raw_metrics]
        
        player_agg = eligible.groupby('player_id').agg({
            'player_short_name': 'first',
            'team_name': 'first',
            'position_group': 'first',
            **{col: 'mean' for col in raw_metrics},   # raw values
            **{col: 'mean' for col in pctile_cols}    # percentiles
        }).reset_index()
        
        family_dfs[family_name] = player_agg
    
    # Merge all families into a combined player-level dataframe
    family_names = list(metric_families.keys())
    combined = family_dfs[family_names[0]].copy()
    
    for family_name in family_names[1:]:
        combined = combined.merge(
            family_dfs[family_name],
            on=['player_id', 'player_short_name', 'team_name', 'position_group'],
            how='outer'
        )
    
    # Key percentile metrics used for composite score (one per family)
    heatmap_metrics = {
        'high_value_sprints_per_90_pctile': 'HV Sprints/90',
        'threat_per_90_pctile': 'Threat/90',
        'successful_presses_per_90_pctile': 'Succ. Presses/90'
    }
    
    # Composite score across the four headline metrics
    combined['composite_score'] = combined[list(heatmap_metrics.keys())].mean(axis=1)
    
    # Top 5 per position group for highlighting
    top_players = (
        combined.groupby('position_group', group_keys=False)
        .apply(lambda x: x.nlargest(5, 'composite_score'))
        .reset_index(drop=True)
    )
    top_player_ids = set(top_players['player_id'])
    
    # For each view, explicitly define (x, y) and labels
    metric_views = {
        'HV Sprints/90': {
            'x_column': 'sprint_distance_per_90',
            'y_column': 'high_value_sprints_per_90',
            'x_label': 'Sprint Distance Per 90 (m)',
            'y_label': 'High Value Sprints Per 90'
        },
        'Threat/90': {
            'x_column': 'high_value_runs_per_90',
            'y_column': 'threat_per_90',
            'x_label': 'High Value Runs Per 90',
            'y_label': 'Threat Per 90 (xThreat)'
        },
        'Succ. Presses/90': {
            'x_column': 'pressing_actions_per_90',
            'y_column': 'successful_presses_per_90',
            'x_label': 'Pressing Actions Per 90',
            'y_label': 'Successful Presses Per 90'
        }
    }
    
    def plot_scatter(metric_label):
        """Update scatter plot based on selected metric view."""
        plt.close('all')
        
        view = metric_views[metric_label]
        x_column = view['x_column']
        y_column = view['y_column']
        x_label = view['x_label']
        y_label = view['y_label']
        
        # Filter to players with valid data for both axes
        plot_data = combined.dropna(subset=[x_column, y_column]).copy()
        
        if len(plot_data) == 0:
            print(f"No valid data for {metric_label}")
            return
        
        # Mark highlighted players
        plot_data['is_top'] = plot_data['player_id'].isin(top_player_ids)
        
        # Sample means for reference lines
        x_mean = plot_data[x_column].mean()
        y_mean = plot_data[y_column].mean()
        
        fig, ax = plt.subplots(figsize=(12, 8))
        
        # Background players
        non_top = plot_data[~plot_data['is_top']]
        ax.scatter(
            non_top[x_column],
            non_top[y_column],
            c='#d3d3d3',
            s=80,
            alpha=0.4,
            zorder=1
        )
        
        # Highlighted players
        top = plot_data[plot_data['is_top']]
        ax.scatter(
            top[x_column],
            top[y_column],
            c='#2ecc71',
            s=120,
            alpha=0.9,
            edgecolors='white',
            linewidths=1.5,
            zorder=2
        )
        
        # Labels for highlighted players
        for _, row in top.iterrows():
            ax.annotate(
                row['player_short_name'],
                xy=(row[x_column], row[y_column]),
                xytext=(8, 8),
                textcoords='offset points',
                fontsize=9,
                fontweight='bold',
                zorder=3
            )
        
        # Mean reference lines
        ax.axhline(y_mean, color='grey', linestyle='--', linewidth=1, alpha=0.6, zorder=0)
        ax.axvline(x_mean, color='grey', linestyle='--', linewidth=1, alpha=0.6, zorder=0)
        
        # Styling
        ax.set_xlabel(x_label, fontsize=11)
        ax.set_ylabel(y_label, fontsize=11)
        ax.set_title(
            f'Player profile – {metric_label} (min {min_minutes} mins)',
            fontsize=12,
            pad=15
        )
        ax.set_facecolor('white')
        ax.grid(True, alpha=0.2, linestyle='-', linewidth=0.5)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        
        plt.tight_layout()
        plt.show()
    
    # Return data and widget components (don't display yet)
    metric_dropdown = widgets.Dropdown(
        options=list(metric_views.keys()),
        value=list(metric_views.keys())[0],
        description='Metric:',
        style={'description_width': '60px'}
    )
    
    output = widgets.interactive_output(plot_scatter, {'metric_label': metric_dropdown})
    widget_box = widgets.VBox([metric_dropdown, output])
    
    return combined, widget_box