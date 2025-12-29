#!/usr/bin/env python3
"""
Bacterial Drug Target Pipeline - Web Application (FIXED v7.2)
===========================================================
Flask server for web-based pipeline interface
FIXES: Project isolation, File paths, Syntax errors, Import statements
"""

import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template, request, jsonify, send_file, session, send_from_directory
from flask_socketio import SocketIO, emit
from flask_cors import CORS
import os
import sys
import json
import signal
import shutil
import time
import secrets
from pathlib import Path
import re
from datetime import datetime
import csv
from werkzeug.utils import secure_filename
import threading
import subprocess
import config
import utils


# Configuration
BASE_DIR = Path(__file__).resolve().parent.parent # Go up one level to the project root
WEBAPP_DIR = Path(__file__).parent
SCRIPTS_DIR = WEBAPP_DIR
JOBS_DIR = WEBAPP_DIR / "jobs"
OUTPUT_DIR = BASE_DIR / "targetX"
MSA_DIR = BASE_DIR / "MSA"
VALIDATION_TEMP_DIR = WEBAPP_DIR / "uploads"
STRUCTURE_DIR = BASE_DIR / "Structure"

UPLOAD_FOLDER = BASE_DIR / 'input_sequences'
ALLOWED_EXTENSIONS = {'faa', 'fasta', 'fa'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Define the 21 standard amino acids (including X for unknown)
STANDARD_AMINO_ACIDS = set("ARNDCEQGHILKMFPSTWYVXUOBZ")

PROJECTS_DIR = WEBAPP_DIR / "projects"
for directory in [JOBS_DIR, MSA_DIR, PROJECTS_DIR, VALIDATION_TEMP_DIR]:
    directory.mkdir(parents=True, exist_ok=True)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['UPLOAD_FOLDER'] = 'input_sequences'
app.config['MAX_CONTENT_LENGTH'] = 2000 * 1024 * 1024  # 2000MB max file size

# Initialize extensions
CORS(app)
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='eventlet',
    logger=True,
    engineio_logger=True,
    ping_timeout=60, # Keep connection alive
    ping_interval=25,
    allow_upgrades=False # FIX: Prevents WebSocket upgrade issues and 400 errors
)

@app.errorhandler(413)
def request_entity_too_large(error):
    """Handle file too large errors"""
    return jsonify({
        'success': False,
        'message': 'File too large. Maximum size is 2GB.'
    }), 413

