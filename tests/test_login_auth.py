"""
tests/test_login_auth.py
-------------------------
Validation script to test user validation from SQLite database.
"""

import sys
from pathlib import Path

# Add root workspace and backend directories to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))
sys.path.insert(0, str(root_dir / "backend"))

from backend.database import authenticate_user

def test_login_auth():
    print("=== Testing Login Authentication against SQLite ===")

    # Test case 1: Successful verification of user1
    print("Verifying user1 with correct password...")
    user1_rec = authenticate_user("user1", "password123")
    assert user1_rec is not None, "Failed to authenticate user1 with correct password"
    assert user1_rec["id"] == 1, f"Expected id 1, got {user1_rec['id']}"
    assert user1_rec["username"] == "user1", f"Expected username user1, got {user1_rec['username']}"
    assert "password_hash" not in user1_rec, "Security violation: password_hash returned in user record"
    print("  [OK] user1 authenticated successfully.")
    print(f"  User Record: {user1_rec}")

    # Test case 2: Successful verification of user2
    print("Verifying user2 with correct password...")
    user2_rec = authenticate_user("user2", "password123")
    assert user2_rec is not None, "Failed to authenticate user2 with correct password"
    assert user2_rec["id"] == 2, f"Expected id 2, got {user2_rec['id']}"
    assert user2_rec["username"] == "user2", f"Expected username user2, got {user2_rec['username']}"
    assert "password_hash" not in user2_rec, "Security violation: password_hash returned in user record"
    print("  [OK] user2 authenticated successfully.")
    print(f"  User Record: {user2_rec}")

    # Test case 3: Unsuccessful verification of user1 with wrong password
    print("Verifying user1 with incorrect password...")
    assert authenticate_user("user1", "wrongpassword") is None, "Authenticated user1 with wrong password!"
    print("  [OK] user1 wrong password rejected successfully.")

    # Test case 4: Unsuccessful verification of nonexistent user
    print("Verifying nonexistent user...")
    assert authenticate_user("invalid_username_123", "password123") is None, "Authenticated nonexistent user!"
    print("  [OK] nonexistent user rejected successfully.")

    print("\n=== All Database Authentication Validation Tests Passed! ===")

if __name__ == "__main__":
    try:
        test_login_auth()
    except AssertionError as e:
        print(f"Assertion Error during validation: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error during validation: {e}")
        sys.exit(1)

