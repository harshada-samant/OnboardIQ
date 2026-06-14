                                                                                        
import json 


import sys
import json
import os
from pathlib import Path
from rich.console import Console

# Add parent workspace and backend directories to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import load_and_validate_env
# Initialize and validate environment
load_and_validate_env()
from agents.migration_generator_agent import run_migration_generator_agent                          
                                                                                                            
# Simulate the context you have (replace with your actual values)                                           
context = json.load(open("D:\\onboardingIQ\\Onboardiq\\workspaces\\users\\user1\\outputs\\context_snapshot.json"))  # Load the context snapshot from a file                                                                                       
                                                                                                            
# Run the agent                                                                                             
result = run_migration_generator_agent(context, verbose=True)    
                                           
                                                                                                            
# Print a brief summary                                                                                     
print("Agent finished. Status:", result.get("migration", {}).get("status"))                                 
print("Generated artifacts:")                                                                               
for art in result.get("migration", {}).get("artifacts", []):                                                
    print(f" - {art['artifact_type']} | {art['entity']} | {art['path']}")                                                                      