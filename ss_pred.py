#!/usr/bin/env python3
"""
Integrated Protein Secondary Structure Prediction and Visualization Pipeline
Runs s4pred prediction and creates visualization in one step
"""

import subprocess
import sys
import os
import argparse
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrow
import numpy as np


def run_s4pred(input_fasta, output_ss2, s4pred_path):
    """Run s4pred secondary structure prediction"""
    print(f"\n{'='*60}")
    print("STEP 1: Running Secondary Structure Prediction (s4pred)")
    print(f"{'='*60}")
    print(f"Input file: {input_fasta}")
    print(f"Output file: {output_ss2}")
    
    s4pred_path = Path(s4pred_path)
    input_fasta = Path(input_fasta)

    # Check if input file exists
    if not input_fasta.is_file():
        raise FileNotFoundError(f"Input FASTA file not found: {input_fasta}")
    
    # Check if s4pred exists
    if not s4pred_path.is_file():
        raise FileNotFoundError(f"s4pred script not found: {s4pred_path}")
    
    # Run s4pred
    cmd = [sys.executable, str(s4pred_path), str(input_fasta)]
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Write output to ss2 file
        with open(output_ss2, 'w') as f:
            f.write(result.stdout)
        
        print(f"✓ Prediction complete! Output saved to: {output_ss2}")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"✗ Error running s4pred:")
        print(f"  {e.stderr}")
        return False


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
    ax.fill_between(x, y_curve - 0.1, y_curve + 0.1, alpha=0.3, color='red')


def draw_strand(ax, start_x, end_x, y, height=0.3):
    """Draw a beta-strand as an arrow"""
    arrow_width = height
    arrow_length = end_x - start_x
    
    # Draw the arrow (beta-strand)
    arrow = FancyArrow(start_x, y, arrow_length * 0.85, 0, 
                       width=arrow_width,
                       head_width=arrow_width * 1.6,
                       head_length=arrow_length * 0.15,
                       fc='gold', ec='orange', linewidth=2,
                       length_includes_head=True)
    ax.add_patch(arrow)


def draw_coil(ax, start_x, end_x, y, height=0.1):
    """Draw a coil/loop as a line"""
    ax.plot([start_x, end_x], [y, y], 'gray', linewidth=4, solid_capstyle='round')


def visualize_secondary_structure(sequence, structure, output_file='secondary_structure_viz.png', 
                                 font_size=10, font_weight='normal'):
    """Create visualization of secondary structure"""
    
    print(f"\n{'='*60}")
    print("STEP 2: Creating Visualization")
    print(f"{'='*60}")
    print(f"Sequence length: {len(sequence)}")
    print(f"Structure: {''.join(structure)}")
    print(f"Font settings: size={font_size}, weight={font_weight}")

    # --- MODIFICATION: Revert to a single long row instead of wrapping ---
    unit_width = 0.8 # Keep the tighter spacing for better alignment with MSA text
    fig_width = len(sequence) * 0.5 * unit_width # Calculate width based on full sequence length
    fig_height = 6  # MODIFICATION: Increased from 4 to make the image taller

    # Create figure
    fig, ax = plt.subplots(figsize=(max(15, fig_width), fig_height))
    
    y_center = fig_height / 2 # Center the visualization vertically

    # Group consecutive same structures for the entire sequence
    segments = []
    if structure:
        current_type = structure[0]
        start_idx = 0
        for i in range(1, len(structure)):
            if structure[i] != current_type:
                segments.append((current_type, start_idx, i - 1))
                current_type = structure[i]
                start_idx = i
        segments.append((current_type, start_idx, len(structure) - 1))

    # Draw each segment
    for ss_type, start_idx, end_idx in segments:
        start_x = start_idx * unit_width
        end_x = (end_idx + 1) * unit_width
        
        if ss_type == 'H':
            draw_helix(ax, start_x, end_x, y_center, height=0.6) # MODIFICATION: Increased height
        elif ss_type == 'E':
            draw_strand(ax, start_x, end_x, y_center, height=0.5) # MODIFICATION: Increased height
        else:  # 'C' or coil
            draw_coil(ax, start_x, end_x, y_center)

    # Add amino acid labels and position numbers
    for i, aa in enumerate(sequence):
        x = i * unit_width + unit_width / 2
        pos = i + 1
        
        # Add amino acid label
        ax.text(x, y_center - 1.2, aa, ha='center', va='top', # MODIFICATION: Increased vertical offset
                fontsize=font_size, family='monospace', weight=font_weight)
        
        # Add position number every 10 residues
        if pos % 10 == 0 or pos == 1:
            ax.text(x, y_center + 1.2, str(pos), ha='center', va='bottom', # MODIFICATION: Increased vertical offset
                    fontsize=font_size - 2, family='sans-serif', color='gray')
    # --- END MODIFICATION ---
    
    # Set axis properties
    ax.set_xlim(-0.5 * unit_width, len(sequence) * unit_width + 0.5 * unit_width)
    ax.set_ylim(0, fig_height)
    ax.axis('off')
    
    # Add legend
    helix_patch = mpatches.Patch(color='red', label='Alpha-Helix (H)')
    strand_patch = mpatches.Patch(color='gold', label='Beta-Strand (E)')
    coil_patch = mpatches.Patch(color='gray', label='Coil (C)')
    legend = ax.legend(handles=[helix_patch, strand_patch, coil_patch], 
             title="Note: The highlighted sequence is the selected reference.\n\nStructure Legend:",
             loc='lower left', bbox_to_anchor=(0, 0), frameon=False, fancybox=True)
    legend.get_title().set_ha("left")
    
    # Save figure
    plt.tight_layout()
    plt.savefig(output_file, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"✓ Visualization saved to: {output_file}")