# Store active jobs
active_jobs = {}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def format_time(seconds):
    """Format seconds to human-readable time"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{mins}m {secs}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        return f"{hours}h {mins}m"

def create_job(job_id, job_type, config):
    """Create a new job entry"""
    # Get current project from session
    current_project = session.get('current_project', 'default')
    
    job_data = {
        'id': job_id,
        'type': (
            'Full Pipeline' if job_type == 'pipeline_all' 
            else 'Alignment' if job_type == 'alignment'
            else job_type
        ),
        'project': current_project,  # Add project association
        'config': config,
        'status': 'queued',
        'progress': 0,
        'created_at': datetime.now().isoformat(),
        'started_at': datetime.now().isoformat(),
        'ended_at': None,
        'runtime_seconds': 0,
        'runtime': None,
        'current_step': None,
        'logs': [],
        'results': None,
        'process': None
    }
    
    # Save to file
    job_file = JOBS_DIR / f"{job_id}.json"
    with open(job_file, 'w') as f:
        save_data = {k: v for k, v in job_data.items() if k != 'process'}
        json.dump(save_data, f, indent=2)
    
    active_jobs[job_id] = job_data
    return job_data

def update_job(job_id, updates):
    """Update job status"""
    if job_id in active_jobs:
        active_jobs[job_id].update(updates)
        
        # Calculate runtime if job completed
        if 'ended_at' in updates and active_jobs[job_id].get('started_at'):
            try:
                start = datetime.fromisoformat(active_jobs[job_id]['started_at'])
                end = datetime.fromisoformat(updates['ended_at'])
                runtime_seconds = (end - start).total_seconds()
                active_jobs[job_id]['runtime_seconds'] = runtime_seconds
                active_jobs[job_id]['runtime'] = format_time(runtime_seconds)
            except Exception as e:
                print(f"Error calculating runtime: {e}")
        
        # Save to file (exclude process object)
        job_file = JOBS_DIR / f"{job_id}.json"
        try:
            with open(job_file, 'w') as f: # Exclude non-serializable objects from the file as well
                save_data = {k: v for k, v in active_jobs[job_id].items() if k not in ['process', 'timeout_timer']}
                json.dump(save_data, f, indent=2)
        except Exception as e:
            print(f"Error saving job: {e}")
        
        # Emit update via WebSocket
        try:
            socketio.emit('job_update', {
                'job_id': job_id, # Exclude non-serializable objects from WebSocket updates
                'data': {k: v for k, v in active_jobs[job_id].items() if k not in ['process', 'timeout_timer']}
            })
        except Exception as e:
            print(f"Error emitting job update: {e}")

def add_job_log(job_id, message, level='info'):
    """Add log entry to job"""
    if job_id in active_jobs:
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message
        }
        active_jobs[job_id]['logs'].append(log_entry)
        
        # Emit log via WebSocket
        try:
            socketio.emit('job_log', {
                'job_id': job_id,
                'log': log_entry
            })
        except Exception:
            pass

def run_pipeline_step(job_id, database, config):
    """Run a single pipeline step in background"""
    
    def run_step():
        try:
            project = active_jobs[job_id].get('project', 'default')
            
            update_job(job_id, {
                'status': 'running',
                'started_at': datetime.now().isoformat(),
                'current_step': f'Starting {database} filter',
                'progress': 5
            })
            
            add_job_log(job_id, f"Starting {database} filter for project: {project}...")
            
            cmd = [
                sys.executable,
                str(SCRIPTS_DIR / 'blast_filter.py'),
                database,
                '--project', project
            ]
            
            if config.get('threads'):
                cmd.extend(['--threads', str(config['threads'])])
            if config.get('identity'):
                cmd.extend(['--identity', str(config['identity'])])
            if config.get('coverage'):
                cmd.extend(['--coverage', str(config['coverage'])])
            if config.get('skip_blast'):
                cmd.append('-s')
            if config.get('cache'):
                cmd.append('--cache')
            
            add_job_log(job_id, f"Command: {' '.join(cmd)}")
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            def kill_process_timeout(process, job_id, timeout_seconds=7200):
                """Kill process after timeout (default 2 hours)"""
                def timeout_handler():
                    if process.poll() is None:  # Still running
                        try:
                            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                            add_job_log(job_id, f"⚠️ Process terminated after {timeout_seconds}s timeout", 'error')
                            update_job(job_id, {'status': 'failed', 'ended_at': datetime.now().isoformat()})
                        except Exception as e:
                            add_job_log(job_id, f"Error terminating process: {e}", 'error')
                
                timer = threading.Timer(timeout_seconds, timeout_handler)
                timer.daemon = True
                timer.start()
                return timer

            # After line 209 (after process creation):
            timeout_timer = kill_process_timeout(process, job_id, timeout_seconds=7200)
            active_jobs[job_id]['timeout_timer'] = timeout_timer

            # When process completes (before line 300), cancel timer:
            if 'timeout_timer' in active_jobs[job_id]:
                active_jobs[job_id]['timeout_timer'].cancel()

            active_jobs[job_id]['process'] = process
            
            # Track BLAST output file for progress
            blast_output = OUTPUT_DIR / project / f"{database}_blast.txt"
            blast_started = False
            last_blast_size = 0
            
            # Stream output
            for line in process.stdout:
                line = line.strip()
                if line:
                    # Check if job was cancelled
                    if active_jobs[job_id]['status'] != 'running':
                        add_job_log(job_id, "Job cancellation detected, terminating process.", 'warning')
                        process.terminate()
                        break

                    add_job_log(job_id, line)
                    
                    # Detect stages
                    if 'STEP 1' in line or 'Setup' in line:
                        update_job(job_id, {'progress': 10, 'current_step': line})
                    elif 'STEP 2' in line or 'Input' in line:
                        update_job(job_id, {'progress': 15, 'current_step': line})
                    elif 'STEP 3' in line or 'Analysis' in line:
                        update_job(job_id, {'progress': 20, 'current_step': line})
                    elif 'STEP 4' in line or 'BLAST' in line or 'Starting BLAST' in line:
                        update_job(job_id, {'progress': 25, 'current_step': line})
                        blast_started = True
                    elif 'STEP 5' in line or 'Filtering' in line:
                        update_job(job_id, {'progress': 90, 'current_step': line})
                        blast_started = False
                    elif 'STEP 6' in line:
                        update_job(job_id, {'progress': 95, 'current_step': line})
                    
                    # Track BLAST progress by file size
                    if blast_started and blast_output.exists():
                        try:
                            current_size = blast_output.stat().st_size
                            if current_size > last_blast_size:
                                # Estimate progress: 25% to 85% during BLAST
                                # Rough estimate: every 10MB = +5% progress
                                size_mb = current_size / (1024 * 1024)
                                progress = min(85, 25 + int(size_mb * 3))
                                update_job(job_id, {
                                    'progress': progress,
                                    'current_step': f'BLAST running... ({size_mb:.1f} MB output)'
                                })
                                last_blast_size = current_size
                        except Exception:
                            pass
            
            process.wait()
            
            if process.returncode == 0:
                update_job(job_id, {
                    'status': 'completed',
                    'progress': 100,
                    'ended_at': datetime.now().isoformat(),
                    'current_step': 'Completed successfully'
                })
                add_job_log(job_id, f"{database} filter completed successfully!", 'success')
                
                results = get_step_results(database, project)
                update_job(job_id, {'results': results})
                
            else:
                update_job(job_id, {
                    'status': 'failed',
                    'ended_at': datetime.now().isoformat(),
                    'current_step': 'Failed'
                })
                add_job_log(job_id, f"{database} filter failed!", 'error')
        
        except Exception as e:
            update_job(job_id, {
                'status': 'failed',
                'ended_at': datetime.now().isoformat(),
                'current_step': f'Error: {str(e)}'
            })
            add_job_log(job_id, f"Error: {str(e)}", 'error')
    
    thread = threading.Thread(target=run_step)
    thread.daemon = True
    thread.start()

def _add_protein_to_completion_list(project_name, protein_data):
    """
    Safely appends a protein's data (including errors/warnings) to the project metadata file.
    This prevents race conditions by using a lock.
    """
    project_meta_file = BASE_DIR / 'projects' / f"{project_name}.json"
    if not project_meta_file.exists():
        return  # Cannot update if the project file doesn't exist

    with threading.Lock():
        try:
            # Read current data
            with open(project_meta_file, 'r') as f:
                meta_data = json.load(f)

            # Initialize list if it doesn't exist
            if 'completed_mutation_proteins' not in meta_data:
                meta_data['completed_mutation_proteins'] = []

            # Check if protein is already in the list to avoid duplicates, using canonical_name as the key
            existing_names = {p.get('canonical_name', p.get('name')) for p in meta_data['completed_mutation_proteins']}
            protein_key = protein_data.get('canonical_name', protein_data.get('name'))
            if protein_key not in existing_names:
                meta_data['completed_mutation_proteins'].append(protein_data)
            # Write updated data back
            with open(project_meta_file, 'w') as f:
                json.dump(meta_data, f, indent=2)

        except (IOError, json.JSONDecodeError) as e:
            print(f"Error updating project metadata for {project_name}: {e}")



def run_full_pipeline_thread(job_id, configs, project_name):
    """
    Runs the entire 4-step pipeline sequentially in a single thread.
    This is for the 'Run All' feature.
    """
    try:
        databases = ['human', 'deg', 'vfdb', 'eskape']
        progress_map = {'human': 10, 'deg': 35, 'vfdb': 60, 'eskape': 85}
        step_results = {}

        for db in databases:
            config = configs[db]
            update_job(job_id, {
                'status': 'running',
                'current_step': f'Starting {db} filter...',
                'progress': progress_map[db]
            })
            add_job_log(job_id, f"--- Starting {db.upper()} Filter ---", 'info')

            # --- Build Command ---
            cmd = [
                sys.executable,
                str(SCRIPTS_DIR / 'blast_filter.py'),
                db,
                '--project', project_name
            ]
            if config.get('threads'):
                cmd.extend(['--threads', str(config['threads'])])
            if config.get('identity'):
                cmd.extend(['--identity', str(config['identity'])])
            if config.get('coverage'):
                cmd.extend(['--coverage', str(config['coverage'])])
            if config.get('skip_blast'):
                cmd.append('-s')
            if config.get('cache'):
                cmd.append('--cache')
            
            add_job_log(job_id, f"Command: {' '.join(cmd)}")

            # --- Run Process Directly ---
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            
            # Store process so it can be killed
            active_jobs[job_id]['process'] = process

            # Stream output
            for line in process.stdout:
                line = line.strip()
                if line:
                    # Check if job was cancelled
                    if active_jobs[job_id]['status'] != 'running':
                        add_job_log(job_id, "Job cancellation detected, terminating process.", 'warning')
                        process.terminate()
                        break

                    add_job_log(job_id, line)
            
            process.wait()
            active_jobs[job_id]['process'] = None # Clear process

            # --- Check for Failure ---
            if process.returncode != 0:
                update_job(job_id, {
                    'status': 'failed',
                    'ended_at': datetime.now().isoformat(),
                    'current_step': f'Failed during {db} filter.'
                })
                add_job_log(job_id, f"Pipeline stopped: {db} filter failed.", 'error')
                return  # Stop the entire pipeline

            # --- MODIFICATION START ---
            # Get results for this step and add to master job
            step_res = get_step_results(db, project_name)
            if not step_res:
                # This means the output file wasn't found, step failed silently
                raise Exception(f"{db} step completed but no output files were found.")

            step_results[db] = step_res
            # Update the master job's results field *as we go*
            update_job(job_id, {'results': step_results})
            # --- MODIFICATION END ---

            add_job_log(job_id, f"--- {db.upper()} Filter Completed Successfully ---", 'success')       

        # --- All steps complete ---
        update_job(job_id, {
            'status': 'completed',
            'progress': 100,
            'ended_at': datetime.now().isoformat(),
            'current_step': 'All pipeline steps completed successfully.',
            'results': step_results # <-- Make sure this is here
        })
        add_job_log(job_id, "All pipeline steps completed.", 'success')

    except Exception as e:
        update_job(job_id, {
            'status': 'failed',
            'ended_at': datetime.now().isoformat(),
            'current_step': f'Error: {str(e)}'
        })
        add_job_log(job_id, f"Fatal Error: {str(e)}", 'error')

def prepare_mutational_analysis_thread(job_id, proteins, project_name):
    """
    Master thread to prepare all assets for mutational analysis. Processes each
    protein individually to prevent one failure from stopping the entire job.
    """
    try:
        update_job(job_id, {'status': 'running', 'current_step': 'Initializing...', 'progress': 1})
        add_job_log(job_id, f"Starting preparation for {len(proteins)} proteins...")

        # Initialize/clear the completed proteins list in the project metadata
        project_meta_file = BASE_DIR / 'projects' / f"{project_name}.json"
        if project_meta_file.exists():
            with open(project_meta_file, 'r+') as f:
                meta_data = json.load(f)
                meta_data['completed_mutation_proteins'] = [] # Start with an empty list
                f.seek(0)
                json.dump(meta_data, f, indent=2)
                f.truncate()

        # Define paths
        project_msa_dir = MSA_DIR / project_name
        protein_variants_dir = project_msa_dir / "proteins"
        protein_variants_dir.mkdir(parents=True, exist_ok=True)
        eskape_passing_file = OUTPUT_DIR / project_name / "eskape_passing.faa"
        if not eskape_passing_file.is_file():
            raise FileNotFoundError("Final pipeline results (eskape_passing.faa) not found.")

        # --- Step 1: Extract all variants for each selected protein (this is fast) ---
        add_job_log(job_id, "--- Step 1 of 3: Extracting Protein Variants ---", 'info')
        proteins_with_variants = set()

        # Use robust line-by-line parsing instead of split('>')
        all_parsed_sequences = []
        try:
            with open(eskape_passing_file, 'r') as f:
                current_header = None
                current_seq = []
                for line in f:
                    line = line.strip()
                    if not line: continue
                    if line.startswith('>'):
                        if current_header:
                            all_parsed_sequences.append((current_header, "".join(current_seq)))
                        current_header = line[1:].strip()
                        current_seq = []
                    else:
                        current_seq.append(line)
                if current_header:
                    all_parsed_sequences.append((current_header, "".join(current_seq)))
        except Exception as e:
            add_job_log(job_id, f"Error reading eskape_passing.faa: {e}", 'error')
            update_job(job_id, {'status': 'failed', 'ended_at': datetime.now().isoformat(), 'current_step': 'Error reading input file'})
            return

        for protein in proteins:
            canonical_name = protein.get('canonical_name', protein.get('name')) # Handle both old and new formats
            display_name = protein.get('display_name', protein.get('name'))
            safe_protein_name = utils.sanitize_protein_name(canonical_name)
            output_faa = protein_variants_dir / f"{safe_protein_name}_variants.faa"
            variants_found = []
            seen_ids = set()

            for header, seq_data in all_parsed_sequences:
                # FIX: Skip empty sequences to prevent ClustalW errors
                if not seq_data or not seq_data.strip():
                    continue

                # FIX: Match against the canonical protein name (before '=>') to be precise
                # and avoid incorrect matches from substrings in the description.
                header_id_part = header.split(' ', 1)[0]
                full_description = header.split(' ', 1)[1] if ' ' in header else ""
                canonical_header_name = full_description.split('=>')[0].strip()

                # --- NEW: More robust matching. Match if the protein name is either the
                # canonical name in the description OR the sequence ID itself.
                if canonical_name == canonical_header_name or canonical_name == header_id_part:
                    seq_id = header_id_part
                    final_header = header

                    if seq_id in seen_ids:
                        count = 1
                        while f"{seq_id}_{count}" in seen_ids:
                            count += 1
                        new_id = f"{seq_id}_{count}"
                        parts = header.split(' ', 1)
                        desc = parts[1] if len(parts) > 1 else ""
                        final_header = f"{new_id} {desc}".strip()
                        seq_id = new_id

                    seen_ids.add(seq_id)
                    variants_found.append(f">{final_header}\n{seq_data}\n")

            if variants_found:
                with open(output_faa, 'w') as f_out:
                    f_out.write("".join(variants_found))
                add_job_log(job_id, f"Saved {len(variants_found)} variants for '{display_name}' to {output_faa.name}", 'info')
                proteins_with_variants.add(canonical_name)
            else:
                add_job_log(job_id, f"No variants found for '{display_name}' in eskape_passing.faa", 'warning')

        update_job(job_id, {'progress': 10, 'current_step': 'Variant extraction complete.'})

        # --- Step 2 & 3: Process each protein individually ---
        add_job_log(job_id, "--- Step 2: Processing each protein (Alignment and SS-Prediction) ---", 'info')
        total_proteins = len(proteins)

        for i, protein in enumerate(proteins):
            canonical_name = protein.get('canonical_name', protein.get('name'))
            display_name = protein.get('display_name', protein.get('name'))
            progress = 10 + int(((i + 1) / total_proteins) * 90)
            update_job(job_id, {'progress': progress, 'current_step': f"Processing: {display_name}"})

            try:
                if canonical_name not in proteins_with_variants:
                    raise Exception("No sequence variants found for this protein.")

                aln_path = _run_alignment_for_protein(canonical_name, project_name, job_id)

                if not aln_path:
                    protein['warning'] = "Only 1 sequence variant exists; alignment and structure prediction skipped."
                    _add_protein_to_completion_list(project_name, protein)
                    continue

                reference_id = find_reference_sequence_from_aln_path(aln_path)
                if reference_id:
                    _run_ss_prediction_for_reference(canonical_name, reference_id, project_name, job_id)
                else:
                    protein['warning'] = "Could not determine reference sequence; structure prediction skipped."

                _add_protein_to_completion_list(project_name, protein)

            except Exception as e:
                error_msg = f"Failed to process '{display_name}': {str(e)}"
                add_job_log(job_id, error_msg, 'error')
                protein['error'] = str(e)
                _add_protein_to_completion_list(project_name, protein)
                continue

        # --- Finalize Job ---
        update_job(job_id, {'status': 'completed', 'progress': 100, 'ended_at': datetime.now().isoformat(), 'current_step': 'All preparations complete.'})
        add_job_log(job_id, "Mutational analysis preparation complete. You can now view alignments on the Mutational Analysis page.", 'success')

    except Exception as e:
        update_job(job_id, {'status': 'failed', 'ended_at': datetime.now().isoformat(), 'current_step': f'Fatal Error: {str(e)}'})
        add_job_log(job_id, f"Fatal Error during preparation: {str(e)}", 'error')


def run_alignment_thread(job_id, protein_name, project_name):
    """
    Runs ClustalW alignment for a specific protein's variants in a background thread.
    """
    try:
        update_job(job_id, {
            'status': 'running',
            'current_step': 'Preparing for alignment...',
            'progress': 5
        })
        add_job_log(job_id, f"--- Starting ClustalW Alignment for: {protein_name} ---", 'info')

        safe_protein_name = utils.sanitize_protein_name(protein_name)

        # Define paths
        input_faa = MSA_DIR / project_name / "proteins" / f"{safe_protein_name}_variants.faa"
        output_dir = MSA_DIR / project_name / "clustal" / safe_protein_name

        # Validate input file
        # --- MODIFICATION: If variants file is missing, attempt to regenerate it ---
        if not input_faa.is_file():
            add_job_log(job_id, f"Input variant file missing. Attempting to regenerate from source.", 'warning')
            try:
                input_faa.parent.mkdir(parents=True, exist_ok=True)
                
                eskape_passing_file = OUTPUT_DIR / project_name / "eskape_passing.faa"
                if not eskape_passing_file.is_file():
                    raise FileNotFoundError("Cannot regenerate variants: eskape_passing.faa not found.")

                all_parsed_sequences = []
                with open(eskape_passing_file, 'r') as f:
                    current_header, current_seq = None, []
                    for line in f:
                        line = line.strip()
                        if not line: continue
                        if line.startswith('>'):
                            if current_header: all_parsed_sequences.append((current_header, "".join(current_seq)))
                            current_header = line[1:].strip()
                            current_seq = []
                        else:
                            current_seq.append(line)
                    if current_header: all_parsed_sequences.append((current_header, "".join(current_seq)))

                variants_found = []
                for header, seq_data in all_parsed_sequences:
                    if not seq_data or not seq_data.strip(): continue
                    
                    # --- NEW: More robust matching. Match if the protein name is either the
                    # canonical name in the description OR the sequence ID itself.
                    header_id_part = header.split(' ', 1)[0]
                    full_description = header.split(' ', 1)[1] if ' ' in header else ""
                    canonical_header_name = full_description.split('=>')[0].strip()

                    if protein_name == canonical_header_name or protein_name == header_id_part:
                        variants_found.append(f">{header}\n{seq_data}\n")

                if variants_found:
                    with open(input_faa, 'w') as f_out:
                        f_out.write("".join(variants_found))
                    add_job_log(job_id, f"Successfully regenerated {len(variants_found)} variants for '{protein_name}'.", 'info')
                else:
                    raise Exception("Regeneration failed: No variants found in source file for this protein.")
            except Exception as e:
                add_job_log(job_id, f"Fatal: Could not regenerate variants file. {e}", 'error')
                update_job(job_id, {'status': 'failed', 'ended_at': datetime.now().isoformat(), 'current_step': f'Error: {e}'})
                return

        # --- NEW: Check sequence count before running alignment ---
        with open(input_faa, 'r') as f:
            seq_count = sum(1 for line in f if line.startswith('>'))
        
        if seq_count <= 1:
            add_job_log(job_id, f"Found only {seq_count} sequence(s). Multiple alignment is not possible.", 'warning')
            update_job(job_id, {
                'status': 'failed', # Use 'failed' to indicate it didn't run as expected
                'progress': 100,
                'ended_at': datetime.now().isoformat(),
                'current_step': 'Alignment not possible: Only one sequence variant exists for this protein.'
            })
            # No need to raise an exception, just end the thread gracefully.
            return

        # Create output directory
        output_dir.mkdir(parents=True, exist_ok=True)
        add_job_log(job_id, f"Output directory created: {output_dir}")

        # Sanitize input file to ensure unique IDs for ClustalW
        # This fixes issues where multiple variants have the same ID (e.g. "Etp")
        try:
            sequences = []
            with open(input_faa, 'r') as f:
                current_header = None
                current_seq = []
                for line in f:
                    line = line.strip()
                    if not line: continue
                    if line.startswith('>'):
                        if current_header:
                            sequences.append((current_header, "".join(current_seq)))
                        current_header = line
                        current_seq = []
                    else:
                        current_seq.append(line)
                if current_header:
                    sequences.append((current_header, "".join(current_seq)))
            
            if sequences:
                with open(input_faa, 'w') as f:
                    for i, (header, seq) in enumerate(sequences):
                        clean_header = header[1:].strip()
                        parts = clean_header.split(' ', 1)
                        original_id = parts[0]
                        desc = parts[1] if len(parts) > 1 else ""
                        # Force unique ID with counter prefix
                        new_id = f"v{i+1}_{original_id}"
                        f.write(f">{new_id} {desc}\n{seq}\n")
                add_job_log(job_id, "Sanitized input sequences to ensure unique IDs.", 'info')
        except Exception as e:
            add_job_log(job_id, f"Warning: Failed to sanitize input file: {e}", 'warning')

        # Build command - Use the simple filename, not the full path.
        cmd = ['clustalw', input_faa.name]
        add_job_log(job_id, f"Command: {' '.join(cmd)}")
        update_job(job_id, {'progress': 20, 'current_step': 'Running ClustalW...'})

        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(input_faa.parent), # FIX: Set the working directory to where the input file is
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1
            )
            active_jobs[job_id]['process'] = process
        except FileNotFoundError:
            # This error is raised if 'clustalw' command is not found
            add_job_log(job_id, "Fatal Error: 'clustalw' command not found. Please ensure it is installed and in the system's PATH.", 'error')
            update_job(job_id, {'status': 'failed', 'ended_at': datetime.now().isoformat(), 'current_step': "Error: 'clustalw' not found. Please ensure it is installed and in the system's PATH."})
            return # End the thread

        # Stream output
        for line in process.stdout:
            line = line.strip()
            if line:
                add_job_log(job_id, line)
        
        process.wait()

        # Check for output files
        # ClustalW sometimes creates output in the CWD, sometimes next to the input file.
        # We will check the input directory and move the files if necessary.
        input_dir = input_faa.parent
        expected_aln = input_dir / f"{input_faa.stem}.aln"
        expected_dnd = input_dir / f"{input_faa.stem}.dnd"

        if process.returncode == 0 and expected_aln.exists():
            # Move files to the correct output directory
            final_aln_path = output_dir / expected_aln.name
            final_dnd_path = output_dir / expected_dnd.name
            
            shutil.move(str(expected_aln), str(final_aln_path))
            add_job_log(job_id, f"Moved {expected_aln.name} to output directory.", 'info')
            if expected_dnd.exists():
                shutil.move(str(expected_dnd), str(final_dnd_path))
                add_job_log(job_id, f"Moved {expected_dnd.name} to output directory.", 'info')

            update_job(job_id, {
                'status': 'completed', 
                'progress': 100, 
                'ended_at': datetime.now().isoformat(), 
                'current_step': 'Alignment complete.',
                'results': {'alignment_file': final_aln_path.name} # Store the filename
            })
            add_job_log(job_id, f"Alignment successful. Output file: {final_aln_path.name}", 'success')
        else:
            raise Exception("ClustalW process failed or alignment file was not created.")

    except Exception as e:
        update_job(job_id, {'status': 'failed', 'ended_at': datetime.now().isoformat(), 'current_step': f'Error: {str(e)}'})
        add_job_log(job_id, f"Fatal Error: {str(e)}", 'error')

def run_structure_prediction_thread(job_id, protein_name, project_name):
    """
    Runs secondary structure prediction for a specific protein's reference sequence.
    """
    try:
        update_job(job_id, {
            'status': 'running',
            'current_step': 'Finding reference sequence...',
            'progress': 10
        })
        add_job_log(job_id, f"--- Starting Structure Prediction for: {protein_name} ---", 'info')

        safe_protein_name = utils.sanitize_protein_name(protein_name)
        aln_path = MSA_DIR / project_name / "clustal" / safe_protein_name / f"{safe_protein_name}_variants.aln"

        if not aln_path.is_file():
            raise FileNotFoundError(f"Alignment file not found for {protein_name}. Please run mutational analysis preparation first.")

        reference_id = find_reference_sequence_from_aln_path(aln_path)
        if not reference_id:
            raise ValueError(f"Could not determine reference sequence for {protein_name}.")

        update_job(job_id, {'progress': 30, 'current_step': f"Found reference: {reference_id}"})

        # This internal function already does everything we need
        output_image_url = _run_ss_prediction_for_reference(protein_name, reference_id, project_name, job_id)

        update_job(job_id, {
            'status': 'completed',
            'progress': 100,
            'ended_at': datetime.now().isoformat(),
            'current_step': 'Prediction complete.',
            'results': {'image_url': output_image_url}
        })
        add_job_log(job_id, f"Structure prediction successful. Image available at: {output_image_url}", 'success')

    except Exception as e:
        update_job(job_id, {
            'status': 'failed',
            'ended_at': datetime.now().isoformat(),
            'current_step': f'Error: {str(e)}'
        })
        add_job_log(job_id, f"Fatal Error during structure prediction: {str(e)}", 'error')


def _run_alignment_for_protein(protein_name, project_name, job_id_for_logging):
    """
    Internal helper to run ClustalW alignment. Re-uses logic from run_alignment_thread.
    Returns the path to the final alignment file.
    """
    add_job_log(job_id_for_logging, f"Starting ClustalW Alignment for: {protein_name}", 'info')
    safe_protein_name = utils.sanitize_protein_name(protein_name)

    input_faa = MSA_DIR / project_name / "proteins" / f"{safe_protein_name}_variants.faa"
    output_dir = MSA_DIR / project_name / "clustal" / safe_protein_name

    if not input_faa.is_file():
        raise FileNotFoundError(f"Input variant file not found: {input_faa}")

    with open(input_faa, 'r') as f:
        seq_count = sum(1 for line in f if line.startswith('>'))
    
    if seq_count <= 1:
        add_job_log(job_id_for_logging, f"Skipping alignment for {protein_name}: Only {seq_count} sequence variant exists.", 'warning')
        return None # Not an error, but nothing to do.

    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = ['clustalw', input_faa.name]
    add_job_log(job_id_for_logging, f"Running command: {' '.join(cmd)} in {input_faa.parent}")

    process = subprocess.run(cmd, cwd=str(input_faa.parent), capture_output=True, text=True)

    if process.returncode != 0:
        raise Exception(f"ClustalW failed for {protein_name}: {process.stderr}")

    input_dir = input_faa.parent
    expected_aln = input_dir / f"{input_faa.stem}.aln"
    expected_dnd = input_dir / f"{input_faa.stem}.dnd"

    if not expected_aln.exists():
        raise Exception(f"ClustalW finished but alignment file was not created for {protein_name}.")

    final_aln_path = output_dir / expected_aln.name
    final_dnd_path = output_dir / expected_dnd.name
    shutil.move(str(expected_aln), str(final_aln_path))
    if expected_dnd.exists():
        shutil.move(str(expected_dnd), str(final_dnd_path))

    add_job_log(job_id_for_logging, f"Alignment for {protein_name} complete.", 'success')
    return final_aln_path

def _run_ss_prediction_for_reference(protein_name, reference_id, project_name, job_id_for_logging):
    """
    Internal helper to run secondary structure prediction.
    Returns the URL to the final image.
    """
    add_job_log(job_id_for_logging, f"Starting SS Prediction for reference: {reference_id}", 'info')
    safe_protein_name = utils.sanitize_protein_name(protein_name)

    ref_dir = STRUCTURE_DIR / project_name / "reference"
    ss_dir = STRUCTURE_DIR / project_name / "secondary_structure"
    ref_dir.mkdir(parents=True, exist_ok=True)
    ss_dir.mkdir(parents=True, exist_ok=True)

    ref_fasta_path = ref_dir / f"reference_{safe_protein_name}.faa"
    ss2_file_path = ss_dir / f"ss_{safe_protein_name}.ss2"
    output_image_path = ss_dir / f"ss_visualization_{safe_protein_name}.png"
    output_image_url = f"/structure_results/{project_name}/secondary_structure/{output_image_path.name}"

    aln_path = MSA_DIR / project_name / "clustal" / safe_protein_name / f"{safe_protein_name}_variants.aln"
    if not aln_path.is_file():
        raise FileNotFoundError(f"Alignment file not found for {protein_name} to extract reference sequence.")

    with open(aln_path, 'r', encoding='utf-8') as f:
        aln_content = f.read()
    
    parsed_data = parse_and_format_aln(aln_content)
    ref_sequence_data = next((seq for seq in parsed_data['alignment_data'] if seq['id'] == reference_id), None)
    if not ref_sequence_data:
        raise ValueError(f"Reference ID {reference_id} not found in alignment file for {protein_name}.")

    ungapped_sequence = ref_sequence_data['sequence'].replace('-', '').replace('*', '')
    with open(ref_fasta_path, 'w', encoding='utf-8') as f:
        f.write(f">{reference_id}\n{ungapped_sequence}\n")

    ss_pred_script_path = WEBAPP_DIR / 'ss_pred.py'
    s4pred_tool_path = "/home/jrf-1/Desktop/jrf/project/tool/s4pred/run_model.py"
    cmd = [
        sys.executable, str(ss_pred_script_path),
        str(ref_fasta_path),
        '--s4pred', str(s4pred_tool_path),
        '--ss2', str(ss2_file_path),
        '--output', str(output_image_path)
    ]
    
    add_job_log(job_id_for_logging, f"Running command: {' '.join(cmd)}")
    process = subprocess.run(cmd, capture_output=True, text=True)
    if process.returncode != 0:
        raise RuntimeError(f"ss_pred.py script failed for {protein_name}: {process.stderr}")

    add_job_log(job_id_for_logging, f"SS Prediction for {protein_name} complete.", 'success')
    return output_image_url

def find_reference_sequence_from_aln_path(aln_path):
    with open(aln_path, 'r') as f:
        content = f.read()
    parsed_data = parse_and_format_aln(content)
    return find_reference_sequence(parsed_data['alignment_data'])

def get_step_results(database, project=None):
    """Get results for a pipeline step"""
    results = {}
    
    # Use project-specific directory if provided
    if project:
        output_dir = OUTPUT_DIR / project
    else:
        output_dir = OUTPUT_DIR
    
    # Check for output files
    passing_file = output_dir / f"{database}_passing.faa"
    filtered_file = output_dir / f"{database}_filtered.tsv"
    summary_file = output_dir / f"{database}_summary.txt"
    
    # Get input count
    if database == 'human':
        combined_file = output_dir / 'combined.faa'
        if combined_file.exists():
            try:
                with open(combined_file) as f:
                    input_count = sum(1 for line in f if line.startswith('>'))
                results['input_sequences'] = input_count
            except Exception:
                pass
    else:
        # For other steps, find previous step's output
        prev_db_map = {
            'deg': 'human',
            'vfdb': 'deg',
            'eskape': 'vfdb'
        }
        prev_db = prev_db_map.get(database)
        if prev_db:
            prev_file = output_dir / f"{prev_db}_passing.faa"
            if prev_file.exists():
                try:
                    with open(prev_file) as f:
                        input_count = sum(1 for line in f if line.startswith('>'))
                    results['input_sequences'] = input_count
                except Exception:
                    pass
    
    if passing_file.exists():
        # Count sequences
        try:
            seq_count = sum(1 for line in open(passing_file) if line.startswith('>'))
            results['passing_sequences'] = seq_count
            results['passing_file'] = str(passing_file.name)
        except Exception:
            pass
    
    if filtered_file.exists():
        # Count filtered hits
        try:
            with open(filtered_file) as f:
                hit_count = sum(1 for line in f) - 1  # Subtract header
            results['filtered_hits'] = hit_count
            results['filtered_file'] = str(filtered_file.name)
        except Exception:
            pass
    
    if summary_file.exists():
        results['summary_file'] = str(summary_file.name)
    
    return results

def get_job_by_type(database_type, project=None):
    """Find most recent job for a database type"""
    matching_jobs = [j for j in active_jobs.values() 
                    if j.get('type') == database_type 
                    and (not project or j.get('project') == project)]
    
    if matching_jobs:
        # Return most recent (by started_at)
        return sorted(matching_jobs, 
                     key=lambda x: x.get('started_at', ''), 
                     reverse=True)[0]
    return None

def load_jobs():
    """Load existing jobs from disk"""
    for job_file in JOBS_DIR.glob("*.json"):
        try:
            with open(job_file) as f:
                job_data = json.load(f)
                # If job is completed but has no results, try to get them from files
                if job_data.get('status') == 'completed' and not job_data.get('results'):
                    database = job_data.get('type')
                    project = job_data.get('project')
                    # For individual database jobs
                    if database and database != 'Full Pipeline' and project:
                        results = get_step_results(database, project)
                        if results:
                            job_data['results'] = results
                            # Save back to file
                            with open(job_file, 'w') as f:
                                json.dump(job_data, f, indent=2)
                    # For full pipeline jobs, reconstruct results from all steps
                    elif database == 'Full Pipeline' and project:
                        step_results = {}
                        databases = ['human', 'deg', 'vfdb', 'eskape']
                        for db in databases:
                            results = get_step_results(db, project)
                            if results:
                                step_results[db] = results
                        if step_results:
                            job_data['results'] = step_results
                            # Save back to file
                            with open(job_file, 'w') as f:
                                json.dump(job_data, f, indent=2)
                active_jobs[job_data['id']] = job_data
        except json.JSONDecodeError:
            print(f"Warning: Corrupted job file found: {job_file.name}. Renaming to .corrupted")
            try:
                job_file.rename(str(job_file) + '.corrupted')
            except Exception:
                pass
        except Exception as e:
            print(f"Error loading job {job_file}: {e}")

# =============================================================================
# ROUTES
# =============================================================================

@app.route('/')
def index():
    """Main dashboard"""
    return render_template('index.html')

@app.route('/configure')
def configure():
    """Configuration page"""
    # Configuration is handled via modal in index.html
    return render_template('index.html')

@app.route('/monitor/<job_id>')
def monitor(job_id):
    """Job monitoring page"""
    return render_template('monitor.html', job_id=job_id)

@app.route('/results')
def results():
    """Results viewer"""
    return render_template('results.html')

@app.route('/mutational_analysis')
def mutational_analysis():
    """Mutational Analysis page"""
    return render_template('mutational_analysis.html')

@app.route('/structure_prediction')
def structure_prediction():
    """Structure Prediction page"""
    return render_template('structure_prediction.html')

# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.route('/api/start_pipeline', methods=['POST'])
def start_pipeline():
    """Start pipeline execution"""
    data = request.json
    
    database = data.get('database')
    config = {
        'threads': data.get('threads', 18),
        'identity': data.get('identity', 35.0),
        'coverage': data.get('coverage', 90.0),
        'skip_blast': data.get('skip_blast', False),
        'cache': data.get('cache', True)
    }
    
    # Create job
    job_id = f"{database}_{int(time.time())}"
    job = create_job(job_id, database, config)
    
    # Start pipeline
    run_pipeline_step(job_id, database, config)
    
    return jsonify({
        'success': True,
        'job_id': job_id,
        'message': f'Started {database} filter'
    })

@app.route('/api/start_full_pipeline', methods=['POST'])
def start_full_pipeline():
    """Start the entire 4-step pipeline as one job"""
    data = request.json
    configs = data.get('configs')
    
    if not configs:
        return jsonify({'success': False, 'message': 'No configurations provided'})
    
    # Get current project from session
    project = session.get('current_project')
    if not project:
        return jsonify({'success': False, 'message': 'No project selected in session'})

    # Create a new "master" job for the full pipeline
    job_id = f"pipeline_all_{int(time.time())}"
    job_type = "pipeline_all"
    
    # Store all 4 configs in the master job
    job = create_job(job_id, job_type, configs)
    
    # Start the background thread to run the whole sequence
    thread = threading.Thread(target=run_full_pipeline_thread, args=(job_id, configs, project))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'job_id': job_id,
        'message': f'Started full pipeline for project {project}'
    })

@app.route('/api/run_alignment', methods=['POST'])
def run_alignment():
    """Start a ClustalW alignment job for a specific protein."""
    data = request.json
    protein_name = data.get('protein_name')

    if not protein_name:
        return jsonify({'success': False, 'message': 'No protein name provided'}), 400

    project = session.get('current_project')
    if not project:
        return jsonify({'success': False, 'message': 'No project selected in session'}), 400

    # Create a job for the alignment
    safe_protein_name = secure_filename(protein_name).replace(' ', '_')
    job_id = f"align_{safe_protein_name}_{int(time.time())}"
    job_type = "alignment"
    job_config = {'protein_name': protein_name}
    create_job(job_id, job_type, job_config)

    # Start the background thread for alignment
    thread = threading.Thread(target=run_alignment_thread, args=(job_id, protein_name, project))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'job_id': job_id, 'message': f'Started alignment for {protein_name}'})

@app.route('/api/run_structure_prediction', methods=['POST'])
def run_structure_prediction():
    """Starts a secondary structure prediction job for a specific protein."""
    data = request.json
    protein_name = data.get('protein_name')

    if not protein_name:
        return jsonify({'success': False, 'message': 'No protein name provided'}), 400

    project = session.get('current_project')
    if not project:
        return jsonify({'success': False, 'message': 'No project selected in session'}), 400

    safe_protein_name = secure_filename(protein_name).replace(' ', '_')
    job_id = f"struct_pred_{safe_protein_name}_{int(time.time())}"
    job_type = "structure_prediction"
    job_config = {'protein_name': protein_name}
    create_job(job_id, job_type, job_config)

    thread = threading.Thread(target=run_structure_prediction_thread, args=(job_id, protein_name, project))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'job_id': job_id, 'message': f'Started structure prediction for {protein_name}'})

@app.route('/api/jobs')
def get_jobs():
    """Get all jobs for current project"""
    current_project = session.get('current_project')
    
    # Filter jobs by project
    jobs_data = []
    for job in active_jobs.values():
        if current_project and job.get('project') == current_project:
            job_copy = {k: v for k, v in job.items() if k not in ['process', 'timeout_timer']}
            jobs_data.append(job_copy)
    
    return jsonify({'jobs': jobs_data})

@app.route('/api/job/<job_id>')
def get_job(job_id):
    """Get specific job details"""
    if job_id in active_jobs:
        job_copy = {k: v for k, v in active_jobs[job_id].items() if k not in ['process', 'timeout_timer']}
        return jsonify(job_copy) # This was the source of the TypeError
    else:
        return jsonify({'error': 'Job not found'}), 404

@app.route('/api/job_by_type/<database>')
def get_job_by_database_type(database):
    """Get most recent job for a database type in current project"""
    current_project = session.get('current_project')
    job = get_job_by_type(database, current_project)
    
    if job:
        job_copy = {k: v for k, v in job.items() if k != 'process'}
        return jsonify(job_copy)
    return jsonify({'error': 'Not found'}), 404

@app.route('/api/results/<database>')
def get_results(database):
    """Get results for a database in current project"""
    current_project = session.get('current_project')
    results = get_step_results(database, current_project)
    return jsonify(results)

@app.route('/api/validate_databases')
def validate_databases():
    """Check if all required BLAST databases are present"""
    databases = {
        'human': config.HUMAN_DB,
        'deg': config.DEG_DB,
        'vfdb': config.VFDB_DB,
        'eskape': config.ESKAPE_DB
    }
    
    validation_results = {}
    all_valid = True
    
    for db_name, db_path in databases.items():
        extensions = ['.phr', '.pin', '.psq']
        exists = all((Path(str(db_path) + ext).exists()) for ext in extensions)
        validation_results[db_name] = exists
        if not exists:
            all_valid = False
    
    return jsonify({
        'all_valid': all_valid,
        'databases': validation_results,
        'database_paths': {k: str(v) for k, v in databases.items()}
    })

@app.route('/api/get_pipeline_stats')
def get_pipeline_stats():
    """Get complete pipeline statistics for current project"""
    try:
        current_project = session.get('current_project', 'default')
        
        stats = {
            'initial_input': 0,
            'total_runtime_seconds': 0,
            'total_runtime': '0s',
            'steps': [],
            'project': current_project
        }
        
        # Get initial input from project-specific combined.faa
        combined_file = BASE_DIR / 'input_sequences' / current_project / 'combined.faa'
        if combined_file.exists():
            try:
                with open(combined_file) as f:
                    stats['initial_input'] = sum(1 for line in f if line.startswith('>'))
            except Exception:
                pass
        
        # Get each step for current project
        databases = ['human', 'deg', 'vfdb', 'eskape']

        # First, check for a completed full pipeline job
        full_job = get_job_by_type('Full Pipeline', current_project)
        if full_job and full_job.get('status') == 'completed' and full_job.get('results'):
            # Use results from the full pipeline job
            for db in databases:
                if db in full_job['results']:
                    res = full_job['results'][db]
                    step_data = {
                        'database': db,
                        'status': 'completed',
                        'runtime': full_job.get('runtime', '0s'),
                        'runtime_seconds': full_job.get('runtime_seconds', 0) / 4,  # Approximate per step
                        'input': res.get('input_sequences', 0),
                        'output': res.get('passing_sequences', 0)
                    }
                    stats['steps'].append(step_data)
                    stats['total_runtime_seconds'] += step_data['runtime_seconds']
        else:
            # Fall back to individual jobs or files
            for db in databases:
                job = get_job_by_type(db, current_project)

                # If no job found, check for existing output files and create a placeholder
                if not job:
                    output_dir = OUTPUT_DIR / current_project
                    passing_file = output_dir / f"{db}_passing.faa"
                    summary_file = output_dir / f"{db}_summary.txt"

                    if passing_file.exists() and summary_file.exists():
                        # Files exist, so the step was likely completed. Create a placeholder job.
                        job = {
                            'database': db,
                            'status': 'completed',
                            'runtime': 'N/A',
                            'runtime_seconds': 0,
                            'results': get_step_results(db, current_project)
                        }
                        # Add a log to indicate this is an inferred step
                        add_job_log('inferred_job', f"Inferred completed step '{db}' from existing output files for project '{current_project}'.", 'info')
                    else:
                        continue  # Skip to next database if no job and no files

                if job and job.get('status') == 'completed':
                    step_data = {
                        'database': db,
                        'status': job['status'],
                        'runtime': job.get('runtime', '0s'),
                        'runtime_seconds': job.get('runtime_seconds', 0)
                    }

                    # Add runtime to total
                    stats['total_runtime_seconds'] += job.get('runtime_seconds', 0)

                    # Get input/output counts
                    if job.get('results'):
                        step_data['input'] = job['results'].get('input_sequences', 0)
                        step_data['output'] = job['results'].get('passing_sequences', 0)

                    stats['steps'].append(step_data)
        
        # Format total runtime
        if stats['total_runtime_seconds'] > 0:
            stats['total_runtime'] = format_time(stats['total_runtime_seconds'])
        
        return jsonify(stats)
        
    except Exception as e:
        print(f"Error getting pipeline stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<filename>')
def download_file(filename):
    """Download file from project directory"""
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'error': 'No project selected'}), 400

    # Sanitize filename to prevent directory traversal
    safe_filename = secure_filename(filename)

    # Construct the absolute path to the project's output directory
    project_output_dir = OUTPUT_DIR / current_proj
    filepath = project_output_dir / safe_filename

    if filepath.is_file():
        # Use send_from_directory with the absolute path of the directory
        return send_from_directory(str(project_output_dir), safe_filename, as_attachment=True)

    return jsonify({'error': 'File not found'}), 404

@app.route('/api/view_file/<filename>', methods=['GET'])
def view_file(filename, directory_type=None):
    """View file content from project directory (for FASTA reader)"""
    # This allows the function to be called internally with a specific directory
    if not directory_type:
        directory_type = request.args.get('type', 'output')

    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'error': 'No project selected'}), 400

    safe_filename = secure_filename(filename)

    # Determine the base directory based on directory_type
    if directory_type == 'validation':
        base_dir_for_file = OUTPUT_DIR / current_proj / 'validation'
    elif directory_type == 'output':
        base_dir_for_file = OUTPUT_DIR / current_proj
    else:
        return jsonify({'success': False, 'error': 'Invalid directory type specified'}), 400

    filepath = base_dir_for_file / safe_filename

    try:
        max_size = 1024 * 1024  # 1MB
        file_size = filepath.stat().st_size
        
        if file_size > max_size:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(max_size)
                content += f"\n\n... (File truncated - showing first 1MB of {file_size / (1024*1024):.1f}MB total)"
        else:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        
        return jsonify({
            'success': True,
            'content': content,
            'filename': safe_filename,
            'size': file_size
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error reading file: {str(e)}'}), 500


AMINO_ACID_COLORS = {
    'R': '#E60606', 'K': '#C64200', 'Q': '#FF6600', 'N': '#FF9900',
    'E': '#FFCC00', 'D': '#FFCC99', 'H': '#FFFF99', 'P': '#FFFF00',
    'Y': '#CCFFCC', 'W': '#CC99FF', 'S': '#CCFF99', 'T': '#00FF99',
    'G': '#00FF00', 'A': '#CCFFFF', 'M': '#99CCFF', 'C': '#00FFFF',
    'F': '#00CCFF', 'L': '#3366FF', 'V': '#0000FF', 'I': '#000080',
    # Default colors for gaps and unknown characters
    '-': '#FFFFFF', # White for gaps
    'X': '#D3D3D3', # Light gray for unknown
    '*': '#D3D3D3', # Light gray for consensus star
    ':': '#D3D3D3', # Light gray for consensus colon
    '.': '#D3D3D3'  # Light gray for consensus dot
}

def get_aa_color(aa):
    """
    Returns the hex color for a given amino acid, with a fallback for unknown characters.
    The text color (black or white) is also returned for contrast.
    """
    color = AMINO_ACID_COLORS.get(aa.upper(), '#D3D3D3') # Default to gray
    # Simple brightness calculation to determine text color
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    brightness = (r * 299 + g * 587 + b * 114) / 1000
    text_color = '#000000' if brightness > 125 else '#FFFFFF'
    return color, text_color

def find_reference_sequence(alignment_data):
    """
    Python port of the frontend reference sequence finder.
    Finds the best reference sequence from an alignment based on length and gap count.
    """
    if not alignment_data:
        return None

    best_candidate = None
    max_ungapped_length = -1
    min_gap_count = float('inf')

    sequences = [seq for seq in alignment_data if not seq.get('is_consensus')]

    for seq_obj in sequences:
        sequence = seq_obj.get('sequence', '')
        ungapped_length = len(sequence.replace('-', ''))
        gap_count = sequence.count('-')

        if ungapped_length > max_ungapped_length or (ungapped_length == max_ungapped_length and gap_count < min_gap_count):
            max_ungapped_length = ungapped_length
            min_gap_count = gap_count
            best_candidate = seq_obj

    return best_candidate['id'] if best_candidate else None

def parse_and_format_aln(file_content):
    """
    Parses a Clustal .aln file and reformats it into a sequential, non-interleaved format.
    """
    from collections import OrderedDict, defaultdict
    sequences = OrderedDict()
    consensus = ""
    max_id_len = 0

    lines = file_content.split('\n')
    for line in lines:
        line = line.rstrip()
        if not line or line.startswith("CLUSTAL") or "multiple sequence alignment" in line:
            continue

        # Handle consensus line (starts with spaces, contains alignment symbols)
        if line.startswith(' ') and ('*' in line or ':' in line or '.' in line):
            # --- FIX: Preserve alignment by finding where the consensus symbols start ---
            # Find the first non-space character to correctly slice the string.
            first_char_index = len(line) - len(line.lstrip(' '))
            consensus_part = line[first_char_index:]
            consensus += consensus_part.rstrip() # Remove trailing whitespace only
            continue

        # Handle sequence lines
        parts = line.split()
        if len(parts) > 0:
            seq_id = parts[0]
            # The sequence part is everything after the ID, or empty if nothing is there
            seq_part = parts[1] if len(parts) > 1 else ""
            
            # Initialize sequence if it's the first time we see it
            if seq_id not in sequences:
                sequences[seq_id] = ""
            
            sequences[seq_id] += seq_part
            if len(seq_id) > max_id_len:
                max_id_len = len(seq_id)
    
    # --- NEW: Build structured alignment data for frontend rendering ---
    alignment_data = []
    for seq_id, seq_string in sequences.items():
        alignment_data.append({
            'id': seq_id,
            'sequence': seq_string
        })
    
    # --- NEW: Calculate and format position-wise counts ---
    position_counts_output = []
    positional_data_for_charts = [] # New data structure for frontend charts
    occupancy_data_for_charts = [] # NEW: For the occupancy chart
    
    # --- NEW: Add consensus line to structured data if it exists ---
    if consensus:
        alignment_data.append({'id': 'Alignment Score', 'sequence': consensus, 'is_consensus': True})

    if sequences:
        position_counts_output.append("\n\n" + "=" * 80)
        position_counts_output.append("Position-wise Amino Acid Counts")
        position_counts_output.append("=" * 80)

        alignment_length = len(next(iter(sequences.values())))
        total_sequences = len(sequences)

        for i in range(alignment_length):
            column_counts = defaultdict(int)
            for seq in sequences.values():
                if i < len(seq):
                    char = seq[i]
                    column_counts[char] += 1

            # --- NEW: Calculate occupancy ---
            non_gap_count = total_sequences - column_counts.get('-', 0)
            occupancy_percentage = (non_gap_count / total_sequences) * 100 if total_sequences > 0 else 0
            occupancy_data_for_charts.append({
                'position': i + 1,
                'percentage': occupancy_percentage
            })
            
            count_str_parts = []
            chart_data_for_position = {'position': i + 1, 'percentages': {}}

            if total_sequences > 0:
                for char, count in sorted(column_counts.items()):
                    percentage = (count / total_sequences) * 100
                    chart_data_for_position['percentages'][char] = percentage

                    if char == '-':
                        continue
                    count_str_parts.append(f"{char}({percentage:.1f}%)")
            
            positional_data_for_charts.append(chart_data_for_position)

            count_str = ", ".join(count_str_parts)
            position_label = f"Position {i+1}:".ljust(15)
            position_counts_output.append(f"{position_label}{count_str}")

    return {
        # Return the parts separately
        "alignment_data": alignment_data,
        "max_id_len": max_id_len,
        "positional_counts_text": "\n".join(position_counts_output),
        "positional_data": positional_data_for_charts,
        "occupancy_data": occupancy_data_for_charts # NEW: Add occupancy data to response
    }

def validate_and_analyze_fasta(file_path):
    """
    Comprehensive FASTA validation checking for 9 common bioinformatics errors.
    Returns a dictionary of found errors and warnings.
    """
    # MODIFICATION: Each error/warning will now be a list of occurrences
    results = {
        'is_valid': True,
        'errors': {}, # e.g., {'duplicate_ids': [{'line': 5, 'content': '>SEQ1'}]}
        'warnings': {},
        'stats': {'sequences': 0, 'max_len': 0}
    }
    
    headers = set()
    has_windows_endings = False
    
    try:
        with open(file_path, 'rb') as f_bytes:
            content_bytes = f_bytes.read()
        
        if b'\r\n' in content_bytes:
            has_windows_endings = True
            results['warnings'].setdefault('windows_endings', []).append({
                'line': None, 'content': 'File uses Windows-style line endings (\\r\\n).', 'fixable': True
            })
        
        content = content_bytes.decode('utf-8', errors='ignore').replace('\r\n', '\n')
        lines = content.split('\n')

        # MODIFICATION: Check for empty lines throughout the file
        first_empty_line = next((i + 1 for i, line in enumerate(lines) if not line.strip() and i < len(lines) - 1 and lines[i+1].strip()), None)
        if first_empty_line:
            results['warnings'].setdefault('empty_lines', []).append({
                'line': first_empty_line, 'content': 'Empty line found.', 'fixable': True
            })
        
        if not content.strip().startswith('>'):
            results['is_valid'] = False
            results['errors'].setdefault('invalid_start', []).append({
                'line': 1, 'content': lines[0] if lines else '', 'fixable': False
            })
            return results

        # MODIFICATION: Find the first instance of wrapping to get a line number.
        first_wrapped_line_num = None
        for i, line in enumerate(lines):
            # A line is part of a wrapped sequence if it's not a header, not empty, and the next line is also not a header and not empty.
            if line.strip() and not line.strip().startswith('>') and (i + 1 < len(lines)) and lines[i+1].strip() and not lines[i+1].strip().startswith('>'):
                first_wrapped_line_num = i + 1
                break
        if first_wrapped_line_num:
            results['warnings'].setdefault('multiline_wrapping', []).append({
                'line': first_wrapped_line_num, 'content': 'This sequence appears to be wrapped across multiple lines.', 'fixable': True
            })

        # Process sequences line-by-line to get accurate line numbers
        current_header = None
        current_sequence = []
        header_line_num = 0

        def process_sequence_block(header, seq_lines, h_line_num):
            if not header: return
            
            sequence_data = "".join(s[0] for s in seq_lines)
            results['stats']['sequences'] += 1

            # 8. Zero-Length Sequences
            if not sequence_data:
                results['warnings'].setdefault('zero_length', []).append({
                    'line': h_line_num, 'content': header, 'fixable': True
                })
                return

            # NEW: Check for short sequences
            if len(sequence_data) < 20:
                results['warnings'].setdefault('short_sequence', []).append({
                    'line': h_line_num, 'content': f'Sequence length is {len(sequence_data)} (less than 20).', 'fixable': True
                })
                return # Don't process other errors for a sequence that will be removed

            # 1. Duplicate IDs
            header_id = header.split()[0]
            if header_id in headers:
                results['is_valid'] = False
                results['errors'].setdefault('duplicate_ids', []).append({
                    'line': h_line_num, 'content': header, 'fixable': True
                })
            headers.add(header_id)

            # 2. Illegal Characters in Header
            # MODIFICATION: Update regex to find characters that need to be replaced.
            if re.search(r'[{}[\]/\\!@#$%^*\'":;]', header_id):
                results['is_valid'] = False
                results['warnings'].setdefault('illegal_chars_header', []).append({
                    'line': h_line_num, 'content': header, 'fixable': True
                })

            # Process sequence lines for line-specific errors
            for seq_content, seq_line_num in seq_lines:
                # 7. Lowercase Sequences
                if any(c.islower() for c in seq_content):
                    results['warnings'].setdefault('lowercase_sequences', []).append({
                        'line': seq_line_num, 'content': seq_content, 'fixable': True
                    })
                # 5. Terminal Stop Codons (check on last line of sequence)
                if seq_line_num == seq_lines[-1][1] and seq_content.endswith('*'):
                    results['warnings'].setdefault('terminal_stop_codon', []).append({
                        'line': seq_line_num, 'content': seq_content, 'fixable': True
                    })
                # 4. Internal Stop Codons
                if '*' in seq_content.rstrip('*'):
                    results['is_valid'] = False
                    results['errors'].setdefault('internal_stop_codon', []).append({
                        'line': seq_line_num, 'content': seq_content, 'fixable': True
                    })
                
                # MODIFICATION: Stricter check for non-standard amino acids
                non_standard_chars = {char for char in seq_content.upper() if char not in STANDARD_AMINO_ACIDS and char != '*'}
                if non_standard_chars:
                    results['warnings'].setdefault('non_standard_aas', []).append({
                        'line': seq_line_num, 
                        'content': f"Found non-standard characters: {', '.join(sorted(list(non_standard_chars)))}", 
                        'fixable': True
                    })


            results['stats']['max_len'] = max(results['stats']['max_len'], len(sequence_data))

        for i, line in enumerate(lines):
            line_num = i + 1
            line_content = line.strip()

            if line_content.startswith('>'):
                # Process the previous sequence block before starting a new one
                process_sequence_block(current_header, current_sequence, header_line_num)
                # Start a new block
                current_header = line_content[1:]
                header_line_num = line_num
                current_sequence = []
            elif current_header and line_content:
                current_sequence.append((line_content, line_num))
            # MODIFICATION: Correctly detect sequence data before the first header.
            elif not current_header and line_content and not line_content.startswith('>'):
                results['is_valid'] = False
                results['errors'].setdefault('no_header_for_sequence', []).append({'line': line_num, 'content': line_content, 'fixable': False})
                continue
        
        # Process the last sequence block in the file
        process_sequence_block(current_header, current_sequence, header_line_num)

    except Exception as e:
        results['is_valid'] = False
        results['errors'].setdefault('read_error', []).append({'line': None, 'content': f'Could not read or parse file: {e}', 'fixable': False})

    return results

@app.route('/api/view_alignment_file', methods=['GET'])
def view_alignment_file():
    """View an alignment file from the project's MSA directory."""
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'error': 'No project selected'}), 400

    protein_name = request.args.get('protein_name')
    # filename = request.args.get('filename') # Ignored to ensure consistency with creation logic

    safe_protein_name = utils.sanitize_protein_name(protein_name)
    
    # Construct the expected filename based on internal naming convention
    # secure_filename strips brackets [] which are allowed in our internal naming
    safe_filename = f"{safe_protein_name}_variants.aln"

    # Construct the path to the alignment file
    filepath = MSA_DIR / current_proj / "clustal" / safe_protein_name / safe_filename

    if not filepath.is_file():
        # --- NEW: Check if the requested name is an alias for another protein ---
        # Search in all passing files to find the alias
        files_to_check = ["eskape_passing.faa", "vfdb_passing.faa", "deg_passing.faa", "human_passing.faa"]
        
        found_canonical = None
        found_match_type = None # 'exact', 'substring'

        for filename in files_to_check:
            check_file = OUTPUT_DIR / current_proj / filename
            if check_file.is_file():
                try:
                    with open(check_file, 'r', encoding='utf-8', errors='ignore') as f:
                        for line in f:
                            if not line.startswith('>'):
                                continue
                            
                            first_space = line.find(' ')
                            if first_space == -1:
                                continue
                            
                            full_description = line[first_space+1:].strip()
                            # Split by '=>' to get all aliases
                            parts = [p.strip() for p in full_description.split('=>')]
                            canonical_name = parts[0]
                            
                            # Clean up the requested protein name for comparison (remove trailing =)
                            clean_protein_name = protein_name.strip().rstrip('=').strip()
                            
                            # Check exact match in aliases
                            if clean_protein_name in parts or protein_name in parts:
                                 if protein_name != canonical_name:
                                     found_canonical = canonical_name
                                     found_match_type = 'exact'
                                     break # Found exact match, stop searching file
                            
                            # Check substring match (fallback)
                            elif (clean_protein_name in full_description or protein_name in full_description) and found_match_type != 'exact':
                                 if protein_name != canonical_name:
                                     found_canonical = canonical_name
                                     found_match_type = 'substring'
                                     # Don't break, keep looking for exact match
                    
                    if found_match_type == 'exact':
                        break # Found exact match, stop searching other files

                except Exception as e:
                    print(f"Error checking for protein aliases in {filename}: {e}")
        
        if found_canonical:
             return jsonify({
                'success': False,
                'error': f"'{protein_name}' is an alternative name (alias). The primary name for this protein is '{found_canonical}'. Please select the primary protein to view its results."
            }), 404
        # --- END NEW LOGIC ---

        # Enhanced error diagnostics to help user understand why file is missing
        variants_file = MSA_DIR / current_proj / "proteins" / f"{safe_protein_name}_variants.faa"
        
        # Case 1: The variants file itself was never created (0 variants found or prep job failed).
        if not variants_file.exists():
            return jsonify({
                'success': False, 
                'error': 'No sequence variants file was found for this protein. The preparation job may have failed or found no variants.\n\nYou can attempt to re-run the alignment, which will first try to re-extract the variants.',
                'can_rerun': True # Allow user to try re-running to fix this.
            }), 404
        
        try:
            with open(variants_file, 'r', encoding='utf-8', errors='ignore') as f:
                seq_count = sum(1 for line in f if line.startswith('>'))
            
            if seq_count <= 1:
                return jsonify({
                    'success': False, 
                    'error': f'Alignment not generated. Only {seq_count} variant found. Alignment requires at least 2 sequences.',
                    'can_rerun': False
                }), 404
            else:
                return jsonify({
                    'success': False, 
                    'error': 'Alignment file missing despite valid input. The alignment job likely failed (e.g., duplicate sequence IDs). Check the "Monitor" tab for specific error logs.',
                    'can_rerun': True
                }), 404
        except Exception:
            return jsonify({'success': False, 'error': 'Alignment file not found.'}), 404

    try:
        max_size = 5 * 1024 * 1024  # 5MB limit for viewing
        file_size = filepath.stat().st_size
        
        if file_size > max_size:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read(max_size)
                content += f"\n\n... (File truncated - showing first 5MB of {file_size / (1024*1024):.1f}MB total)"
        else:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

        # Reformat the content before sending
        parsed_data = parse_and_format_aln(content)

        # --- MODIFICATION: Proactively find the SS *string*, not the image URL ---
        ss_string = None
        try:
            reference_id = find_reference_sequence_from_aln_path(filepath)
            if reference_id:
                # FIX: The ss2 file is in STRUCTURE_DIR, not MSA_DIR.
                # This corrects the path to find and display the secondary structure.
                ss2_file_path = STRUCTURE_DIR / current_proj / "secondary_structure" / f"ss_{safe_protein_name}.ss2"
                if ss2_file_path.is_file():
                    with open(ss2_file_path, 'r') as f:
                        # Parse the .ss2 file to get only the structure string
                        structure_chars = [line.split()[2] for line in f if line.strip() and not line.startswith('#')]
                        ss_string = "".join(structure_chars)
        except Exception as e:
            print(f"Could not find or parse secondary structure file for {protein_name}: {e}")
        # --- END MODIFICATION ---

        return jsonify({
            'success': True,
            'alignment_data': parsed_data['alignment_data'],
            'max_id_len': parsed_data['max_id_len'],
            'positional_data': parsed_data['positional_data'],
            'occupancy_data': parsed_data['occupancy_data'], # NEW: Pass occupancy data
            'positional_counts_text': parsed_data['positional_counts_text'],
            'filename': safe_filename,
            'ss_string': ss_string # Add the structure string to the response
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'Error reading alignment file: {str(e)}'}), 500

