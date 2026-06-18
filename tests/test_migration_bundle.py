                                                                                        
import json 


import sys
import json
import os
from pathlib import Path
from rich.console import Console

# from Onboardiq.context import save_snapshot

# Add parent workspace and backend directories to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from agents.migration_generator_agent import run_migration_generator_agent                          
   
from config import load_and_validate_env
from context import save_snapshot
# Initialize and validate environment
load_and_validate_env()
# from agents.migration_generator_agent import run_migration_generator_agent  
from agents.migration_reviewer_agent import run_migration_reviewer_agent
from agents.migration_repair_agent import run_migration_repair_agent
from agents.migration_execution_agent import run_migration_execution_agent                        
from agents.migration_validation_agent import run_migration_validation_agent
                                                                                                            
# Simulate the context you have (replace with your actual values)                                           
ctx = json.load(open("D:\\onboardingIQ\\Onboardiq\\outputs\\context_snapshot.json"))  # Load the context snapshot from a file                                                                                       
result = ctx
                                                                                                            
# Run the agent    
# 
PASSING_STATUSES = {"APPROVED", "APPROVED WITH WARNINGS"}

# 7. Migration Generator
# print( "MigrationAgent", "Starting Migration Code Generator...")
# run_migration_generator_agent(ctx, verbose=True)
# save_snapshot(ctx)
# if ctx.get("migration", {}).get("status") == "FAILED":
#     raise ValueError(ctx.get("migration", {}).get("error", "Migration Generator failed."))

# print("Generated artifacts:")                                                                               
# for art in result.get("migration", {}).get("artifacts", []):                                                
#     print(f" - {art['artifact_type']} | {art['entity']} | {art['path']}")                                                                      


# # 8. Migration Reviewer
# print("MigrationAgent", "Starting Migration Reviewer...")
# run_migration_reviewer_agent(ctx, verbose=True)
# save_snapshot(ctx)
# if ctx.get("review", {}).get("status") == "FAILED":
#     raise ValueError(ctx.get("review", {}).get("error", "Migration Reviewer failed."))

# # 9. Bounded repair loop: up to 2 retries (3 total review runs)
# repair_attempts = 0
# while ctx.get("review", {}).get("status") == "REJECTED" and ctx.get("review", {}).get("fix_required") and repair_attempts < 2:
#     repair_attempts += 1
#     print("MigrationAgent", f"Starting Migration Repair Agent (Attempt {repair_attempts})...")
#     run_migration_repair_agent(ctx, verbose=True)
#     save_snapshot(ctx)
    
#     print("MigrationAgent", f"Re-running Migration Reviewer (Attempt {repair_attempts})...")
#     run_migration_reviewer_agent(ctx, verbose=True)
#     # save_snapshot(ctx)
# 10. Execution Agent (runs only if approved)
if ctx.get("review", {}).get("status") in PASSING_STATUSES:
    print("MigrationAgent", "Starting Migration Execution Agent...")
    run_migration_execution_agent(ctx, verbose=True)
    save_snapshot(ctx)
    if ctx.get("execution", {}).get("status") == "FAILED":
        raise ValueError(ctx.get("execution", {}).get("error", "Migration Execution failed."))

    # 11. Validation Agent
    print("MigrationAgent", "Starting Migration Validation Agent...")
    run_migration_validation_agent(ctx, verbose=True)
    save_snapshot(ctx)
    if ctx.get("validation", {}).get("status") == "FAILED":
        raise ValueError(ctx.get("validation", {}).get("error", "Migration Validation failed."))
    
else:
    msg = "Skipping Execution, Validation, and Approval because Migration Review was not approved."
    print(f"  ! {msg}")
    raise ValueError(msg)
                                                                                                      
# Print a brief summary                                                                                     
print("Agent finished. Status:", result.get("migration", {}).get("status"))                                 





              
