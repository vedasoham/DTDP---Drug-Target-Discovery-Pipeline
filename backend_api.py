#!/usr/bin/env python3
"""
Backend API Endpoints for V4
Add these to your app.py file
"""

# ============================================================================
# ADD THESE IMPORTS AT THE TOP OF app.py
# ============================================================================

import json
from pathlib import Path
from datetime import datetime

# ============================================================================
# ADD THESE ROUTES TO YOUR app.py
# ============================================================================

@app.route('/api/current_project')
def get_current_project():
    """Get current project"""
    project = session.get('current_project')
    return jsonify({'project': project})


@app.route('/api/projects')
def list_projects():
    """List all available projects"""
    projects_dir = Path('projects')
    projects_dir.mkdir(exist_ok=True)
    
    projects = []
    for project_file in projects_dir.glob('*.json'):
        try:
            with open(project_file) as f:
                project_data = json.load(f)
                projects.append(project_data)
        except Exception as e:
            print(f"Error loading project {project_file}: {e}")
            pass
    
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
        
        # Create project directory if it doesn't exist
        project_dir = Path('targetX') / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        
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
    
    # Sanitize project name - keep alphanumeric, spaces, hyphens, underscores
    safe_name = "".join(c for c in project_name if c.isalnum() or c in '_- ')
    safe_name = safe_name.strip()
    
    if not safe_name:
        return jsonify({'success': False, 'message': 'Invalid project name'})
    
    # Create project directories
    project_dir = Path('targetX') / safe_name
    project_dir.mkdir(parents=True, exist_ok=True)
    
    # Create input directory for project
    input_dir = Path('input_sequences') / safe_name
    input_dir.mkdir(parents=True, exist_ok=True)
    
    # Save project metadata
    project_data = {
        'name': safe_name,
        'description': description,
        'created_at': datetime.now().isoformat(),
        'last_updated': datetime.now().isoformat()
    }
    
    projects_dir = Path('projects')
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


@app.route('/api/get_initial_sequences')
def get_initial_sequences():
    """Get initial input sequence count"""
    try:
        # Try project-specific combined file first
        current_project = session.get('current_project')
        
        if current_project:
            combined_file = Path('targetX') / current_project / 'combined.faa'
        else:
            combined_file = Path('targetX/combined.faa')
        
        if combined_file.exists():
            with open(combined_file) as f:
                count = sum(1 for line in f if line.startswith('>'))
            return jsonify({'count': count})
        
        # Try default location
        combined_file = Path('targetX/combined.faa')
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
    job = jobs.get(job_id)
    
    if not job:
        return jsonify({'success': False, 'message': 'Job not found'})
    
    if job['status'] not in ['running', 'queued']:
        return jsonify({
            'success': False, 
            'message': f'Job is not running (status: {job["status"]})'
        })
    
    # Kill the process if it exists
    if 'process' in job and job['process']:
        try:
            import signal
            import os
            
            # Try graceful termination first
            if hasattr(job['process'], 'pid'):
                pid = job['process'].pid
                try:
                    os.kill(pid, signal.SIGTERM)
                    job['process'].wait(timeout=5)
                except:
                    # Force kill if graceful didn't work
                    try:
                        os.kill(pid, signal.SIGKILL)
                    except:
                        pass
            else:
                job['process'].terminate()
                job['process'].wait(timeout=5)
        except Exception as e:
            print(f"Error terminating process: {e}")
            try:
                job['process'].kill()
            except:
                pass
    
    # Update job status
    job['status'] = 'failed'
    job['progress'] = 0
    job['current_step'] = 'Job manually stopped by user'
    job['ended_at'] = datetime.now().isoformat()
    
    # Broadcast update
    try:
        emit('job_update', {
            'job_id': job_id, 
            'data': job
        }, namespace='/', broadcast=True)
    except:
        pass
    
    return jsonify({'success': True, 'message': 'Job stopped successfully'})


# ============================================================================
# ALSO UPDATE THIS EXISTING ROUTE (if you have session management)
# ============================================================================

# Make sure you have a secret key for sessions
# Add near the top of app.py if not already present:

# app.secret_key = 'your-secret-key-here-change-this-to-random-string'
# Or better yet, use environment variable:
# import os
# app.secret_key = os.environ.get('SECRET_KEY', 'dev-key-change-in-production')


# ============================================================================
# NOTES
# ============================================================================

# 1. Make sure you have Flask session support enabled
# 2. The 'jobs' dictionary should be accessible (global or app context)
# 3. The 'emit' function requires Flask-SocketIO
# 4. Project directories are created in:
#    - targetX/<project_name>/  (for pipeline outputs)
#    - input_sequences/<project_name>/  (for input files)
#    - projects/  (for project metadata)

# 5. To test the API endpoints:
"""
# Test in terminal:

# Get current project
curl http://localhost:5000/api/current_project

# List projects
curl http://localhost:5000/api/projects

# Create project
curl -X POST http://localhost:5000/api/create_project \
  -H "Content-Type: application/json" \
  -d '{"name": "Test_Project", "description": "Test project"}'

# Set project
curl -X POST http://localhost:5000/api/set_project \
  -H "Content-Type: application/json" \
  -d '{"project": "Test_Project"}'

# Get initial sequences
curl http://localhost:5000/api/get_initial_sequences

# End job
curl -X POST http://localhost:5000/api/end_job/JOB_ID_HERE
"""