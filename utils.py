import re

def sanitize_protein_name(protein_name: str) -> str:
    """
    Sanitizes a protein name to create a safe and consistent filename component.
    Matches legacy file naming convention to ensure existing files are found.
    """
    # Legacy sanitization logic that matches currently generated files
    # This preserves '=', '[', ']', and creates multiple underscores '___' which exist in the filenames
    return protein_name.replace('/', '_').replace('(', '').replace(')', '').replace(',', '').replace(' ', '_').replace("'", "")