# Traits Insights Take-Home Assessment

ETL pipeline for SkillCorner A-League tracking data analysis.

## Setup

**Prerequisites:**
- Python 3.12+
- Git LFS

**Installation:**

```bash
# Clone repo
git clone https://github.com/aang-sym/traits-takehome.git
cd traits-takehome

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or on windows: venv\Scripts\activate
pip install -r requirements.txt

# Get the SkillCorner data
git lfs install
mkdir -p data
cd data
git clone https://github.com/SkillCorner/opendata.git
git lfs pull
cd ..
```

**Verify setup:**
```bash
ls data/opendata/data/matches/
# Should see 10 match directories
```

## Running

Run notebooks in order:

1. `01_data_loading.ipynb` - Data loading and exploration

## Project Structure

```
├── notebooks/           # Analysis notebooks
├── src/                # Python modules
│   └── loaders.py     # Data loading functions
├── output/            # Generated files
└── tests/             # Unit tests
```

## Data

Uses [SkillCorner Open Data](https://github.com/SkillCorner/opendata) - 10 A-League matches with:
- Match metadata and lineups
- 10fps tracking data (player/ball positions)
- Pre-computed dynamic events
- Game phase classifications