@app.route('/api/download_alignment_file', methods=['GET'])
def download_alignment_file():
    """Sends a specific alignment file for download."""
    current_proj = session.get('current_project')
    if not current_proj:
        return "No project selected", 400

    protein_name = request.args.get('protein_name')
    # filename = request.args.get('filename')

    if not protein_name:
        return "Missing protein_name parameter", 400

    # Use the same sanitization logic as the viewer to find the correct directory
    safe_protein_name = utils.sanitize_protein_name(protein_name)
    
    safe_filename = f"{safe_protein_name}_variants.aln"

    # Construct the path to the alignment file's directory
    directory = MSA_DIR / current_proj / "clustal" / safe_protein_name
    filepath = directory / safe_filename

    if not filepath.is_file():
        return "Alignment file not found.", 404

    # Use send_from_directory for security and proper header handling
    return send_from_directory(str(directory), safe_filename, as_attachment=True)

@app.route('/api/system_info')
def system_info():
    """Get system information"""
    import multiprocessing
    
    info = {
        'cpu_count': multiprocessing.cpu_count(),
        'output_dir': str(OUTPUT_DIR),
        'databases': []
    }
    
    # Check databases
    db_dir = BASE_DIR / "db"
    for db_name in ['human', 'deg', 'vfdb', 'eskape']:
        db_path = db_dir / db_name
        if db_path.exists():
            info['databases'].append(db_name)
    
    return jsonify(info)

