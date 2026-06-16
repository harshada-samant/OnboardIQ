"""
backend/database.py
-------------------
SQLite database initialization, schema definition, and seeding helpers.
"""

import sqlite3
import bcrypt
import config

def get_db_connection() -> sqlite3.Connection:
    """
    Establishes and returns a database connection to the SQLite database.
    Sets Row factory for dictionary-like access to records.
    """
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def initialize_database() -> None:
    """
    Initializes the SQLite database and creates the users table if it does not exist.
    """
    query = """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        target_schema TEXT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    with get_db_connection() as conn:
        conn.execute(query)
        conn.commit()

def hash_password(password: str) -> str:
    """
    Generates a bcrypt hash for the given plaintext password.
    """
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')

def seed_users() -> None:
    """
    Seeds default demo users into the database.
    - user1 / password123
    - user2 / password123
    Password hashes are stored using bcrypt.
    """
    users_to_seed = [
        ("user1", "password123"),
        ("user2", "password123")
    ]
    
    with get_db_connection() as conn:
        for username, password in users_to_seed:
            pwd_hash = hash_password(password)
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                    (username, pwd_hash)
                )
                print(f"  + Seeded user: {username}")
            except sqlite3.IntegrityError:
                # User already exists, skip
                print(f"  ~ User already exists, skipping: {username}")
        conn.commit()

def authenticate_user(username: str, password: str) -> dict | None:
    """
    Validates user credentials against the SQLite database.
    Returns the user record (dict) if valid, None otherwise.
    The returned dictionary does NOT include the password_hash.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, target_schema, password_hash FROM users WHERE username = ?",
            (username,)
        )
        row = cursor.fetchone()
        if row:
            user_id, name, target_schema, db_hash = row
            if bcrypt.checkpw(password.encode('utf-8'), db_hash.encode('utf-8')):
                return {
                    "id": user_id,
                    "username": name,
                    "target_schema": target_schema
                }
    return None


def update_user_target_schema(user_id: int, schema_name: str) -> None:
    """
    Updates the target_schema field for the specified user ID.
    Validates that:
      - schema_name is a string and not empty.
      - schema_name ends with '.json'.
      - schema file exists at config.SCHEMAS_DIR / schema_name.
      - user_id exists in the users table.
    Raises ValueError for invalid values.
    """
    # 1. Type check
    if not isinstance(schema_name, str):
        raise ValueError("Schema name must be a string.")
    
    # 2. Empty check
    if not schema_name:
        raise ValueError("Schema name must not be empty.")
    if not schema_name.strip():
        raise ValueError("Schema name must not be empty or whitespace only.")
        
    # 3. Ends with .json check
    if not schema_name.endswith(".json"):
        raise ValueError("Schema name must end with '.json'.")
        
    # 4. Schema file existence check
    schema_file = config.SCHEMAS_DIR / schema_name
    if not schema_file.is_file():
        raise ValueError(f"Schema file '{schema_name}' does not exist in {config.SCHEMAS_DIR}.")
        
    # 5. User existence check and DB update
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if not cursor.fetchone():
            raise ValueError(f"User with ID {user_id} does not exist.")
            
        cursor.execute(
            "UPDATE users SET target_schema = ? WHERE id = ?",
            (schema_name, user_id)
        )
        conn.commit()


def get_user_target_schema(user_id: int) -> str | None:
    """
    Retrieves the target_schema filename for the specified user ID.
    Returns None if the user does not exist or target_schema is not set.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT target_schema FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return row["target_schema"]
    return None


def get_username_by_id(user_id: int) -> str:
    """
    Retrieves the username for the specified user ID.
    Raises ValueError if the user ID does not exist in the database.
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT username FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if not row:
            raise ValueError(f"User with ID {user_id} does not exist.")
        return row["username"]




