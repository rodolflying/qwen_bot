import ast
import os
import sys
from importlib.metadata import version, distributions, PackageNotFoundError
from typing import Dict, Set

# Ensure UTF-8 encoding for terminal output
sys.stdout.reconfigure(encoding='utf-8')

# This script generates a requirements.txt file for any Python project (i created this to help me with my own projects)
# It scans all Python files in the current directory and its subdirectories
# for import statements, resolves the package names, and writes them to requirements.txt
# It also handles some common edge cases. 

def get_imports_from_file(filepath: str) -> Set[str]:
    """Extract all imports from a Python file"""
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read())
    
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # Absolute imports only
                imports.add(node.module.split('.')[0])
    return imports

def resolve_package_name(pkg: str) -> str:
    """Resolve import name to package name with multiple fallbacks"""
    # First try direct version lookup (works for most packages)
    try:
        version(pkg)
        return pkg
    except PackageNotFoundError:
        pass
    
    # Check all installed packages
    for dist in distributions():
        try:
            # Method 1: Check top_level.txt
            top_level = (dist.read_text('top_level.txt') or '').split()
            if pkg in top_level:
                return dist.metadata['Name']
            
            # Method 2: Check package metadata
            if pkg.lower() == dist.metadata['Name'].replace('-', '_'):
                return dist.metadata['Name']
                
        except (FileNotFoundError, AttributeError, KeyError):
            continue
    
    return pkg  # Final fallback

def generate_requirements():
    project_dir = os.getcwd()
    requirements = {}
    
    for root, _, files in os.walk(project_dir):
        for file in files:
            if file.endswith('.py'):
                filepath = os.path.join(root, file)
                try:
                    for pkg in get_imports_from_file(filepath):
                        if (pkg not in sys.stdlib_module_names 
                            and not pkg.startswith('_') 
                            and pkg.isidentifier()):
                            
                            resolved_name = resolve_package_name(pkg)
                            try:
                                requirements[resolved_name] = version(resolved_name)
                            except PackageNotFoundError:
                                print(f"⚠️ Could not resolve: {pkg}")
                                requirements[pkg] = "0.0.0"
                except Exception as e:
                    print(f"⚠️ Error parsing {filepath}: {str(e)}")
                    continue
    
    with open("requirements.txt", "w", encoding="utf-8") as f:
        f.write("# Auto-generated requirements.txt\n")
        for pkg, ver in sorted(requirements.items()):
            f.write(f"{pkg}=={ver}\n")
    
    print(f"✅ Generated requirements.txt with {len(requirements)} packages")

if __name__ == "__main__":
    generate_requirements()
    # This script will generate a requirements.txt file in the current directory. You need to paste it in the root of your project.
    # Make sure to run this script in the root directory of your project.