@app.route('/msa_results/<path:filepath>')
def serve_msa_results(filepath):
    """Serves files from the MSA directory (e.g., psipred images)."""
    # Security enhancement: Ensure the requested path is within MSA_DIR
    msa_dir_abs = MSA_DIR.resolve()
    requested_path = msa_dir_abs.joinpath(filepath).resolve()

    if not requested_path.is_relative_to(msa_dir_abs):
        return "Access denied", 403

    return send_from_directory(str(msa_dir_abs), filepath)

@app.route('/structure_results/<path:filepath>')
def serve_structure_results(filepath):
    """Serves files from the Structure directory."""
    # Security enhancement: Ensure the requested path is within STRUCTURE_DIR
    structure_dir_abs = STRUCTURE_DIR.resolve()
    requested_path = structure_dir_abs.joinpath(filepath).resolve()

    if not requested_path.is_relative_to(structure_dir_abs):
        return "Access denied", 403
        
    return send_from_directory(str(structure_dir_abs), filepath)

    
@app.route('/api/current_project')
def get_current_project():
    """Get current project"""
    project = session.get('current_project')
    return jsonify({'project': project})

@app.route('/api/projects') # Renaming this to /api/projects
def projects_list():
    """List all available projects"""
    projects_dir = BASE_DIR / 'projects'
    projects_dir.mkdir(exist_ok=True)
    
    projects = []
    for project_file in projects_dir.glob('*.json'):
        try:
            with open(project_file) as f:
                project_data = json.load(f)
                projects.append(project_data)
        except Exception as e:
            print(f"Error loading project {project_file}: {e}")
    
    # Sort by created_at descending
    projects.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    
    return jsonify({'projects': projects})