def count_structures(structure):
    """Count helix, strand, and coil residues"""
    counts = {'H': 0, 'E': 0, 'C': 0}
    for ss in structure:
        if ss in counts:
            counts[ss] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(
        description='Integrated secondary structure prediction and visualization pipeline',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage (uses default paths)
  python3 predict_and_visualize_ss.py protein.faa

  # Specify all parameters
  python3 predict_and_visualize_ss.py protein.faa --output protein_ss.png --font-size 10

  # Custom s4pred path
  python3 predict_and_visualize_ss.py protein.faa --s4pred /path/to/run_model.py
        """
    )
    
    parser.add_argument('input_fasta', 
                        help='Input protein FASTA file')
    parser.add_argument('--s4pred', 
                        default=str(Path(__file__).parent.parent / 'db' / 's4pred' / 'run_model.py'),
                        help='Path to s4pred run_model.py script')
    parser.add_argument('--ss2', 
                        help='Output .ss2 file (default: input_basename.ss2)')
    parser.add_argument('--output', '-o',
                        help='Output visualization PNG file (default: input_basename_viz.png)')
    parser.add_argument('--font-size', type=int, default=10,
                        help='Font size for amino acid labels (default: 8)')
    parser.add_argument('--font-weight', default='normal',
                        help='Font weight: normal, bold, light, or numeric 100-900 (default: normal)')
    parser.add_argument('--no-viz', action='store_true',
                        help='Skip visualization step (only run prediction)')
    
    args = parser.parse_args()
    
    input_path = Path(args.input_fasta).resolve()
    
    # If output paths are not provided, derive them from the input file name.
    if args.ss2:
        ss2_file = Path(args.ss2)
    else:
        ss2_file = input_path.with_suffix('.ss2')
    
    if args.output:
        viz_file = Path(args.output)
    else:
        viz_file = input_path.with_suffix('.png')
    
    print("\n" + "="*60)
    print("PROTEIN SECONDARY STRUCTURE PREDICTION & VISUALIZATION")
    print("="*60)
    print(f"Input FASTA: {args.input_fasta}")
    print(f"Output SS2: {ss2_file}")
    if not args.no_viz:
        print(f"Output visualization: {viz_file}")
    
    try:
        # Step 1: Run prediction
        success = run_s4pred(args.input_fasta, ss2_file, args.s4pred)
        
        if not success:
            print("\n✗ Pipeline failed at prediction step")
            sys.exit(1)
        
        # Step 2: Visualize (unless skipped)
        if not args.no_viz:
            sequence, structure = parse_ss2_file(ss2_file)
            
            if not sequence:
                print("\n✗ No sequence data found in .ss2 file")
                sys.exit(1)
            
            visualize_secondary_structure(sequence, structure, viz_file, 
                                        args.font_size, args.font_weight)
            
            # Print summary statistics
            counts = count_structures(structure)
            total = len(structure)
            print(f"\n{'='*60}")
            print("SUMMARY")
            print(f"{'='*60}")
            print(f"Total residues: {total}")
            print(f"Helix (H):      {counts['H']:4d} ({counts['H']/total*100:5.1f}%)")
            print(f"Strand (E):     {counts['E']:4d} ({counts['E']/total*100:5.1f}%)")
            print(f"Coil (C):       {counts['C']:4d} ({counts['C']/total*100:5.1f}%)")
        
        print(f"\n{'='*60}")
        print("✓ PIPELINE COMPLETE!")
        print(f"{'='*60}\n")
        
    except FileNotFoundError as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()