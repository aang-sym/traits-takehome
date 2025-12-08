"""
Data loaders for SkillCorner A-League tracking data.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List

import pandas as pd

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data" / "opendata" / "data" / "matches"
MATCHES_JSON = PROJECT_ROOT / "data" / "opendata" / "data" / "matches.json"

def load_physical_aggregates() -> pd.DataFrame:
    """Load the A-League physical aggregates dataset."""
    agg_path = (
        PROJECT_ROOT
        / "data"
        / "opendata"
        / "data"
        / "aggregates"
        / "aus1league_physicalaggregates_20242025_midfielders.csv"
    )
    return pd.read_csv(agg_path)

def load_match_metadata(match_id: str) -> Dict:
    """Load match.json file - contains teams, players, pitch dimensions."""
    file_path = DATA_DIR / match_id / f"{match_id}_match.json"
    
    if not file_path.exists():
        raise FileNotFoundError(f"Match file not found: {file_path}")
    
    with open(file_path, 'r') as f:
        return json.load(f)


def load_tracking_data(match_id: str) -> pd.DataFrame:
    """
    Load tracking_extrapolated.jsonl - frame-by-frame positions at 10fps.
    
    Note: Returns DataFrame with nested structures (ball_data, possession, player_data).
    Will need to explode player_data for player-level analysis.
    """
    file_path = DATA_DIR / match_id / f"{match_id}_tracking_extrapolated.jsonl"
    
    if not file_path.exists():
        raise FileNotFoundError(f"Tracking file not found: {file_path}")
    
    # JSONL = one JSON object per line
    return pd.read_json(file_path, lines=True)


def load_dynamic_events(match_id: str) -> pd.DataFrame:
    """
    Load dynamic_events.csv - pre-computed events like possessions, runs, passes.
    """
    file_path = DATA_DIR / match_id / f"{match_id}_dynamic_events.csv"

    if not file_path.exists():
        raise FileNotFoundError(f"Events file not found: {file_path}")

    # Use low_memory=False to avoid dtype warnings from mixed types in sparse columns
    return pd.read_csv(file_path, low_memory=False)


def load_phases(match_id: str) -> pd.DataFrame:
    """Load phases_of_play.csv - game phase classifications."""
    file_path = DATA_DIR / match_id / f"{match_id}_phases_of_play.csv"
    
    if not file_path.exists():
        raise FileNotFoundError(f"Phases file not found: {file_path}")
    
    return pd.read_csv(file_path)


def get_all_match_ids() -> List[str]:
    """Get list of all match IDs from matches.json or filesystem."""
    # Try matches.json first
    if MATCHES_JSON.exists():
        try:
            with open(MATCHES_JSON, 'r') as f:
                matches_data = json.load(f)
            return [str(match['id']) for match in matches_data]
        except Exception as e:
            logger.warning(f"Could not read matches.json: {e}")
    
    # Fallback to filesystem
    if DATA_DIR.exists():
        return sorted([d.name for d in DATA_DIR.iterdir() if d.is_dir() and d.name.isdigit()])
    
    raise FileNotFoundError(f"Cannot find match data: {DATA_DIR}")


def load_all_matches() -> Dict[str, Dict]:
    """
    Load all 10 matches.
    
    Returns dict like:
        {
            "1886347": {
                "metadata": dict,
                "tracking": DataFrame,
                "events": DataFrame,
                "phases": DataFrame
            },
            ...
        }
    """
    match_ids = get_all_match_ids()
    all_data = {}
    
    for i, match_id in enumerate(match_ids, 1):
        logger.info(f"Loading match {i}/{len(match_ids)}: {match_id}")
        
        try:
            all_data[match_id] = {
                "metadata": load_match_metadata(match_id),
                "tracking": load_tracking_data(match_id),
                "events": load_dynamic_events(match_id),
                "phases": load_phases(match_id)
            }
        except Exception as e:
            logger.warning(f"Skipping match {match_id}: {e}")
            continue
    
    logger.info(f"Loaded {len(all_data)}/{len(match_ids)} matches")
    return all_data