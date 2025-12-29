#!/usr/bin/env python3
"""
Configuration File for Protein Target Identification Pipeline (v2.2)
=====================================================================
Updated: Added project_name awareness to all file paths
"""
from pathlib import Path

# =============================================================================
# BASE DIRECTORY - EDIT THIS!
# =============================================================================

BASE_DIR = Path(__file__).parent.parent

# =============================================================================
# DIRECTORY STRUCTURE
# =============================================================================

INPUT_SEQUENCES = BASE_DIR / "input_sequences"
DB_DIR = BASE_DIR / "db"
OUTPUT_DIR = BASE_DIR / "targetX"

MSA_DIR = BASE_DIR / "MSA"
STRUCTURE_DIR = BASE_DIR / "Structure"
# =============================================================================
# DATABASE PATHS
# =============================================================================

HUMAN_DB = DB_DIR / "human" / "human_protein"
DEG_DB = DB_DIR / "deg" / "deg_protein"
VFDB_DB = DB_DIR / "vfdb" / "virulence_factors"
ESKAPE_DB = DB_DIR / "eskape" / "ESKAPE"
DRUGBANK_DB = DB_DIR / "drugbank" / "drugbank_database"

# =============================================================================
# FILE NAMING FUNCTIONS
# =============================================================================

# <-- MODIFIED: Added a helper function to get the correct (project or global) output dir
def get_project_output_dir(project_name=None):
    """Helper to get the correct output dir and ensure it exists."""
    project_dir = OUTPUT_DIR / project_name if project_name else OUTPUT_DIR
    # Ensure the directory exists before returning
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir

# <-- MODIFIED: Added a helper function to get the correct (project or global) input dir
def get_project_input_dir(project_name=None):
    """Helper to get the correct input dir."""
    project_dir = INPUT_SEQUENCES / project_name if project_name else INPUT_SEQUENCES
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir

# <-- MODIFIED: Added project_name=None
def get_input_file(database_name, project_name=None):
    """Get input file: {project}/{database}_input.faa"""
    project_dir = get_project_output_dir(project_name) # <-- MODIFIED
    return project_dir / f"{database_name}_input.faa"

# <-- MODIFIED: Added project_name=None
def get_blast_file(database_name, project_name=None):
    """Get BLAST output: {project}/{database}_blast.txt"""
    project_dir = get_project_output_dir(project_name) # <-- MODIFIED
    return project_dir / f"{database_name}_blast.txt"

# <-- MODIFIED: Added project_name=None
def get_filtered_file(database_name, project_name=None):
    """Get filtered results: {project}/{database}_filtered.tsv"""
    project_dir = get_project_output_dir(project_name) # <-- MODIFIED
    return project_dir / f"{database_name}_filtered.tsv"

# <-- MODIFIED: Added project_name=None
def get_passing_file(database_name, project_name=None):
    """Get passing sequences: {project}/{database}_passing.faa"""
    project_dir = get_project_output_dir(project_name) # <-- MODIFIED
    return project_dir / f"{database_name}_passing.faa"

# <-- MODIFIED: Added project_name=None
def get_summary_file(database_name, project_name=None):
    """Get summary report: {project}/{database}_summary.txt"""
    project_dir = get_project_output_dir(project_name) # <-- MODIFIED
    return project_dir / f"{database_name}_summary.txt"

# <-- MODIFIED: Added project_name=None
def get_log_file(database_name, timestamp=None, project_name=None):
    """Get log file: {project}/{database}_run_{timestamp}.log"""
    project_dir = get_project_output_dir(project_name) # <-- MODIFIED
    if timestamp:
        return project_dir / f"{database_name}_run_{timestamp}.log"
    return project_dir / f"{database_name}_run.log"

# <-- MODIFIED: Added project_name=None
def get_cache_file(database_name, project_name=None):
    """Get cache file: {project}/.{database}_cache.pkl (hidden)"""
    project_dir = get_project_output_dir(project_name) # <-- MODIFIED
    return project_dir / f".{database_name}_cache.pkl"

# <-- MODIFIED: Changed from a global variable to a function
def get_combined_sequences_file(project_name=None):
    """
    Get the combined input file for the project.
    The web app creates this in the project's *output* directory.
    """
    project_dir = get_project_output_dir(project_name) # <-- MODIFIED
    return project_dir / "combined.faa"


# =============================================================================
# BLAST PARAMETERS
# =============================================================================

