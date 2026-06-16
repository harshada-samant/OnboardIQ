"""
seed_db.py
----------
Standalone utility script to initialize and seed the SQLite database.
"""

import sys
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

from backend.database import initialize_database, seed_users

def main():
    print("Initializing SQLite database...")
    initialize_database()
    print("Database initialized successfully.")
    
    print("Seeding database users...")
    seed_users()
    print("Seeding complete.")

if __name__ == "__main__":
    main()