@app.route('/api/set_project', methods=['POST'])
def set_project():
    """Set current project"""
    data = request.json
    project_name = data.get('project')
    
    if project_name:
        session['current_project'] = project_name
        
        # Create project directories if they don't exist
        project_dir = OUTPUT_DIR / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        
        input_dir = BASE_DIR / 'input_sequences' / project_name
        input_dir.mkdir(parents=True, exist_ok=True)
        
        return jsonify({'success': True})
    
    return jsonify({'success': False, 'message': 'No project name provided'})

@app.route('/api/create_project', methods=['POST'])
def create_project():
    """Create a new project"""
    data = request.json
    project_name = data.get('name')
    description = data.get('description', '')
    
    if not project_name:
        return jsonify({'success': False, 'message': 'Project name required'})
    
    # Sanitize project name
    safe_name = "".join(c for c in project_name if c.isalnum() or c in '_- ')
    safe_name = safe_name.strip()
    
    if not safe_name:
        return jsonify({'success': False, 'message': 'Invalid project name'})
    
    # Create project directories
    project_dir = OUTPUT_DIR / safe_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Create input directory for project
    input_dir = BASE_DIR / 'input_sequences' / safe_name
    input_dir.mkdir(parents=True, exist_ok=True)
    
    # Save project metadata
    project_data = {
        'name': safe_name,
        'description': description,
        'created_at': datetime.now().isoformat(),
        'last_updated': datetime.now().isoformat()
    }
    
    projects_dir = BASE_DIR / 'projects'
    projects_dir.mkdir(exist_ok=True)
    
    project_file = projects_dir / f'{safe_name}.json'
    
    # Check if project already exists
    if project_file.exists():
        return jsonify({
            'success': False, 
            'message': f'Project "{safe_name}" already exists'
        })
    
    with open(project_file, 'w') as f:
        json.dump(project_data, f, indent=2)
    
    # Set as current project
    session['current_project'] = safe_name
    
    return jsonify({'success': True, 'project': safe_name})

@app.route('/api/project_info/<project_name>')
def get_project_info(project_name):
    """Get project information including input sequences and step outputs."""
    try:
        project_input_dir = BASE_DIR / 'input_sequences' / project_name
        project_output_dir = OUTPUT_DIR / project_name
        
        info = {
            'success': True,
            'project': project_name,
            'has_input': False,
            'input_sequences': 0,
            'step_outputs': {},
            'eskape_proteins': [], # NEW: Add this to hold the structured protein list
            'mutation_proteins': [], # This is for the selection list
            'alignment_status': {}, # This will hold alignment file status and variant counts
            'pdb_search_status': {} # NEW: To hold cache status for each protein
        }
        
        # 1. Get initial input sequence count from the combined file in the input directory
        combined_file = project_input_dir / 'combined.faa'
        if combined_file.exists():
            with open(combined_file, 'r', encoding='utf-8', errors='ignore') as f:
                info['input_sequences'] = sum(1 for line in f if line.startswith('>'))
                info['has_input'] = info['input_sequences'] > 0
        
        # 2. Get output counts for each completed step from the output directory
        databases = ['human', 'deg', 'vfdb', 'eskape']
        for db in databases:
            passing_file = project_output_dir / f"{db}_passing.faa"
            if passing_file.exists():
                try:
                    with open(passing_file, 'r', encoding='utf-8', errors='ignore') as f:
                        if db == 'eskape':
                            # Use a dict to store unique proteins by canonical name
                            protein_data_map = {}
                            for line in f:
                                if line.startswith('>'):
                                    first_space = line.find(' ')
                                    if first_space != -1:
                                        full_description = line[first_space+1:].strip()
                                        canonical_name = full_description.split('=>')[0].strip()
                                        # Store both canonical and full display name, preventing duplicates
                                        if canonical_name not in protein_data_map:
                                            protein_data_map[canonical_name] = {
                                                'canonical_name': canonical_name,
                                                'display_name': full_description
                                            }
                            info['eskape_proteins'] = list(protein_data_map.values())

                            f.seek(0) # Reset file pointer
                            for prot_data in info['eskape_proteins']:
                                name = prot_data['canonical_name']
                                safe_name = utils.sanitize_protein_name(name)
                                aln_file = MSA_DIR / project_name / "clustal" / safe_name / f"{safe_name}_variants.aln"
                                variant_count = 0
                                variant_file = MSA_DIR / project_name / "proteins" / f"{safe_name}_variants.faa"
                                if variant_file.is_file():
                                    try:
                                        with open(variant_file, 'r', encoding='utf-8', errors='ignore') as vf:
                                            variant_count = sum(1 for line in vf if line.startswith('>'))
                                    except Exception:
                                        pass

                                info['alignment_status'][name] = {'aligned': aln_file.is_file(), 'variant_count': variant_count}
                        count = sum(1 for line in f if line.startswith('>'))
                        info['step_outputs'][db] = count
                except Exception as e:
                    print(f"Could not read passing file for {db} in {project_name}: {e}")

        # 3. Get mutation analysis proteins from the project's metadata file
        project_meta_file = BASE_DIR / 'projects' / f"{project_name}.json"
        if project_meta_file.exists():
            with open(project_meta_file, 'r') as f:
                meta_data = json.load(f)
                # --- MODIFICATION: Read from the 'completed' list for live updates ---
                info['mutation_proteins'] = meta_data.get('completed_mutation_proteins', [])
                # --- FIX: Also read the proteins selected for the next step ---
                info['structure_prediction_proteins'] = meta_data.get('structure_prediction_proteins', [])
                # --- NEW: Read literature search terms ---
                info['literature_terms'] = meta_data.get('literature_terms', [])
                # --- END MODIFICATION ---

        # 3.5 NEW: Check for cached PDB search results for structure prediction proteins
        if 'structure_prediction_proteins' in info:
            for protein_name in info['structure_prediction_proteins']:
                safe_protein_name = utils.sanitize_protein_name(protein_name)
                pdb_results_dir = STRUCTURE_DIR / project_name / "pdb_search"
                cached_json_filepath = pdb_results_dir / f"pdb_matches_{safe_protein_name}.json"
                info['pdb_search_status'][protein_name] = cached_json_filepath.is_file()

        # 4. Get mutational analysis preparation job status
        prep_job = get_job_by_type('mutational_prep', project_name)
        if prep_job and prep_job.get('status') in ['running', 'queued']:
            # Only include relevant fields to avoid sending too much data
            info['mutational_prep_job'] = {
                'status': prep_job.get('status'),
                'progress': prep_job.get('progress'),
                'current_step': prep_job.get('current_step')
            }

        return jsonify(info)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/project_files/<project>')
