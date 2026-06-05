#!/usr/bin/env python3
"""
Extract all API routes from the FastAPI application.
Outputs a structured list of all endpoints with methods, paths, and handlers.
"""
import ast
import os
from pathlib import Path
from typing import List, Dict, Any

def extract_routes_from_file(file_path: str) -> List[Dict[str, Any]]:
    """Extract route definitions from a Python file."""
    routes = []
    
    with open(file_path, 'r') as f:
        try:
            tree = ast.parse(f.read())
        except SyntaxError:
            print(f"Syntax error in {file_path}")
            return routes
    
    # Find router prefix
    router_prefix = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "router":
                    if isinstance(node.value, ast.Call):
                        for keyword in node.value.keywords:
                            if keyword.arg == "prefix":
                                if isinstance(keyword.value, ast.Constant):
                                    router_prefix = keyword.value.value
    
    # Find all decorated functions
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                route_info = parse_decorator(decorator, node.name, router_prefix)
                if route_info:
                    route_info['file'] = file_path
                    routes.append(route_info)
    
    return routes

def parse_decorator(decorator, func_name: str, router_prefix: str) -> Dict[str, Any]:
    """Parse a route decorator to extract method and path."""
    if not isinstance(decorator, ast.Call):
        return None
    
    # Check if it's a router decorator
    if not isinstance(decorator.func, ast.Attribute):
        return None
    
    if not isinstance(decorator.func.value, ast.Name):
        return None
    
    if decorator.func.value.id != "router":
        return None
    
    method = decorator.func.attr.upper()
    if method not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
        return None
    
    # Extract path
    path = "/"
    if decorator.args:
        if isinstance(decorator.args[0], ast.Constant):
            path = decorator.args[0].value
    
    # Combine with router prefix
    full_path = router_prefix + path if path != "/" or not router_prefix else router_prefix + path
    
    return {
        'method': method,
        'path': full_path,
        'handler': func_name
    }

def main():
    """Main function to extract all routes."""
    src_dir = Path(__file__).parent.parent / "src"
    
    all_routes = []
    
    # Find all routes.py files
    for routes_file in src_dir.rglob("*routes.py"):
        if "__pycache__" in str(routes_file):
            continue
        
        module = str(routes_file.relative_to(src_dir))
        routes = extract_routes_from_file(str(routes_file))
        
        for route in routes:
            route['module'] = module
            all_routes.append(route)
    
    # Sort by path
    all_routes.sort(key=lambda x: (x['path'], x['method']))
    
    # Print results
    print(f"Found {len(all_routes)} routes:\n")
    print(f"{'Method':<8} {'Path':<60} {'Handler':<40} {'Module'}")
    print("=" * 150)
    
    for route in all_routes:
        print(f"{route['method']:<8} {route['path']:<60} {route['handler']:<40} {route['module']}")

if __name__ == "__main__":
    main()
