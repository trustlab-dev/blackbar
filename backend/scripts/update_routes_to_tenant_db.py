#!/usr/bin/env python3
"""
Script to update route functions to use tenant_db dependency

This script helps convert routes from using global collections to tenant-specific databases.
"""
import re
import sys
from pathlib import Path

def update_route_signature(content: str) -> str:
    """
    Add tenant_db parameter to route functions that don't have it
    """
    # Pattern to match async def functions with current_user dependency
    pattern = r'(async def \w+\([^)]*)(current_user = Depends\(get_current_user\))'
    
    def replacer(match):
        params = match.group(1)
        current_user_dep = match.group(2)
        
        # Check if tenant_db is already in params
        if 'tenant_db' in params:
            return match.group(0)  # Already has it
        
        # Add tenant_db before current_user
        return f'{params}tenant_db: AsyncIOMotorDatabase = Depends(get_tenant_database_from_request),\n    {current_user_dep}'
    
    return re.sub(pattern, replacer, content)


def replace_collection_access(content: str) -> str:
    """
    Replace direct collection access with tenant_db access
    
    cases.find() -> tenant_db.cases.find()
    documents.find() -> tenant_db.documents.find()
    templates.find() -> tenant_db.templates.find()
    """
    replacements = [
        (r'\bcases\.', 'tenant_db.cases.'),
        (r'\bdocuments\.', 'tenant_db.documents.'),
        (r'\btemplates\.', 'tenant_db.templates.'),
        (r'\bteams\.', 'tenant_db.teams.'),
    ]
    
    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)
    
    return content


def main():
    if len(sys.argv) < 2:
        print("Usage: python update_routes_to_tenant_db.py <routes_file.py>")
        sys.exit(1)
    
    file_path = Path(sys.argv[1])
    
    if not file_path.exists():
        print(f"File not found: {file_path}")
        sys.exit(1)
    
    print(f"Updating {file_path}...")
    
    # Read file
    content = file_path.read_text()
    
    # Apply transformations
    content = update_route_signature(content)
    content = replace_collection_access(content)
    
    # Write back
    file_path.write_text(content)
    
    print(f"✓ Updated {file_path}")
    print("\nPlease review the changes manually!")
    print("Some routes may need manual adjustment.")


if __name__ == "__main__":
    main()
