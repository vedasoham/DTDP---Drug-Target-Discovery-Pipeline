#!/usr/bin/env python3
"""
Protein Secondary Structure Visualization
Visualizes PSIPRED output showing helices, coils, and beta-strands
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrow
import numpy as np

def parse_ss2_file(filename):
    """Parse PSIPRED .ss2 file and extract sequence and structure"""
    sequence = []
    structure = []
    
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if line.startswith('#') or not line:
                continue
            
            parts = line.split()
            if len(parts) >= 3:
                # Format: position amino_acid structure confidence1 confidence2 confidence3
                pos = parts[0]
                aa = parts[1]
                ss = parts[2]
                
                sequence.append(aa)
                structure.append(ss)
    
    return sequence, structure

def draw_helix(ax, start_x, end_x, y, height=0.4, n_turns=None):
    """Draw a helix representation"""
    length = end_x - start_x
    
    # Calculate number of turns based on length
    if n_turns is None:
        n_turns = max(2, int(length / 1.5))
    
    # Generate helix curve
    t = np.linspace(0, n_turns * 2 * np.pi, 200)
    x = np.linspace(start_x, end_x, 200)
    y_curve = y + height * 0.5 * np.sin(t)
    
    # Draw the helix with thicker line
    ax.plot(x, y_curve, 'r-', linewidth=5, solid_capstyle='round')
    
    # Add shading to give 3D effect
    ax.fill_between(x, y_curve - 0.08, y_curve + 0.08, alpha=0.3, color='red')

def draw_strand(ax, start_x, end_x, y, height=0.3):
    """Draw a beta-strand as an arrow"""
    arrow_width = height
    arrow_length = end_x - start_x
    
    # Draw the arrow (beta-strand)
    arrow = FancyArrow(start_x, y, arrow_length * 0.85, 0, 
                       width=arrow_width, 
                       head_width=arrow_width * 1.8, 
                       head_length=arrow_length * 0.15,
                       fc='gold', ec='orange', linewidth=2,
                       length_includes_head=True)
    ax.add_patch(arrow)

def draw_coil(ax, start_x, end_x, y, height=0.1):
    """Draw a coil/loop as a line"""
    ax.plot([start_x, end_x], [y, y], 'gray', linewidth=4, solid_capstyle='round')

def visualize_secondary_structure(sequence, structure, output_file='secondary_structure_viz.png', 
                                 font_size=8, font_weight='normal'):
    """Create visualization of secondary structure
    
    Args:
        sequence: List of amino acids
        structure: List of secondary structures (H/E/C)
        output_file: Output filename
        font_size: Font size for amino acid labels (default: 8)
        font_weight: Font weight - 'normal', 'bold', 'light', or numeric (100-900) (default: 'normal')
    """
    
    # Create figure
    fig, ax = plt.subplots(figsize=(max(15, len(sequence) * 0.4), 4))
    
    y_center = 0.5
    x_pos = 0
    unit_width = 1.0
    
    # Group consecutive same structures
    segments = []
    if structure:
        current_type = structure[0]
        start_idx = 0
        
        for i in range(1, len(structure)):
            if structure[i] != current_type:
                segments.append((current_type, start_idx, i - 1))
                current_type = structure[i]
                start_idx = i
        
        # Add last segment
        segments.append((current_type, start_idx, len(structure) - 1))
    
    # Draw each segment
    for ss_type, start_idx, end_idx in segments:
        start_x = start_idx * unit_width
        end_x = (end_idx + 1) * unit_width
        
        if ss_type == 'H':
            draw_helix(ax, start_x, end_x, y_center)
        elif ss_type == 'E':
            draw_strand(ax, start_x, end_x, y_center)
        else:  # 'C' or coil
            draw_coil(ax, start_x, end_x, y_center)
    
    # Add amino acid labels below
    for i, (aa, ss) in enumerate(zip(sequence, structure)):
        x = i * unit_width + unit_width / 2
        ax.text(x, y_center - 0.6, aa, ha='center', va='top', 
                fontsize=font_size, family='monospace', weight=font_weight)
    
    # Set axis properties
    ax.set_xlim(-0.5, len(sequence) * unit_width + 0.5)
    ax.set_ylim(-1, 1.5)
    ax.set_aspect('equal')
    ax.axis('off')
    
    # Save figure
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"Visualization saved to: {output_file}")