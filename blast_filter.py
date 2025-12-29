#!/usr/bin/env python3
"""
Unified Database Filter Script (v4.1)
=====================================
New structure: Project-based directories (e.g., targetX/ProjectName/)
Accepts --project argument from web app.

Usage:
python3 filter_database.py human --project Trial2
python3 filter_database.py human --dry-run
"""
import sys
import argparse
import time
import multiprocessing
import pickle
import hashlib
import shutil
from pathlib import Path
from datetime import datetime

# Import configuration
import config as config
import utils

# =============================================================================
# DATABASE CONFIGURATIONS
# =============================================================================

DATABASE_CONFIGS = {
    'human': {
        'name': 'Human',
        'db_path': config.HUMAN_DB,
        'action': 'reject',
        'selection': 'negative',  # Remove matches (human-like proteins)
        'description': 'Remove proteins similar to human proteins'
    },
    'deg': {
        'name': 'DEG (Essential Genes)',
        'db_path': config.DEG_DB,
        'action': 'reject',
        'selection': 'positive',  # Keep only matches (essential proteins)
        'description': 'Keep only essential proteins'
    },
    'vfdb': {
        'name': 'VFDB (Virulence Factors)',
        'db_path': config.VFDB_DB,
        'action': 'reject',
        'selection': 'positive',  # Keep only matches (virulent proteins)
        'description': 'Keep only virulence factor proteins'
    },
    'eskape': {
        'name': 'ESKAPE (Priority Pathogens)',
        'db_path': config.ESKAPE_DB,
        'action': 'reject',
        'selection': 'positive',  # Keep only matches (ESKAPE proteins)
        'description': 'Keep only ESKAPE pathogen proteins'
    },
    'drugbank': {
        'name': 'DrugBank (Drug Targets)',
        'db_path': config.DRUGBANK_DB,
        'action': 'reject',
        'selection': 'positive',
        'description': 'Keep only drug target proteins'
    },
}

# =============================================================================
# LOGGING
# =============================================================================

class Logger:
    """Dual output to console and file."""

    def __init__(self, log_file=None):
        self.terminal = sys.stdout
        self.log_file = None

        if log_file:
            # <-- MODIFIED: Ensure log directory exists (now handled by config)
            # log_file.parent.mkdir(parents=True, exist_ok=True)
            self.log_file = open(log_file, 'w', buffering=1)

    def write(self, message):
        self.terminal.write(message)
        if self.log_file:
            self.log_file.write(message)

    def flush(self):
        self.terminal.flush()
        if self.log_file:
            self.log_file.flush()

    def close(self):
        if self.log_file:
            self.log_file.close()

# =============================================================================
# CACHING
# =============================================================================

def get_cache_key(blast_file, identity, coverage, evalue):
    """Generate unique cache key."""
    blast_mtime = blast_file.stat().st_mtime if blast_file.exists() else 0
    key_str = f"{blast_file}_{blast_mtime}_{identity}_{coverage}_{evalue}"
    return hashlib.md5(key_str.encode()).hexdigest()

def get_cached_results(cache_file, blast_file, identity, coverage, evalue):
    """Load cached results if valid."""
    if not cache_file.exists():
        return None

    try:
        with open(cache_file, 'rb') as f:
            cached = pickle.load(f)

        expected_key = get_cache_key(blast_file, identity, coverage, evalue)
        if cached.get('cache_key') == expected_key:
            return cached
    except Exception:
        pass

    return None

def save_cached_results(cache_file, blast_file, identity, coverage, evalue,
                        filtered_ids, hit_details, blast_hits):
    """Save results to cache."""
    try:
        cache_data = {
            'cache_key': get_cache_key(blast_file, identity, coverage, evalue),
            'filtered_ids': filtered_ids,
            'hit_details': hit_details,
            'blast_hits': blast_hits,
            'timestamp': datetime.now().isoformat()
        }

        with open(cache_file, 'wb') as f:
            pickle.dump(cache_data, f)

        return True
    except Exception:
        return False