def get_project_files(project):
    """Get list of input files for a project"""
    from datetime import datetime

    project_dir = BASE_DIR / 'input_sequences' / project
    
    if not os.path.exists(project_dir):
        return jsonify({
            'success': False,
            'files': [],
            'message': 'Project directory not found'
        })
    
    files = []
    try:
        for filepath_obj in project_dir.iterdir():
            filename = filepath_obj.name
            # Skip combined file and non-FASTA files
            if filename == 'combined.faa':
                continue
            if not filename.endswith(('.faa', '.fasta', '.fa')):
                continue
            
            stat = filepath_obj.stat()
            
            # Count sequences in file
            try:
                with open(filepath_obj, 'r') as f:
                    seq_count = f.read().count('>')
            except:
                seq_count = 0
            
            files.append({
                'name': filename,
                'size': stat.st_size,
                'sequences': seq_count,
                'modified': datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')
            })
        
        # Sort by name
        files.sort(key=lambda x: x['name'])
        
    except Exception as e:
        return jsonify({
            'success': False,
            'files': [],
            'message': str(e)
        })
    
    return jsonify({
        'success': True,
        'files': files,
        'project': project,
        'count': len(files)
    })

@app.route('/api/cleanup_job/<job_id>', methods=['POST'])
def cleanup_job(job_id):
    """Cleanup and remove a failed/stuck job"""
    try:
        if job_id in active_jobs:
            job = active_jobs[job_id]
            
            # Kill process if running
            if 'process' in job and job['process']:
                try:
                    if hasattr(job['process'], 'pid'):
                        os.killpg(os.getpgid(job['process'].pid), signal.SIGTERM)
                    else:
                        job['process'].terminate()
                except Exception as e:
                    print(f"Error killing process: {e}")
            
            # Cancel timeout timer
            if 'timeout_timer' in job:
                try:
                    job['timeout_timer'].cancel()
                except:
                    pass
            
            # Update status
            update_job(job_id, {
                'status': 'cancelled',
                'ended_at': datetime.now().isoformat(),
                'current_step': 'Cleaned up by user'
            })
            
            return jsonify({'success': True, 'message': 'Job cleaned up'})
        
        return jsonify({'success': False, 'message': 'Job not found'}), 404
        
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/recover_jobs', methods=['POST'])
def recover_stuck_jobs():
    """Recover jobs that are stuck in running state"""
    recovered = []
    for job_id, job in list(active_jobs.items()):
        if job['status'] == 'running':
            if 'process' in job and job['process']:
                if job['process'].poll() is not None:
                    # Process finished but status not updated
                    update_job(job_id, {
                        'status': 'failed',
                        'ended_at': datetime.now().isoformat(),
                        'current_step': 'Process ended unexpectedly'
                    })
                    recovered.append(job_id)
    
    return jsonify({
        'success': True,
        'recovered': len(recovered),
        'job_ids': recovered
    })

@app.route('/api/upload_files', methods=['POST'])
def upload_files():
    """Upload files to project-specific directory"""
    try:
        if 'files' not in request.files:
            return jsonify({'success': False, 'message': 'No files uploaded'})

        files = request.files.getlist('files')
        project = request.form.get('project')

        if not project:
            project = session.get('current_project')

        if not project:
            return jsonify({'success': False, 'message': 'No project specified'})

        # Get project paths
        project_input_dir = BASE_DIR / 'input_sequences' / project
        project_output_dir = OUTPUT_DIR / project
        project_input_dir.mkdir(parents=True, exist_ok=True)
        project_output_dir.mkdir(parents=True, exist_ok=True)

        total_sequences = 0
        uploaded_files_info = []

        # Define file paths for combined files
        input_combined_path = project_input_dir / 'combined.faa'
        output_combined_path = project_output_dir / 'combined.faa'

        # Open both combined files for writing
        with open(input_combined_path, 'w') as input_outfile, open(output_combined_path, 'w') as output_outfile:
            for file in files:
                if file and file.filename and allowed_file(file.filename):
                    filename = secure_filename(file.filename)
                    filepath = project_input_dir / filename

                    # Save the individual file
                    file.save(filepath)

                    # After saving the file, add validation:
                    valid, message = validate_fasta_content(filepath)
                    if not valid:
                        os.remove(filepath)  # Delete invalid file
                        return jsonify({
                            'success': False,
                            'message': f'Invalid FASTA file ({filename}): {message}'
                        }), 400

                    # Stream the saved file's content to both combined files
                    # and count sequences at the same time
                    file_seq_count = 0
                    with open(filepath, 'r') as infile:
                        for line in infile:
                            if line.startswith('>'):
                                file_seq_count += 1
                            input_outfile.write(line)
                            output_outfile.write(line)

                    # Ensure a newline at the end
                    input_outfile.write('\n')
                    output_outfile.write('\n')

                    total_sequences += file_seq_count
                    uploaded_files_info.append(filename)

        return jsonify({
            'success': True,
            'total_sequences': total_sequences,
            'files': uploaded_files_info,
            'project': project
        })

    except Exception as e:
        print(f"Error uploading files: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'message': str(e)})

@app.route('/api/get_initial_sequences')
def get_initial_sequences():
    """Get initial input sequence count for current project"""
    try:
        current_project = session.get('current_project')
        if not current_project:
            return jsonify({'count': None})
        
        # Try project-specific combined file
        combined_file = BASE_DIR / 'input_sequences' / current_project / 'combined.faa'
        
        if combined_file.exists():
            with open(combined_file) as f:
                count = sum(1 for line in f if line.startswith('>'))
            return jsonify({'count': count})
            
    except Exception as e:
        print(f"Error getting initial sequences: {e}")
    
    return jsonify({'count': None})

@app.route('/api/end_job/<job_id>', methods=['POST'])
def end_job(job_id):
    """End a running job"""
    try:
        job = active_jobs.get(job_id)
        
        if not job:
            return jsonify({'success': False, 'message': 'Job not found'})
        
        if job['status'] not in ['running', 'queued']:
            return jsonify({
                'success': False, 
                'message': f'Job is not running (status: {job["status"]})'
            })
        
        # Kill the process if it exists
        terminated = False
        
        if 'process' in job and job['process']:
            try:
                proc = job['process']
                
                # Get process ID
                if hasattr(proc, 'pid'):
                    pid = proc.pid
                    
                    # Try graceful termination
                    try:
                        os.kill(pid, signal.SIGTERM)
                        proc.wait(timeout=3)
                        terminated = True
                    except subprocess.TimeoutExpired:
                        # Force kill if still running
                        try:
                            os.kill(pid, signal.SIGKILL)
                            proc.wait(timeout=1)
                            terminated = True
                        except:
                            pass
                    except ProcessLookupError:
                        # Process already dead
                        terminated = True
                    except Exception as e:
                        print(f"Error terminating with signal: {e}")
                else:
                    # Fallback to process methods
                    proc.terminate()
                    try:
                        proc.wait(timeout=3)
                        terminated = True
                    except:
                        proc.kill()
                        terminated = True
                        
            except Exception as e:
                print(f"Error terminating process: {e}")
                import traceback
                traceback.print_exc()
        
        # Update job status
        update_job(job_id, {
            'status': 'failed',
            'progress': 0,
            'current_step': 'Job manually stopped by user',
            'ended_at': datetime.now().isoformat()
        })
        
        return jsonify({
            'success': True, 
            'message': 'Job stopped successfully',
            'terminated': terminated
        })
        
    except Exception as e:
        print(f"Error in end_job: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False, 
            'message': f'Error stopping job: {str(e)}'
        })

@app.route('/api/save_mutation_selection', methods=['POST'])
def save_mutation_selection():
    """
    Saves the list of proteins selected for mutational analysis to the project's
    metadata file.
    """
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    data = request.get_json()
    proteins = data.get('proteins')

    if proteins is None:
        return jsonify({'success': False, 'message': 'Missing proteins data'}), 400

    # Save selection to project metadata
    project_meta_file = BASE_DIR / 'projects' / f"{current_proj}.json"
    if not project_meta_file.exists():
        return jsonify({'success': False, 'message': 'Project metadata file not found'}), 404
    with open(project_meta_file, 'r+') as f:
        meta_data = json.load(f)
        meta_data['mutation_proteins'] = proteins
        meta_data['last_updated'] = datetime.now().isoformat()
        f.seek(0)
        json.dump(meta_data, f, indent=2)
        f.truncate()

    # This endpoint now only saves the metadata. The preparation is done in the new endpoint.
    return jsonify({'success': True, 'message': 'Selection saved.'})

@app.route('/api/prepare_mutational_analysis', methods=['POST'])
def prepare_mutational_analysis():
    """
    Creates a master job to run MSA and SS-pred for all selected proteins.
    """
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    data = request.get_json()
    proteins = data.get('proteins')
    if not proteins:
        return jsonify({'success': False, 'message': 'No proteins provided'}), 400

    # --- MODIFICATION: Save the selection to the project metadata first ---
    project_meta_file = BASE_DIR / 'projects' / f"{current_proj}.json"
    if not project_meta_file.exists():
        return jsonify({'success': False, 'message': 'Project metadata file not found'}), 404
    with open(project_meta_file, 'r+') as f:
        meta_data = json.load(f)
        meta_data['mutation_proteins'] = proteins
        meta_data['last_updated'] = datetime.now().isoformat()
        f.seek(0)
        json.dump(meta_data, f, indent=2)
        f.truncate()

    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    data = request.get_json()
    proteins = data.get('proteins')
    if not proteins:
        return jsonify({'success': False, 'message': 'No proteins provided'}), 400

    job_id = f"mut_prep_{current_proj}_{int(time.time())}"
    job_type = "mutational_prep"
    job_config = {'proteins': [p.get('display_name', p.get('name')) for p in proteins]}
    create_job(job_id, job_type, job_config)

    thread = threading.Thread(target=prepare_mutational_analysis_thread, args=(job_id, proteins, current_proj))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'job_id': job_id, 'message': 'Started mutational analysis preparation job.'})

@app.route('/api/download_selected_sequences', methods=['POST'])
def download_selected_sequences():
    """
    Filters a FASTA file based on a list of protein names and returns it for download.
    """
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    try:
        data = request.get_json()
        database = data.get('database')
        protein_names = data.get('protein_names')
        names_only = data.get('names_only', False)
        source_file = data.get('source_file') # New parameter

        if not database or not protein_names:
            return jsonify({'success': False, 'message': 'Missing database or protein names'}), 400

        # Sanitize filename and construct path
        safe_filename = secure_filename(f"{database}_passing.faa")
        project_output_dir = OUTPUT_DIR / current_proj
        source_filepath = project_output_dir / safe_filename

        if not source_filepath.is_file():
            return jsonify({'success': False, 'message': 'Source FASTA file not found'}), 404

        # --- NEW LOGIC: Handle specific source file requests differently ---
        if source_file:
            # 1. Get all sequence IDs that passed the filter stage
            with open(source_filepath, 'r') as f:
                passing_seq_ids = {line.strip()[1:].split()[0] for line in f if line.startswith('>')}

            # 2. Get the path to the original user-uploaded file
            original_input_path = BASE_DIR / 'input_sequences' / current_proj / secure_filename(source_file)
            if not original_input_path.is_file():
                return jsonify({'success': False, 'message': f'Original input file {source_file} not found.'}), 404

            # 3. Extract sequences from the original file that are in the passing set and match the protein name
            selected_names_set = set(protein_names)
            output_lines = []
            with open(original_input_path, 'r') as f:
                current_sequence_block = []
                keep_sequence = False
                for line in f:
                    if line.startswith('>'):
                        # Process the previous block
                        if keep_sequence:
                            if names_only:
                                output_lines.append(current_sequence_block[0].strip())
                            else:
                                output_lines.extend(current_sequence_block)

                        # Start a new block
                        current_sequence_block = [line]
                        header_id = line.strip()[1:].split()[0]
                        first_space_index = line.find(' ')
                        protein_name = line[first_space_index + 1:].strip() if first_space_index != -1 else ""
                        
                        # Check if this new block should be kept
                        keep_sequence = (header_id in passing_seq_ids) and (protein_name in selected_names_set)
                    
                    elif keep_sequence:
                        current_sequence_block.append(line)

                # Process the very last block in the file
                if keep_sequence:
                    if names_only:
                        output_lines.append(current_sequence_block[0].strip())
                    else:
                        output_lines.extend(current_sequence_block)
            
            content = "\n".join(output_lines) if names_only else "".join(output_lines)
            content_type = 'text/plain; charset=utf-8' if names_only else 'application/octet-stream'
            return content, 200, {'Content-Type': content_type}

        # --- Original logic for "all files" download ---
        # Use a set for efficient lookup
        selected_names_set = set(protein_names)
        output_lines = []
        
        with open(source_filepath, 'r') as f:
            current_sequence_lines = []
            header = None
            keep_sequence = False

            for line in f:
                if line.startswith('>'):
                    # Process the previous sequence block
                    if header and keep_sequence and not names_only:
                        output_lines.append(header)
                        output_lines.extend(current_sequence_lines)
                    # If only names (headers) are requested, just add the header
                    elif header and keep_sequence and names_only:
                        output_lines.append(header.strip())

                    # Start a new sequence block
                    header = line
                    current_sequence_lines = []
                    
                    # Check if this new sequence should be kept
                    first_space_index = line.find(' ')
                    protein_name = line[first_space_index + 1:].strip() if first_space_index != -1 else ""
                    
                    # Condition 1: The protein name must be in the selected list
                    keep_sequence = protein_name in selected_names_set
                else:
                    # Only collect sequence lines if we are not in names_only mode
                    if not names_only:
                        current_sequence_lines.append(line) # This was the last line of the original code block
            
            # Process the very last sequence in the file
            if header and keep_sequence:
                if names_only:
                    output_lines.append(header.strip())
                else:
                    output_lines.extend([header] + current_sequence_lines)

        # Join the collected lines and determine the content type
        if names_only:
            content = "\n".join(output_lines)
            content_type = 'text/plain; charset=utf-8'
        else:
            content = "".join(output_lines)
            content_type = 'application/octet-stream'

        return content, 200, {'Content-Type': content_type}

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/classify_protein', methods=['POST'])
def classify_protein():
    """
    Saves a protein's drug target classification to the project's metadata file.
    """
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    data = request.get_json()
    protein_name = data.get('protein_name')
    classification = data.get('classification') # 'strong', 'medium', 'remove', or None to clear

    if not protein_name:
        return jsonify({'success': False, 'message': 'Missing protein_name'}), 400

    project_meta_file = BASE_DIR / 'projects' / f"{current_proj}.json"
    if not project_meta_file.exists():
        return jsonify({'success': False, 'message': 'Project metadata file not found'}), 404

    with open(project_meta_file, 'r+') as f:
        meta_data = json.load(f)
        
        # Find the protein in the list of completed proteins
        protein_found = False
        if 'completed_mutation_proteins' in meta_data:
            for protein in meta_data['completed_mutation_proteins']:
                if protein.get('name') == protein_name:
                    protein['classification'] = classification
                    protein_found = True
                    break
        
        if not protein_found:
            return jsonify({'success': False, 'message': f'Protein "{protein_name}" not found in project metadata.'}), 404

        # Write the updated data back to the file
        f.seek(0)
        json.dump(meta_data, f, indent=2)
        f.truncate()

    return jsonify({'success': True, 'message': f'Classification for {protein_name} saved.'})

