"""
Tool 4: output_tools.py
------------------------
Saves agent outputs to disk and into the shared context store.
Every agent calls this at the end to persist its results.
"""

import json
import os
from datetime import datetime
import config


def save_output(data: dict, filename: str) -> dict:
    """
    Saves a dictionary as a JSON file in the outputs/ directory.
    
    The Discovery Agent calls this to save the entity catalog.
    All subsequent agents will load this as their starting point.

    Returns the file path so the LLM knows where it was saved.
    """
    try:
        os.makedirs(config.OUTPUT_DIR, exist_ok=True)

        # Add metadata
        data["_meta"] = {
            "saved_at": datetime.utcnow().isoformat(),
            "filename": filename
        }

        file_path = os.path.join(config.OUTPUT_DIR, filename)
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return {
            "status": "success",
            "saved_to": file_path,
            "keys_saved": [k for k in data.keys() if k != "_meta"]
        }

    except Exception as e:
        return {"error": f"Failed to save output: {str(e)}"}


def load_output(filename: str) -> dict:
    """
    Loads a previously saved output JSON file.
    Used by downstream agents to read previous agent results.
    """
    try:
        file_path = os.path.join(config.OUTPUT_DIR, filename)
        if not os.path.exists(file_path):
            return {"error": f"Output file not found: {file_path}"}

        with open(file_path, "r") as f:
            return json.load(f)

    except Exception as e:
        return {"error": f"Failed to load output: {str(e)}"}