# =============================================================================
# DATABASE UTILITIES
# =============================================================================

def check_blast_db(db_path):
    """Check if BLAST database files exist."""
    extensions = ['.phr', '.pin', '.psq']
    for ext in extensions:
        if Path(str(db_path) + ext).exists():
            return True
    return False

def get_blast_db_info(db_path):
    """Get database information."""
    import subprocess

    info = {
        'sequences': None,
        'residues': None,
        'size_bytes': 0,
        'files': []
    }

    try:
        result = subprocess.run(
            ['blastdbcmd', '-db', str(db_path), '-info'],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            for line in result.stdout.split('\n'):
                line_lower = line.lower()

                if 'sequences' in line_lower:
                    parts = line.split()
                    for part in parts:
                        clean = part.replace(',', '')
                        if clean.isdigit():
                            info['sequences'] = int(clean)
                            break

                elif 'bases' in line_lower or 'letters' in line_lower:
                    parts = line.split()
                    for part in parts:
                        clean = part.replace(',', '')
                        if clean.isdigit():
                            info['residues'] = int(clean)
                            break

            # Get file sizes
            for ext in ['.phr', '.pin', '.psq']:
                db_file = Path(str(db_path) + ext)
                if db_file.exists():
                    size = db_file.stat().st_size
                    info['size_bytes'] += size
                    info['files'].append({'name': db_file.name, 'size': size})

    except Exception:
        pass

    return info

def estimate_blast_time(num_queries, db_sequences, threads):
    """Estimate BLAST runtime."""
    if not db_sequences:
        return None

    base_rate = 50

    if db_sequences > 100000:
        base_rate *= 0.5
    elif db_sequences > 1000000:
        base_rate *= 0.3

    effective_rate = base_rate * threads
    minutes = num_queries / effective_rate

    return minutes * 60

# =============================================================================
# UTILITIES
# =============================================================================

def format_bytes(bytes_size):
    """Format bytes to human-readable."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"

def format_time(seconds):
    """Format seconds to human-readable."""
    if seconds < 60:
        return f"{seconds:.1f} seconds"
    elif seconds < 3600:
        return f"{seconds / 60:.1f} minutes"
    else:
        return f"{seconds / 3600:.1f} hours"

def print_step_time(start_time):
    """Print step completion time."""
    elapsed = time.time() - start_time
    print(f"  ⏱ Completed in {format_time(elapsed)}")

def determine_thread_count(threads_arg):
    """Determine number of threads."""
    total_cpus = multiprocessing.cpu_count()
    default_threads = max(1, total_cpus - 4)

    warning = None

    if threads_arg is None:
        threads = default_threads
        mode = "auto"
    elif threads_arg == 0:
        threads = total_cpus
        mode = "all"
        if total_cpus > 8:
            warning = "Using ALL threads may impact system"
    else:
        threads = threads_arg
        mode = "user"
        if threads > total_cpus:
            warning = f"Specified {threads} but only {total_cpus} available"
            threads = total_cpus
        elif threads > total_cpus - 2:
            warning = "Using nearly all threads may impact system"

    return threads, mode, warning, total_cpus

def run_blastp_with_progress(query_fasta, blast_db, output_file, evalue, num_threads, num_queries):
    """Run BLAST with progress."""
    import subprocess

    print(f"\n  Starting BLAST...")
    print(f"    Queries: {num_queries:,}")
    print(f"    Database: {blast_db.name}")
    print(f"    Threads: {num_threads}")

    blast_start = time.time()

    cmd = [
        'blastp',
        '-db', str(blast_db),
        '-query', str(query_fasta),
        '-out', str(output_file),
        '-outfmt', '6',
        '-evalue', str(evalue),
        '-num_threads', str(num_threads)
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    last_size = 0
    while process.poll() is None:
        time.sleep(5)

        if output_file.exists():
            current_size = output_file.stat().st_size
            if current_size > last_size:
                elapsed = time.time() - blast_start
                print(f"\r  Progress: {format_time(elapsed)} | "
                      f"Output: {format_bytes(current_size)}" + " " * 10,
                      end='', flush=True)
                last_size = current_size

    returncode = process.wait()
    print()

    if returncode != 0:
        stderr = process.stderr.read()
        raise RuntimeError(f"BLAST failed:\n{stderr}")

    blast_elapsed = time.time() - blast_start

    if output_file.exists():
        print(f"\n  ✓ BLAST completed!")
        print(f"    Size: {format_bytes(output_file.stat().st_size)}")
        print(f"    Time: {format_time(blast_elapsed)}")
    else:
        print(f"\n  ✓ BLAST completed (no hits)")
        print(f"    Time: {format_time(blast_elapsed)}")

    return blast_elapsed

# =============================================================================
# DRY RUN
# =============================================================================

# <-- MODIFIED: Added project_name
def dry_run(db_name, db_config, identity, coverage, evalue, threads, skip_blast, project_name=None):
    """Preview without executing."""

    print("\n" + "=" * 70)
    print("🔍 DRY RUN - No files will be modified")
    print("=" * 70)

    print(f"\n📋 Configuration:")
    print(f"  Database: {db_config['name']}")
    # <-- MODIFIED: Added project name to output
    if project_name:
        print(f"  Project: {project_name}")
    print(f"  Action: {db_config['action'].upper()}")
    print(f"  Selection: {db_config.get('selection', 'negative').upper()}")
    if db_config.get('selection') == 'negative':
        print(f"  Strategy: Remove matches (reject {db_name}-like proteins)")
    else:
        print(f"  Strategy: Keep only matches (positive selection)")
    print(f"  Thresholds: {identity}% / {coverage}% / {evalue}")
    print(f"  Threads: {threads}")

    # Check input
    print(f"\n📥 Input:")
    # <-- MODIFIED: Pass project_name
    input_file = config.get_input_file(db_name, project_name)
    # <-- MODIFIED: Get project-specific output dir
    project_output_dir = config.get_project_output_dir(project_name)
    project_input_dir = config.get_project_input_dir(project_name)

    if db_name == 'human':
        # <-- MODIFIED: Use new function and pass project_name
        combined_file = config.get_combined_sequences_file(project_name)
        if combined_file.exists():
            seq_count = sum(1 for line in open(combined_file) if line.startswith('>'))
            print(f"  ✓ Combined sequences: {seq_count:,} (from {combined_file.name})")
        else:
            # <-- MODIFIED: Check project input dir
            faa_files = list(project_input_dir.glob("*.faa"))
            if faa_files:
                total = sum(sum(1 for line in open(f) if line.startswith('>')) for f in faa_files)
                print(f"  ✓ Found {len(faa_files)} files in {project_input_dir.name}, ~{total:,} sequences")
            else:
                print(f"  ✗ No input files found in {project_input_dir}")
                return
    else:
        prev_db = config.PIPELINE_FLOW[db_name]['input_source']
        # <-- MODIFIED: Pass project_name
        prev_passing = config.get_passing_file(prev_db, project_name)

        if prev_passing.exists():
            seq_count = sum(1 for line in open(prev_passing) if line.startswith('>'))
            print(f"  ✓ From {prev_db}: {seq_count:,} sequences")
        else:
            print(f"  ✗ Previous step not complete ({prev_passing.name} not found)")
            return

    # Check database
    print(f"\n💾 Database:")
    if check_blast_db(db_config['db_path']):
        print(f"  ✓ Found: {db_config['db_path'].name}")

        db_info = get_blast_db_info(db_config['db_path'])
        if db_info['sequences']:
            print(f"    Sequences: {db_info['sequences']:,}")
        if db_info['size_bytes']:
            print(f"    Size: {format_bytes(db_info['size_bytes'])}")
    else:
        print(f"  ✗ Not found: {db_config['db_path']}")
        return

    # Estimate
    print(f"\n⚙️ Resources:")
    print(f"  CPUs: {multiprocessing.cpu_count()}")
    print(f"  Threads: {threads}")

    if not skip_blast and 'seq_count' in locals() and db_info.get('sequences'):
        est_time = estimate_blast_time(seq_count, db_info['sequences'], threads)
        if est_time:
            print(f"  Estimated: {format_time(est_time)}")

    # Files
    print(f"\n📤 Output:")
    # <-- MODIFIED: Show project output dir
    print(f"  Directory: {project_output_dir}")
    print(f"  → {input_file.name}")
    # <-- MODIFIED: Pass project_name
    print(f"  → {config.get_blast_file(db_name, project_name).name}")
    print(f"  → {config.get_filtered_file(db_name, project_name).name}")
    print(f"  → {config.get_passing_file(db_name, project_name).name}")
    print(f"  → {config.get_summary_file(db_name, project_name).name}")

    print(f"\n" + "=" * 70)
    print("✓ Dry run complete")
    print(f"\nTo run: python3 filter_database.py {db_name} --project {project_name}")
    if skip_blast:
        print(f"        (with --skip-blast flag)")
    print("=" * 70)

# =============================================================================
# MAIN FILTER
# =============================================================================

# <-- MODIFIED: Added project_name
def filter_database(db_name, identity, coverage, evalue, skip_blast, threads_arg,
                    log_file, dry_run_mode, use_cache, project_name=None):
    """Main filtering function."""

    # Validate
    if db_name not in DATABASE_CONFIGS:
        print(f"✗ Unknown database: {db_name}")
        sys.exit(1)

    db_config = DATABASE_CONFIGS[db_name]

    # Threads
    threads, thread_mode, thread_warning, total_cpus = determine_thread_count(threads_arg)

    # Dry run
    if dry_run_mode:
        # <-- MODIFIED: Pass project_name
        dry_run(db_name, db_config, identity, coverage, evalue, threads, skip_blast, project_name)
        return

    # Logging
    logger = None
    if log_file or log_file is None:
        # <-- MODIFIED: Get project output dir
        project_output_dir = config.get_project_output_dir(project_name)
        # project_output_dir.mkdir(parents=True, exist_ok=True) # <-- Handled by config func

        if log_file is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            # <-- MODIFIED: Pass project_name
            log_file = config.get_log_file(db_name, timestamp, project_name)
        else:
            # <-- MODIFIED: Use project_output_dir
            log_file = project_output_dir / log_file

        logger = Logger(log_file)
        sys.stdout = logger

    try:
        overall_start = time.time()
        start_datetime = datetime.now()

        # Header
        print("\n" + "=" * 70)
        print(f"RUNNING: {db_config['name']} Filter")
        print("=" * 70)

        print(f"Start: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        if logger:
            print(f"📝 Log: {log_file}")
        
        # <-- MODIFIED: Print project name
        if project_name:
            print(f"📁 Project: {project_name}")

        print(f"\nDatabase: {db_config['name']}")
        print(f"Action: {db_config['action'].upper()}")
        print(f"Selection: {db_config.get('selection', 'negative').upper()}")
        if db_config.get('selection') == 'negative':
            print(f"Strategy: Remove matches (reject {db_name}-like)")
        else:
            print(f"Strategy: Keep only matches (positive selection)")
        print(f"Mode: {'Skip-BLAST' if skip_blast else 'Full'}")

        print(f"\n🔧 Resources:")
        print(f"  CPUs: {total_cpus} | Threads: {threads} ({thread_mode})")
        if thread_warning:
            print(f"  ⚠ {thread_warning}")

        print(f"\n🎯 Thresholds:")
        print(f"  Identity: {identity}% | Coverage: {coverage}% | E-value: {evalue}")
        if use_cache:
            print(f"  Caching: ENABLED")

        # Setup
        print("\n" + "=" * 70)
        print("STEP 1: Setup")
        print("=" * 70)
        step1_start = time.time()

        # <-- MODIFIED: Get project output dir (already created by log setup)
        project_output_dir = config.get_project_output_dir(project_name)
        project_input_dir = config.get_project_input_dir(project_name)

        if not skip_blast:
            print(f"\n  → Checking database...")
            if not check_blast_db(db_config['db_path']):
                print(f"\n✗ Database not found: {db_config['db_path']}")
                sys.exit(1)

            print(f"  ✓ Database: {db_config['db_path']}")

            db_info = get_blast_db_info(db_config['db_path'])
            if db_info['sequences'] or db_info['size_bytes']:
                print(f"  📊 Stats:")
                if db_info['sequences']:
                    print(f"     Sequences: {db_info['sequences']:,}")
                if db_info['size_bytes']:
                    print(f"     Size: {format_bytes(db_info['size_bytes'])}")

        print_step_time(step1_start)

        # Input
        print("\n" + "=" * 70)
        print("STEP 2: Input")
        print("=" * 70)
        step2_start = time.time()

        # <-- MODIFIED: Pass project_name
        input_file = config.get_input_file(db_name, project_name)
        # <-- MODIFIED: Use new function and pass project_name
        combined_file = config.get_combined_sequences_file(project_name)

        if db_name == 'human':
            # First step: use combined file from web app (which is in output dir)
            if not combined_file.exists():
                # <-- MODIFIED: Fallback to combining from project *input* dir
                print(f"\n  → {combined_file.name} not found. Scanning {project_input_dir}...")
                faa_files = list(project_input_dir.glob("*.faa"))

                if not faa_files:
                    print(f"\n✗ No .faa files found in {project_input_dir}")
                    sys.exit(1)

                print(f"  ✓ Found {len(faa_files)} files")
                print(f"\n  → Combining into {combined_file.name}...")

                total_seqs = utils.combine_fasta_files(
                    input_dir=project_input_dir,
                    output_file=combined_file
                )
                print(f"  ✓ Combined: {total_seqs:,} sequences")
                seq_count = total_seqs
            else:
                seq_count = sum(1 for line in open(combined_file) if line.startswith('>'))
                print(f"\n  ✓ Combined file exists: {seq_count:,} sequences")

            # Copy to human_input.faa
            print(f"\n  → Copying to {input_file.name}...")
            shutil.copy(combined_file, input_file)
            print(f"  ✓ Input ready: {input_file.name}")

        else:
            # Subsequent steps: copy from previous
            prev_db = config.PIPELINE_FLOW[db_name]['input_source']
            # <-- MODIFIED: Pass project_name
            prev_passing = config.get_passing_file(prev_db, project_name)

            if not prev_passing.exists():
                print(f"\n✗ Previous step ({prev_db}) not complete. File not found:")
                print(f"  {prev_passing}")
                sys.exit(1)

            print(f"\n  → Loading from {prev_db} step...")
            shutil.copy(prev_passing, input_file)

            seq_count = sum(1 for line in open(input_file) if line.startswith('>'))
            print(f"  ✓ Input: {input_file.name}")
            print(f"  ✓ Sequences: {seq_count:,}")

        print(f"\n  📊 Input: {input_file.name} ({seq_count:,} sequences)")

        print_step_time(step2_start)

        # Analysis
        print("\n" + "=" * 70)
        print("STEP 3: Analysis")
        print("=" * 70)
        step3_start = time.time()

        print(f"\n  → Calculating lengths...")
        seq_lengths = utils.get_sequence_lengths(input_file)
        print(f"  ✓ Processed: {len(seq_lengths):,}")

        filtered_seqs = seq_lengths # Always initialize with all sequences

        if db_name == 'human':
            print(f"\n  → Length filter ({config.MIN_PROTEIN_LENGTH}-{config.MAX_PROTEIN_LENGTH} aa)...")

            filtered_seqs = {
                seq_id: length
                for seq_id, length in seq_lengths.items()
                if config.MIN_PROTEIN_LENGTH <= length <= config.MAX_PROTEIN_LENGTH
            }

            removed = len(seq_lengths) - len(filtered_seqs)
            print(f"  ✓ Pass: {len(filtered_seqs):,}")
            if removed > 0:
                print(f"  ✗ Removed: {removed:,} ({(removed/len(seq_lengths)*100):.2f}%)")
        else: # For other steps, just log that it was skipped
             print(f"\n  → Length filter skipped for this step.")


        print_step_time(step3_start)

        # BLAST
        print("\n" + "=" * 70)
        print("STEP 4: BLAST")
        print("=" * 70)
        step4_start = time.time()

        # <-- MODIFIED: Pass project_name
        blast_output = config.get_blast_file(db_name, project_name)

        if skip_blast:
            print("\n  ⚡ BLAST SKIPPED")

            if not blast_output.exists():
                print(f"\n✗ BLAST output not found: {blast_output.name}")
                sys.exit(1)

            size = blast_output.stat().st_size
            lines = sum(1 for _ in open(blast_output))

            print(f"  ✓ Using existing: {blast_output.name}")
            print(f"    Size: {format_bytes(size)} | Hits: {lines:,}")
        else:
            print(f"\n  → Running BLAST ({threads} threads)...")

            if 'db_info' in locals() and db_info.get('sequences'):
                est_time = estimate_blast_time(len(filtered_seqs), db_info['sequences'], threads)
                if est_time:
                    print(f"  ⏱ Estimated: {format_time(est_time)}")

            run_blastp_with_progress(
                query_fasta=input_file,
                blast_db=db_config['db_path'],
                output_file=blast_output,
                evalue=evalue,
                num_threads=threads,
                num_queries=len(filtered_seqs)
            )

        print_step_time(step4_start)

        # Filtering
        print("\n" + "=" * 70)
        print("STEP 5: Filtering")
        print("=" * 70)
        step5_start = time.time()

        # <-- MODIFIED: Pass project_name
        cache_file = config.get_cache_file(db_name, project_name)
        filtered_ids = None
        hit_details = None
        blast_hits = None

        if use_cache:
            print("\n  → Checking cache...")
            cached = get_cached_results(cache_file, blast_output, identity, coverage, evalue)

            if cached:
                print(f"  ✓ Using cache!")
                print(f"     Cached: {cached['timestamp']}")
                filtered_ids = cached['filtered_ids']
                hit_details = cached['hit_details']
                blast_hits = cached['blast_hits']
                print(f"     Raw: {len(blast_hits):,} | Passing: {len(filtered_ids):,}")

        if filtered_ids is None:
            print(f"\n  → Parsing BLAST...")
            blast_hits = utils.parse_blast_results(blast_output)
            print(f"  ✓ Raw hits: {len(blast_hits):,}")

            if blast_hits:
                print(f"\n  → Applying thresholds...")
                print(f"     Identity ≥ {identity}%")
                print(f"     Coverage ≥ {coverage}%")
                print(f"     E-value ≤ {evalue}")

                filtered_ids, hit_details = utils.filter_blast_hits(
                    hits=blast_hits,
                    query_lengths=filtered_seqs,
                    pct_identity=identity,
                    coverage=coverage,
                    evalue=evalue
                )

                print(f"\n  ✓ Passing: {len(filtered_ids):,} ({(len(filtered_ids)/len(blast_hits)*100):.2f}%)")
                
                if use_cache:
                    print(f"\n  → Saving cache...")
                    if save_cached_results(cache_file, blast_output, identity, coverage,
                                        evalue, filtered_ids, hit_details, blast_hits):
                        print(f"  ✓ Cached: {format_bytes(cache_file.stat().st_size)}")
            else:
                filtered_ids = set()
                hit_details = {}

        if hit_details:
            # <-- MODIFIED: Pass project_name
            filtered_file = config.get_filtered_file(db_name, project_name)
            utils.save_filtered_results(
                hit_details=hit_details,
                output_file=filtered_file,
                action=db_config['action']
            )

        print_step_time(step5_start)

        # Apply action
        print("\n" + "=" * 70)
        print(f"STEP 6: {db_config['action'].upper()}")
        print("=" * 70)
        step6_start = time.time()

        # <-- MODIFIED: Pass project_name
        passing_file = config.get_passing_file(db_name, project_name)
        selection_type = db_config.get('selection', 'negative')

        if db_config['action'] == 'reject':
            if selection_type == 'negative':
                # Negative selection: Remove matches (e.g., human-like proteins)
                print(f"\n  → Rejecting matches (remove {db_name}-like proteins)...")
                passing_ids = set(filtered_seqs.keys()) - filtered_ids

                print(f"     Input: {len(filtered_seqs):,}")
                print(f"     Matches (rejected): {len(filtered_ids):,}")
                print(f"     Output: {len(passing_ids):,}")

                extracted = utils.extract_sequences_by_id(
                    input_fasta=input_file,
                    seq_ids=passing_ids,
                    output_fasta=passing_file
                )

                print(f"\n  📊 Final:")
                print(f"     ✓ Passed: {extracted:,}")
                print(f"     ✗ Rejected: {len(filtered_ids):,} ({(len(filtered_ids)/len(filtered_seqs)*100):.2f}%)")

            else:
                # Positive selection: Keep only matches (e.g., essential, virulent, ESKAPE)
                print(f"\n  → Positive selection (keep only {db_name} proteins)...")
                passing_ids = filtered_ids

                print(f"     Input: {len(filtered_seqs):,}")
                print(f"     Matches (kept): {len(filtered_ids):,}")
                print(f"     Non-matches (rejected): {len(filtered_seqs) - len(filtered_ids):,}")

                if passing_ids:
                    extracted = utils.extract_sequences_by_id(
                        input_fasta=input_file,
                        seq_ids=passing_ids,
                        output_fasta=passing_file
                    )

                    print(f"\n  📊 Final:")
                    print(f"     ✓ Kept: {extracted:,}")
                    print(f"     ✗ Rejected: {len(filtered_seqs) - len(filtered_ids):,} ({((len(filtered_seqs) - len(filtered_ids))/len(filtered_seqs)*100):.2f}%)")
                else:
                    print(f"\n  ⚠ WARNING: No proteins matched!")
                    print(f"     All {len(filtered_seqs):,} proteins were rejected.")
                    # Create empty file
                    passing_file.touch()

        print_step_time(step6_start)

        # Summary
        overall_elapsed = time.time() - overall_start
        end_datetime = datetime.now()

        selection_type = db_config.get('selection', 'negative')
        if selection_type == 'negative':
            final_count = len(filtered_seqs) - len(filtered_ids) if filtered_ids else len(filtered_seqs)
            action_desc = f"Rejected {len(filtered_ids) if filtered_ids else 0} matches"
        else:
            final_count = len(filtered_ids) if filtered_ids else 0
            action_desc = f"Kept {len(filtered_ids) if filtered_ids else 0} matches"

        stats = {
            "Start": start_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            "End": end_datetime.strftime('%Y-%m-%d %H:%M:%S'),
            "Runtime": format_time(overall_elapsed),
            "Project": str(project_name), # <-- MODIFIED: Add project name
            "Threads": str(threads),
            "": "",
            "Database": db_config['name'],
            "Action": db_config['action'],
            "Selection": selection_type,
            "Mode": "Skip-BLAST" if skip_blast else "Full",
            " ": "",
            "Input": len(seq_lengths),
            "After length filter": len(filtered_seqs),
            "BLAST hits": len(blast_hits) if blast_hits else 0,
            "Passing thresholds": len(filtered_ids) if filtered_ids else 0,
            "Final output": final_count,
            "  ": "",
            "Action taken": action_desc,
            "   ": "",
            "Thresholds": "",
            "  Identity": f"{identity}%",
            "  Coverage": f"{coverage}%",
            "  E-value": f"{evalue}",
        }

        # <-- MODIFIED: Pass project_name
        summary_file = config.get_summary_file(db_name, project_name)
        utils.create_summary_report(
            output_file=summary_file,
            step_name=f"{db_config['name']} Filter",
            stats=stats
        )

        print(f"\n{'=' * 70}")
        print(f"✓✓✓ {db_config['name']} Filter COMPLETE ✓✓✓")
        print(f"{'=' * 70}")

        print(f"\n{'=' * 70}")
        print("SUMMARY OF THIS STEP")
        print(f"Total runtime: {format_time(overall_elapsed)}")

        # <-- MODIFIED: Use project output dir
        print(f"\nFiles in {project_output_dir}:")
        print(f"  → {input_file.name}")
        print(f"  → {blast_output.name}")
        if hit_details:
            # <-- MODIFIED: Pass project_name
            print(f"  → {config.get_filtered_file(db_name, project_name).name}")
        print(f"  → {passing_file.name}")
        print(f"  → {summary_file.name}")
        if logger:
            print(f"  → {log_file.name}")
        print()

    finally:
        if logger:
            logger.close()
        sys.stdout = sys.__stdout__

# =============================================================================
# CLI
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Filter sequences (v4.1) - Project-aware',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
python3 filter_database.py human --dry-run
python3 filter_database.py human --threads 16 --cache
python3 filter_database.py deg -s --identity 40
python3 filter_database.py eskape --project Trial2 --threads 8
"""
    )

    parser.add_argument('database', choices=list(DATABASE_CONFIGS.keys()),
                        help='Database to filter against')
    parser.add_argument('--identity', '-i', type=float, default=35.0,
                        help='Minimum identity percentage of the resultant sequence (default: 35.0)')
    parser.add_argument('--coverage', '-c', type=float, default=70.0,
                        help='Minimum query coverage percentage (default: 70.0)')
    parser.add_argument('--evalue', '-e', type=float, default=1e-5,
                        help='Maximum e-value score cutoff (default: 1e-5)')
    parser.add_argument('--skip-blast', '-s', action='store_true',
                        help='Skip BLAST, in case of BLAST already performed use an existing BLAST result')
    parser.add_argument('--threads', '-t', type=int, default=None,
                        help='Threads (default: auto)')
    parser.add_argument('--log', '-l', type=str, default=None,
                        help='Log file name')
    parser.add_argument('--no-log', action='store_true',
                        help='Disable logging')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview the entire run dynamics without executing the run')
    parser.add_argument('--cache', action='store_true',
                        help='Use result caching for faster re-filtering')
    
    # <-- MODIFIED: Added project argument
    parser.add_argument('--project', type=str, default=None,
                        help='Project name to use for input/output paths (required by web app)')

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    log_file = args.log
    if args.no_log:
        log_file = False

    try:
        filter_database(
            db_name=args.database,
            identity=args.identity,
            coverage=args.coverage,
            evalue=args.evalue,
            skip_blast=args.skip_blast,
            threads_arg=args.threads,
            log_file=log_file,
            dry_run_mode=args.dry_run,
            use_cache=args.cache,
            project_name=args.project  # <-- MODIFIED: Pass project argument
        )
    except KeyboardInterrupt:
        print("\n\n✗ Interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()