@app.route('/api/save_structure_selection', methods=['POST'])
def save_structure_selection():
    """
    Saves the final list of proteins selected for structure prediction.
    """
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    data = request.get_json()
    protein_names = data.get('protein_names')

    if protein_names is None:
        return jsonify({'success': False, 'message': 'Missing protein_names data'}), 400

    project_meta_file = BASE_DIR / 'projects' / f"{current_proj}.json"
    if not project_meta_file.exists():
        return jsonify({'success': False, 'message': 'Project metadata file not found'}), 404

    with open(project_meta_file, 'r+') as f:
        meta_data = json.load(f)
        # Save the list of names under a new key
        meta_data['structure_prediction_proteins'] = protein_names
        meta_data['last_updated'] = datetime.now().isoformat()
        f.seek(0)
        json.dump(meta_data, f, indent=2)
        f.truncate()

    return jsonify({'success': True, 'message': 'Structure prediction selection saved.'})

@app.route('/api/get_reference_sequence/<path:protein_name>', methods=['GET'])
def get_reference_sequence(protein_name):
    """
    Finds and returns the reference sequence for a given protein.
    """
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    if not protein_name:
        return jsonify({'success': False, 'message': 'No protein name provided'}), 400

    # Sanitize the protein name to find the correct file
    safe_protein_name = utils.sanitize_protein_name(protein_name)
    
    # Construct the path to the reference FASTA file
    ref_fasta_path = MSA_DIR / current_proj / "reference" / f"reference_{safe_protein_name}.faa"

    if not ref_fasta_path.is_file():
        return jsonify({'success': False, 'message': f'Reference sequence file not found for "{protein_name}". Please ensure mutational analysis preparation is complete.'}), 404

    try:
        with open(ref_fasta_path, 'r') as f:
            lines = f.readlines()
            # Find the first line that is not a header
            sequence = ""
            for line in lines:
                if not line.startswith('>'):
                    sequence += line.strip()
            
            if not sequence:
                return jsonify({'success': False, 'message': 'No sequence data found in the reference file.'}), 500

        return jsonify({'success': True, 'sequence': sequence})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Error reading reference file: {str(e)}'}), 500

@app.route('/api/uniprot_blast', methods=['POST'])
def uniprot_blast_proxy():
    """
    Acts as a server-side proxy for the UniProt BLAST API.
    Takes a sequence, submits it, polls for results, and returns the filtered matches.
    """
    import requests
    import time

    data = request.get_json()
    sequence = data.get('sequence')
    identity_threshold = data.get('identity_threshold', 0.9)

    if not sequence:
        return jsonify({'success': False, 'message': 'No sequence provided'}), 400

    # --- 1. Submit BLAST Job ---
    blast_api_url = "https://rest.uniprot.org/uniprotkb/blast"
    blast_payload = {
        "sequence": sequence,
        "database": "uniprotkb_refprotswissprot",
        "program": "blastp",
    }
    try:
        # This endpoint expects urlencoded data
        submit_response = requests.post(blast_api_url, data=blast_payload)
        submit_response.raise_for_status()
        job_id = submit_response.json().get("jobId")
        if not job_id:
            return jsonify({'success': False, 'message': 'UniProt API did not return a Job ID.'}), 502
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'message': f'UniProt BLAST submission failed: {e}'}), 502

    # --- 2. Poll for Status ---
    status_url = f"https://rest.uniprot.org/blast/status/{job_id}"
    while True:
        try:
            status_response = requests.get(status_url)
            status_response.raise_for_status()
            status = status_response.json().get("jobStatus")

            if status == "FINISHED":
                break
            elif status in ["ERROR", "FAILURE", "NOT_FOUND"]:
                return jsonify({'success': False, 'message': f'UniProt job failed with status: {status}'}), 502
            
            time.sleep(5) # Wait 5 seconds before polling again

        except requests.exceptions.RequestException as e:
            return jsonify({'success': False, 'message': f'UniProt status check failed: {e}'}), 502

    # --- 3. Get and Filter Results ---
    results_url = f"https://rest.uniprot.org/blast/results/{job_id}"
    try:
        results_response = requests.get(results_url)
        results_response.raise_for_status()
        results = results_response.json().get("results", [])

        matches = []
        for hit in results:
            identity = float(hit.get("identity", 0)) / 100
            if identity >= identity_threshold:
                matches.append({
                    "uniprot_id": hit.get("from"),
                    "identity": identity,
                    "protein_name": hit.get("proteinName"),
                    "organism": hit.get("organism", {}).get("scientificName"),
                    "sequence_length": hit.get("sequenceLength")
                })
        
        return jsonify({'success': True, 'matches': matches})
    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'message': f'UniProt results retrieval failed: {e}'}), 502

@app.route('/api/pdb_blast', methods=['POST'])
def pdb_blast_proxy():
    """
    Acts as a server-side proxy for the RCSB PDB sequence search API.
    """
    import requests
    data = request.get_json()
    protein_name = data.get('protein_name')
    sequence = data.get('sequence')
    
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400
    if not protein_name:
        return jsonify({'success': False, 'message': 'No protein name provided'}), 400
    if not sequence:
        return jsonify({'success': False, 'message': 'No sequence provided'}), 400
    
    # --- FIX: Sanitize the sequence to remove non-standard characters ---
    import re
    original_len = len(sequence)
    sanitized_sequence = re.sub(r'[^A-Z]', '', sequence.upper())
    if len(sanitized_sequence) < original_len:
        print(f"Warning: Sanitized sequence for PDB search. Original length: {original_len}, New length: {len(sanitized_sequence)}")
    # --- NEW: Check for cached results first ---
    safe_protein_name = utils.sanitize_protein_name(protein_name)
    pdb_results_dir = STRUCTURE_DIR / current_proj / "pdb_search"
    cached_json_filepath = pdb_results_dir / f"pdb_matches_{safe_protein_name}.json"

    if cached_json_filepath.is_file():
        try:
            with open(cached_json_filepath, 'r') as f:
                cached_matches = json.load(f)
            # If file exists and is readable, return its content immediately.
            print(f"Serving PDB search results for '{protein_name}' from cache.")
            return jsonify({'success': True, 'matches': cached_matches})
        except Exception as e:
            # If reading the cache fails, proceed to fetch from the API.
            print(f"Warning: Could not read cached PDB results file, will re-fetch. Error: {e}")
    
    try:
        pdb_api_url = "https://search.rcsb.org/rcsbsearch/v2/query"
        
        # Updated query based on the recommended robust structure
        query = {
            "query": {
                "type": "terminal",
                "service": "sequence",
                "parameters": {
                    "evalue_cutoff": 1,
                    "identity_cutoff": 0.9,
                    "sequence_type": "protein",
                    "value": sanitized_sequence
                }
            },
            "request_options": {
                "scoring_strategy": "sequence",
                "results_content_type": [
                    "experimental"
                ],
                "sort": [{"sort_by": "score", "direction": "desc"}],
                "paginate": {"start": 0, "rows": 25}
            },
            "return_type": "polymer_entity"
        }
        
        try:
            response = requests.post(pdb_api_url, json=query)
            # This will raise an HTTPError for bad responses (4xx or 5xx)
            response.raise_for_status()
            # This will raise a JSONDecodeError if the response is not valid JSON
            results = response.json()

            # Extract just the PDB IDs and scores from the results
            matches = []
            for item in results.get("result_set", []):
                # FIX: Handle identifiers that may not have an underscore (e.g., just "1ABC")
                identifier = item["identifier"]
                pdb_id = identifier.split("_")[0]
                matches.append({
                    "pdb_id": pdb_id,
                    "score": item.get("score", 0),
                    "title": item.get("struct", {}).get("title", "N/A"),
                    "organism": item.get("rcsb_entity_source_organism", [{}])[0].get("ncbi_scientific_name", "N/A"),
                    "resolution": item.get("rcsb_entry_info", {}).get("resolution_combined", [None])[0]
                })
            
            # --- MODIFICATION: Augment matches with detailed metadata for the UI ---
            if matches:
                try:
                    # Import here to avoid startup crash if RCSB schema fetch fails
                    from rcsbapi.data import DataQuery as Query

                    pdb_ids_to_fetch = [match['pdb_id'] for match in matches]
                    all_detailed_entries = []
                    
                    # --- FIX: Query PDB API in chunks to prevent timeouts/errors ---
                    chunk_size = 50
                    for i in range(0, len(pdb_ids_to_fetch), chunk_size):
                        chunk = pdb_ids_to_fetch[i:i + chunk_size]
                        detail_query = Query(
                            input_type="entries", input_ids=chunk,
                            return_data_list=[
                                "entries.rcsb_id", "struct.title", "struct_keywords.pdbx_keywords",
                                "rcsb_accession_info.initial_release_date", "rcsb_entry_info.resolution_combined",
                                "exptl.method", "polymer_entities.rcsb_entity_source_organism.ncbi_scientific_name",
                                "polymer_entities.rcsb_entity_host_organism.ncbi_scientific_name",
                                "polymer_entities.rcsb_polymer_entity_feature_summary.type",
                                "polymer_entities.rcsb_polymer_entity_feature_summary.count",
                            ]
                        )
                        detailed_results = detail_query.exec()
                        if detailed_results and "data" in detailed_results and "entries" in detailed_results["data"]:
                            all_detailed_entries.extend(detailed_results["data"]["entries"])
                    
                    # Create a lookup map for the detailed results
                    detailed_data_map = {entry['rcsb_id']: entry for entry in all_detailed_entries if entry and 'rcsb_id' in entry}

                except Exception as e:
                    print(f"Warning: Could not fetch detailed PDB metadata for UI: {e}")
                    detailed_data_map = {} # Ensure it exists even on failure

                # --- FIX: Iterate over the original matches to ensure all are processed ---
                for match in matches:
                    entry = detailed_data_map.get(match['pdb_id'])
                    if not entry:
                        # If no detailed data, just continue with the basic info we already have.
                        continue

                    # --- Augment the match object with detailed data ---
                    pe_list_ui = entry.get("polymer_entities") or []
                    host_orgs_ui, source_orgs_ui, has_mutation_ui = set(), set(), False
                    for pe in pe_list_ui:
                        for host in pe.get("rcsb_entity_host_organism") or []:
                            if hname := host.get("ncbi_scientific_name"): host_orgs_ui.add(hname)
                        for src in pe.get("rcsb_entity_source_organism") or []:
                            if name := src.get("ncbi_scientific_name"): source_orgs_ui.add(name)
                        for feat in pe.get("rcsb_polymer_entity_feature_summary") or []:
                            if feat.get("type") == "mutation" and (feat.get("count") or 0) > 0: has_mutation_ui = True
                    
                    # Overwrite initial data with more reliable detailed data
                    match['title'] = (entry.get("struct") or {}).get("title", "N/A")
                    match['organism'] = "; ".join(sorted(source_orgs_ui)) if source_orgs_ui else "N/A"
                    match['resolution'] = (entry.get("rcsb_entry_info") or {}).get("resolution_combined", [None])[0]
                    match['classification'] = (entry.get("struct_keywords") or {}).get("pdbx_keywords")
                    match['mutations'] = "Yes" if has_mutation_ui else "No"
                    match['expression_system'] = "; ".join(sorted(host_orgs_ui)) if host_orgs_ui else "N/A"
                    match['released'] = (entry.get("rcsb_accession_info") or {}).get("initial_release_date", "N/A")[:10]
                    match['method'] = "; ".join(sorted({e.get("method") for e in (entry.get("exptl") or []) if e.get("method")})) or "N/A"

                # --- NEW: Integration of detailed metadata fetching script ---
                if matches:
                    try:
                        pdb_ids_to_fetch = [match['pdb_id'] for match in matches]

                        # Flatten the JSON into table rows
                        rows = []
                        for match in matches:
                            entry = detailed_data_map.get(match['pdb_id'])
                            if not entry: continue # Skip if no detailed entry for this match

                            pe_list = entry.get("polymer_entities") or []
                            source_orgs, host_orgs, has_mutation = set(), set(), False
                            for pe in pe_list:
                                for src in pe.get("rcsb_entity_source_organism") or []:
                                    if name := src.get("ncbi_scientific_name"): source_orgs.add(name)
                                for host in pe.get("rcsb_entity_host_organism") or []:
                                    if hname := host.get("ncbi_scientific_name"): host_orgs.add(hname)
                                for feat in pe.get("rcsb_polymer_entity_feature_summary") or []:
                                    if feat.get("type") == "mutation" and (feat.get("count") or 0) > 0: has_mutation = True

                            rows.append({
                                "PDB_ID": entry.get("rcsb_id"),
                                "Title": (entry.get("struct") or {}).get("title"),
                                "Classification": (entry.get("struct_keywords") or {}).get("pdbx_keywords"),
                                "Organisms": "; ".join(sorted(source_orgs)) if source_orgs else None,
                                "Expression_System": "; ".join(sorted(host_orgs)) if host_orgs else None,
                                "Mutations": "Yes" if has_mutation else "No",
                                "Released": (entry.get("rcsb_accession_info") or {}).get("initial_release_date"),
                                "Method": "; ".join(sorted({e.get("method") for e in (entry.get("exptl") or []) if e.get("method")})) or None,
                                "Resolution_Angstrom": (entry.get("rcsb_entry_info") or {}).get("resolution_combined", [None])[0],
                            })

                        # Write the detailed results to a CSV file
                        safe_protein_name = utils.sanitize_protein_name(protein_name)
                        pdb_results_dir = STRUCTURE_DIR / current_proj / "pdb_search"
                        pdb_results_dir.mkdir(parents=True, exist_ok=True)
                        csv_filepath = pdb_results_dir / f"pdb_metadata_{safe_protein_name}.csv"
                        
                        fieldnames = ["PDB_ID", "Title", "Classification", "Organisms", "Expression_System", "Mutations", "Released", "Method", "Resolution_Angstrom"]
                        with open(csv_filepath, "w", newline="", encoding="utf-8") as fh:
                            writer = csv.DictWriter(fh, fieldnames=fieldnames)
                            writer.writeheader()
                            writer.writerows(rows)

                    except Exception as e:
                        print(f"Warning: Could not fetch or save detailed PDB metadata: {e}")

            # Save the results to a JSON file
            try:
                safe_protein_name = utils.sanitize_protein_name(protein_name)
                pdb_results_dir = STRUCTURE_DIR / current_proj / "pdb_search"
                pdb_results_dir.mkdir(parents=True, exist_ok=True)
                
                output_filepath = pdb_results_dir / f"pdb_matches_{safe_protein_name}.json"
                
                with open(output_filepath, 'w') as f:
                    json.dump(matches, f, indent=2)

            except Exception as e:
                print(f"Warning: Could not save PDB search results to file: {e}")

            return jsonify({'success': True, 'matches': matches})
        except requests.exceptions.JSONDecodeError:
            # This catches cases where the PDB API returns non-JSON (e.g., an HTML error page)
            return jsonify({'success': False, 'message': 'PDB search failed: The PDB API returned an invalid response. This may be due to an invalid sequence.'}), 502
        except requests.exceptions.RequestException as e:  # Catches other network-related errors
            return jsonify({'success': False, 'message': f'PDB search failed: {e}'}), 502
    except Exception as e:
        # Catch any other unexpected errors from the outer try block
        return jsonify({'success': False, 'message': f'An unexpected error occurred: {str(e)}'}), 500

