import json
import time
import cProfile
import pstats
from pathlib import Path
from collections import defaultdict
import logging
import sys

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add current directory to sys.path to allow imports
sys.path.append(str(Path(__file__).parent))

from regelpruefer_pauschale import determine_applicable_pauschale, build_pauschale_condition_structure_index

# Data Paths
DATA_DIR = Path("data")
PAUSCHALE_LP_PATH = DATA_DIR / "PAUSCHALEN_Leistungspositionen.json"
PAUSCHALEN_PATH = DATA_DIR / "PAUSCHALEN_Pauschalen.json"
PAUSCHALE_BED_PATH = DATA_DIR / "PAUSCHALEN_Bedingungen.json"
TABELLEN_PATH = DATA_DIR / "PAUSCHALEN_Tabellen.json"
LEISTUNGSKATALOG_PATH = DATA_DIR / "LKAAT_Leistungskatalog.json"

# Global Data Containers
pauschale_lp_data = []
pauschalen_dict = {}
pauschale_bedingungen_data = []
tabellen_dict_by_table = {}
leistungskatalog_dict = {}

def load_data():
    logger.info("Loading data...")
    
    with open(PAUSCHALE_LP_PATH, 'r', encoding='utf-8') as f:
        pauschale_lp_data.extend(json.load(f))
        
    with open(PAUSCHALEN_PATH, 'r', encoding='utf-8') as f:
        p_data = json.load(f)
        for item in p_data:
            if item.get('Pauschale'):
                pauschalen_dict[str(item['Pauschale'])] = item
                
    with open(PAUSCHALE_BED_PATH, 'r', encoding='utf-8') as f:
        pauschale_bedingungen_data.extend(json.load(f))
        
    with open(TABELLEN_PATH, 'r', encoding='utf-8') as f:
        t_data = json.load(f)
        for item in t_data:
            table_name = item.get('Tabelle')
            if table_name:
                key = str(table_name).lower()
                if key not in tabellen_dict_by_table:
                    tabellen_dict_by_table[key] = []
                tabellen_dict_by_table[key].append(item)

    with open(LEISTUNGSKATALOG_PATH, 'r', encoding='utf-8') as f:
        lk_data = json.load(f)
        for item in lk_data:
            lkn = item.get('LKN')
            if lkn:
                leistungskatalog_dict[str(lkn)] = item

    logger.info("Data loaded.")

def run_benchmark():
    # Heavy LKNs found: C03.GC.0200, WA.10.0050
    # Let's use WA.10.0050 (Anästhesie) as it's very common
    heavy_lkn = "WA.10.0050" 
    
    # Create a context that triggers many checks
    context = {
        "LKN": [heavy_lkn, "AA.00.0010"], # Add a common consultation code too
        "Alter": 45,
        "Geschlecht": "W",
        "Seitigkeit": "unbekannt",
        "Anzahl": 1,
        "useIcd": True,
        "ICD": ["M54.5"] # Back pain, common
    }
    
    # Pre-compute structures (simulating server.py)
    logger.info("Building prepared structures...")
    prepared_structures = build_pauschale_condition_structure_index(pauschale_bedingungen_data)
    logger.info(f"Built {len(prepared_structures)} structures.")

    # Pre-filter potential pauschale codes (simulating server.py logic)
    potential_codes = set()
    for item in pauschale_lp_data:
        if item.get('Leistungsposition') in context['LKN']:
            potential_codes.add(item.get('Pauschale'))
            
    logger.info(f"Found {len(potential_codes)} potential Pauschale codes for LKNs {context['LKN']}")
    
    start_time = time.time()
    
    # Run the determination
    result = determine_applicable_pauschale(
        user_input="",
        rule_checked_leistungen=[],
        context=context,
        pauschale_lp_data=pauschale_lp_data,
        pauschale_bedingungen_data=pauschale_bedingungen_data,
        pauschalen_dict=pauschalen_dict,
        leistungskatalog_dict=leistungskatalog_dict,
        tabellen_dict_by_table=tabellen_dict_by_table,
        potential_pauschale_codes_input=potential_codes,
        prepared_structures=prepared_structures
    )
    
    end_time = time.time()
    duration = end_time - start_time
    
    logger.info(f"Execution time: {duration:.4f} seconds")
    logger.info(f"Result type: {result.get('type')}")
    if result.get('details'):
        logger.info(f"Selected Pauschale: {result['details'].get('Pauschale')}")

def profile_benchmark():
    logger.info("Starting profiling...")
    profiler = cProfile.Profile()
    profiler.enable()
    
    run_benchmark()
    
    profiler.disable()
    with open("profile_stats.txt", "w", encoding="utf-8") as f:
        stats = pstats.Stats(profiler, stream=f).sort_stats('cumtime')
        stats.print_stats(50)
        f.write("\nTop 50 by internal time (self time):\n")
        stats.sort_stats('tottime').print_stats(50)
    
    logger.info("Profiling complete. Stats written to profile_stats.txt")

if __name__ == "__main__":
    load_data()
    profile_benchmark()