import multiprocessing
BLAST_THREADS = max(1, multiprocessing.cpu_count() - 4)

# =============================================================================
# FILTERING THRESHOLDS
# =============================================================================

DEFAULT_THRESHOLDS = {
    'pct_identity': 35.0,
    'coverage': 70.0,
    'evalue': 1e-5
}

# =============================================================================
# SEQUENCE LENGTH FILTERS
# =============================================================================

MIN_PROTEIN_LENGTH = 50
MAX_PROTEIN_LENGTH = 5000

# =============================================================================
# DATABASE ACTIONS (UPDATED - All use rejection!)
# =============================================================================

DATABASE_ACTIONS = {
    'human': {
        'action': 'reject',
        'selection': 'negative',  # Reject matches (remove human-like)
        'description': 'Remove proteins similar to human proteins'
    },
    'deg': {
        'action': 'reject',
        'selection': 'positive',  # Reject non-matches (keep only essential)
        'description': 'Keep only essential proteins'
    },
    'vfdb': {
        'action': 'reject',
        'selection': 'positive',  # Reject non-matches (keep only virulent)
        'description': 'Keep only virulence factor proteins'
    },
    'eskape': {
        'action': 'reject',
        'selection': 'positive',  # Reject non-matches (keep only ESKAPE)
        'description': 'Keep only ESKAPE pathogen proteins'
    },
    'drugbank': {
        'action': 'reject',
        'selection': 'positive',
        'description': 'Keep only drug target proteins'
    },
}

# =============================================================================
# PIPELINE FLOW
# =============================================================================

PIPELINE_FLOW = {
    'human': {
        'input_source': 'combined',
        'next_step': 'deg'
    },
    'deg': {
        'input_source': 'human',
        'next_step': 'vfdb'
    },
    'vfdb': {
        'input_source': 'deg',
        'next_step': 'eskape'
    },
    'eskape': {
        'input_source': 'vfdb',
        'next_step': None
    },
}

# =============================================================================
# VALIDATION
# =============================================================================

def validate_config():
    """Validate configuration and create directories."""
    
    print("\n" + "=" * 70)
    print("Configuration Validation")
    print("=" * 70)
    
    if not BASE_DIR.exists():
        print(f"\n⚠ Warning: BASE_DIR does not exist: {BASE_DIR}")
        print(f"    Creating directory...")
        BASE_DIR.mkdir(parents=True, exist_ok=True)
    
    print(f"\n✓ Base directory: {BASE_DIR}")
    
    print("\nCreating/checking directories...")
    
    INPUT_SEQUENCES.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Input: {INPUT_SEQUENCES}")
    
    DB_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Databases: {DB_DIR}")
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Output: {OUTPUT_DIR}")
    
    for db_name in ['human', 'deg', 'vfdb', 'eskape', 'drugbank']:
        db_subdir = DB_DIR / db_name
        db_subdir.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Database subdirectories created")
    
    print("\nChecking databases...")
    databases = [
        ('Human', HUMAN_DB),
        ('DEG', DEG_DB),
        ('VFDB', VFDB_DB),
        ('ESKAPE', ESKAPE_DB),
    ]
    
    for name, db_path in databases:
        extensions = ['.phr', '.pin', '.psq']
        found = any((Path(str(db_path) + ext).exists()) for ext in extensions)
        
        if found:
            print(f"  ✓ {name}: {db_path}")
        else:
            print(f"  ✗ {name}: NOT FOUND - {db_path}")
    
    # <-- MODIFIED: This check is no longer relevant for the web app,
    # as files will be in project-specific subdirectories.
    # print("\nChecking input sequences...")
    # faa_files = list(INPUT_SEQUENCES.glob("*.faa"))
    
    # if faa_files:
    #     print(f"  ✓ Found {len(faa_files)} .faa files")
    # else:
    #     print(f"  ⚠ No .faa files found")
    
    print("\n" + "=" * 70)
    print("✓ Configuration validated!")
    print("=" * 70)
    print("\nPipeline Strategy (Progressive Rejection):")
    print("  HUMAN → Remove human-like proteins")
    print("  DEG   → Remove NON-essential proteins (keep essential)")
    print("  VFDB  → Remove NON-virulent proteins (keep virulent)")
    print("  ESKAPE→ Remove NON-eskape proteins (keep eskape)")
    print("\nFinal output: Proteins meeting ALL 4 criteria!")
    print()

if __name__ == "__main__":
    validate_config()