@app.route('/api/validate_input_files', methods=['POST'])
def validate_input_files():
    """
    Validates uploaded FASTA files without saving them.
    Checks for format, sequence length, and invalid characters.
    """
    if 'files' not in request.files:
        return jsonify({'success': False, 'message': 'No files provided for validation'}), 400

    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    files = request.files.getlist('files')
    validation_results = []
    all_valid = True

    # Create a unique temporary directory for this validation session
    validation_session_id = f"{current_proj}_{int(time.time())}"
    temp_dir = VALIDATION_TEMP_DIR / validation_session_id
    temp_dir.mkdir(exist_ok=True)

    for file in files:
        if not (file and file.filename and allowed_file(file.filename)):
            validation_results.append({
                'filename': file.filename or 'unnamed file',
                'analysis': {
                    'is_valid': False,
                    'errors': {'invalid_type': [{'line': None, 'content': 'Invalid file type. Only .faa, .fasta, .fa are allowed.', 'fixable': False}]},
                    'warnings': [],
                    'stats': {}
                }
            })
            all_valid = False
            continue

        try:
            temp_path = temp_dir / secure_filename(file.filename)
            file.save(temp_path)

            analysis = validate_and_analyze_fasta(temp_path)
            validation_results.append({
                'filename': file.filename,
                'analysis': analysis
            })
            if not analysis['is_valid']:
                all_valid = False

        except Exception as e:
            all_valid = False
            validation_results.append({
                'filename': file.filename,
                'analysis': {
                    'is_valid': False,
                    'errors': {'server_error': [{'line': None, 'content': f'Server error during validation: {e}', 'fixable': False}]},
                    'warnings': [],
                    'stats': {}
                }
            })

    return jsonify({
        'success': True,
        'all_valid': all_valid,
        'results': validation_results,
        'validation_session_id': validation_session_id
    })

@app.route('/api/fix_and_upload_files', methods=['POST'])
def fix_and_upload_files():
    """
    Applies selected fixes to files from a validation session and completes the upload.
    """
    data = request.get_json()
    session_id = data.get('validation_session_id')
    fixes_to_apply = data.get('fixes') # e.g., {'my_file.faa': ['duplicate_ids', 'lowercase_sequences']}

    if not session_id or not fixes_to_apply:
        return jsonify({'success': False, 'message': 'Missing session ID or fix instructions'}), 400

    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    temp_dir = VALIDATION_TEMP_DIR / session_id
    if not temp_dir.is_dir():
        return jsonify({'success': False, 'message': 'Validation session expired or not found'}), 404

    project_input_dir = BASE_DIR / 'input_sequences' / current_proj
    project_input_dir.mkdir(parents=True, exist_ok=True)

    try:
        for filename, active_fixes in fixes_to_apply.items():
            original_path = temp_dir / secure_filename(filename)
            target_path = project_input_dir / secure_filename(filename)

            if not original_path.exists():
                continue

            with open(original_path, 'r', encoding='utf-8', errors='ignore') as f_in:
                content = f_in.read()

            # Apply fixes sequentially
            if 'windows_endings' in active_fixes:
                content = content.replace('\r\n', '\n')

            # NEW: Fix for empty lines
            if 'empty_lines' in active_fixes:
                content = "\n".join(line for line in content.split('\n') if line.strip() or line == '')
            
            # Unwrapper should run first
            if 'multiline_wrapping' in active_fixes:
                sequences = content.split('>')
                unwrapped_content = []
                for seq_block in sequences:
                    if not seq_block.strip(): continue
                    parts = seq_block.split('\n', 1)
                    header = parts[0]
                    seq_data = parts[1].replace('\n', '') if len(parts) > 1 else ''
                    unwrapped_content.append(f">{header}\n{seq_data}")
                content = "\n".join(unwrapped_content)

            # Process line-by-line fixes
            fixed_lines = []
            seen_ids = set()
            for line in content.split('\n'):
                if line.startswith('>'):
                    header_id, *desc = line[1:].split(' ', 1)
                    original_id = header_id
                    if 'illegal_chars_header' in active_fixes:
                        # MODIFICATION: Apply the new, more specific replacement rules.
                        header_id = header_id.replace('{', '(').replace('}', ')')
                        header_id = header_id.replace('[', '(').replace(']', ')')
                        header_id = header_id.replace('/', '_').replace('\\', '_')
                        header_id = re.sub(r'[!@#$%^*]', '_', header_id)
                        header_id = header_id.replace("'", "").replace('"', "")
                        header_id = header_id.replace(':', '-')
                        header_id = header_id.replace(';', '-')
                        # Clean up multiple spaces that might result from replacements
                        header_id = re.sub(r'\s+', ' ', header_id).strip()

                    if 'duplicate_ids' in active_fixes:
                        new_id = header_id
                        count = 1
                        while new_id in seen_ids:
                            count += 1
                            new_id = f"{header_id}_{count}"
                        header_id = new_id
                    seen_ids.add(header_id)
                    fixed_lines.append(f">{header_id} {''.join(desc)}")
                else:
                    # This part is now handled by the block processing logic
                    # but we keep it for the sequence-line specific fixes
                    seq_data = line
                    if 'internal_stop_codon' in active_fixes and '*' in seq_data.rstrip('*'):
                        continue # Discard sequence
                    if 'terminal_stop_codon' in active_fixes:
                        seq_data = seq_data.rstrip('*')
                    if 'lowercase_sequences' in active_fixes:
                        seq_data = seq_data.upper()
                    # MODIFICATION: Fix for non-standard AAs
                    if 'non_standard_aas' in active_fixes:
                        seq_data = ''.join([char if char.upper() in STANDARD_AMINO_ACIDS or char == '*' else 'X' for char in seq_data])
                    if seq_data: # Don't write empty sequence lines
                        fixed_lines.append(seq_data)
            
            # NEW: Re-process with block logic to handle short sequences
            final_fixed_lines = []
            current_block = []
            for line in fixed_lines:
                if line.startswith('>'):
                    if current_block: # Process previous block
                        seq_data = "".join(current_block[1:])
                        if 'short_sequence' not in active_fixes or len(seq_data) >= 20:
                            final_fixed_lines.extend(current_block)
                    current_block = [line] # Start new block
                else:
                    if current_block: # Only add sequence if a header was found
                        current_block.append(line)
            
            # Process the last block
            if current_block:
                seq_data = "".join(current_block[1:])
                if 'short_sequence' not in active_fixes or len(seq_data) >= 20:
                    final_fixed_lines.extend(current_block)

            # Final cleanup for empty lines if the fix is active
            if 'empty_lines' in active_fixes:
                final_fixed_lines = [line for line in final_fixed_lines if line.strip()]

            # If after all fixes, the file is empty, don't write it
            if not final_fixed_lines:
                continue

            with open(target_path, 'w', encoding='utf-8') as f_out:
                f_out.write('\n'.join(final_fixed_lines))

        # Now, call the original upload logic to combine the (now fixed) files
        # We can reuse the logic from `upload_files` by calling it internally or duplicating it.
        # For simplicity, let's just combine them here.
        input_combined_path = project_input_dir / 'combined.faa'
        output_combined_path = OUTPUT_DIR / current_proj / 'combined.faa'
        total_sequences = 0
        with open(input_combined_path, 'w') as input_outfile, open(output_combined_path, 'w') as output_outfile:
            for filename in fixes_to_apply.keys():
                filepath = project_input_dir / secure_filename(filename)
                if not filepath.exists(): continue
                with open(filepath, 'r') as infile:
                    content = infile.read()
                    total_sequences += content.count('>')
                    input_outfile.write(content + '\n')
                    output_outfile.write(content + '\n')

        # Clean up the temporary validation directory
        shutil.rmtree(temp_dir)

        return jsonify({
            'success': True,
            'message': 'Files fixed and uploaded successfully!',
            'total_sequences': total_sequences,
            'project': current_proj
        })

    except Exception as e:
        return jsonify({'success': False, 'message': f'An error occurred during fixing: {e}'}), 500

@app.route('/api/pdb_search_cache/<path:protein_name>', methods=['GET'])
def get_pdb_search_cache(protein_name):
    """
    Checks for and returns cached PDB search results for a given protein.
    """
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    safe_protein_name = utils.sanitize_protein_name(protein_name)
    pdb_results_dir = STRUCTURE_DIR / current_proj / "pdb_search"
    cached_json_filepath = pdb_results_dir / f"pdb_matches_{safe_protein_name}.json"

    if cached_json_filepath.is_file():
        try:
            with open(cached_json_filepath, 'r') as f:
                cached_matches = json.load(f)
            return jsonify({'success': True, 'matches': cached_matches, 'cached': True})
        except Exception as e:
            # If reading the cache fails, report it.
            return jsonify({'success': False, 'message': f'Error reading cache file: {e}', 'cached': False}), 500
    else:
        # No cache file found, which is a valid state.
        return jsonify({'success': True, 'matches': [], 'cached': False})

@app.route('/api/save_config', methods=['POST'])
def save_project_config():
    """Saves a specific filter's configuration to the project's config file."""
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'message': 'No project selected'}), 400

    data = request.get_json()
    database = data.get('database')
    config = data.get('config')

    if not database or config is None:
        return jsonify({'success': False, 'message': 'Missing database or config data'}), 400

    # The config file will be stored in the project's main output directory
    project_output_dir = OUTPUT_DIR / current_proj
    project_output_dir.mkdir(parents=True, exist_ok=True)
    config_filepath = project_output_dir / 'project_configs.json'

    try:
        all_configs = {}
        if config_filepath.is_file():
            with open(config_filepath, 'r') as f:
                all_configs = json.load(f)
        
        all_configs[database] = config

        with open(config_filepath, 'w') as f:
            json.dump(all_configs, f, indent=2)

        return jsonify({'success': True, 'message': 'Configuration saved.'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@app.route('/api/load_configs', methods=['GET'])
def load_project_configs():
    """Loads all filter configurations for the current project."""
    current_proj = session.get('current_project')
    if not current_proj:
        return jsonify({'success': False, 'configs': {}}), 400

    project_output_dir = OUTPUT_DIR / current_proj
    config_filepath = project_output_dir / 'project_configs.json'

    if config_filepath.is_file():
        try:
            with open(config_filepath, 'r') as f:
                configs = json.load(f)
            return jsonify({'success': True, 'configs': configs})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
    else:
        # It's not an error if the file doesn't exist yet
        return jsonify({'success': True, 'configs': {}})

@app.route('/api/fetch_and_cache_pdb/<pdb_id>', methods=['POST'])
def fetch_and_cache_pdb(pdb_id):
    """
    Acts as a proxy to download a PDB file from RCSB.
    Returns the raw PDB data content without saving it to a file.
    """
    # Download from RCSB
    pdb_url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    try:
        import requests
        response = requests.get(pdb_url, timeout=30)
        response.raise_for_status() # Will raise an HTTPError for bad responses (4xx or 5xx)
        
        pdb_data = response.text
        if not pdb_data:
            return jsonify({'success': False, 'message': 'Downloaded PDB file was empty.'}), 500

        return jsonify({
            'success': True, 
            'pdb_data': pdb_data
        })

    except requests.exceptions.RequestException as e:
        return jsonify({'success': False, 'message': f'Failed to download PDB file from RCSB: {str(e)}'}), 502

# =============================================================================
# WEBSOCKET EVENTS
# =============================================================================

@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    emit('connected', {'message': 'Connected to server'})

@socketio.on('subscribe_job')
def handle_subscribe(data):
    """Subscribe to job updates"""
    job_id = data.get('job_id')
    if job_id in active_jobs:
        job_copy = {k: v for k, v in active_jobs[job_id].items() if k not in ['process', 'timeout_timer']}
        emit('job_update', {
            'job_id': job_id,
            'data': job_copy # This ensures initial subscription also gets clean data
        })

# =============================================================================
# MAIN
# =============================================================================

if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("Bacterial Drug Target Pipeline - Web Interface (v7.2)")
    print("=" * 70)
    print(f"\nServer starting...")
    print(f"  Base directory: {BASE_DIR}")
    print(f"  Scripts directory: {SCRIPTS_DIR}")
    print(f"  Output directory: {OUTPUT_DIR}")
    print(f"\n🌐 Open your browser: http://localhost:5000")
    print(f"\nPress Ctrl+C to stop the server")
    print("=" * 70 + "\n")
    
    # Load existing jobs
    load_jobs()
    
    # Start server
    socketio.run(app, host='127.0.0.1', port=2100, debug=True)
