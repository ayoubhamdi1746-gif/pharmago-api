"""
create_founders.py — Seed co-founder super_admin accounts via direct PostgreSQL.
Run locally: cd pharmago-api && railway run python create_founders.py
"""
import os, sys, hashlib

try:
    import psycopg2
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2

import bcrypt

FOUNDERS = [
    {"username": "ayoub", "email": "ayoubhamdi1746@gmail.com", "password": "youpipo19", "role": "super_admin"},
    {"username": "eya",   "email": "eyarzeigui218@gmail.com",   "password": "israbestie4life",  "role": "super_admin"},
]

def run():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print("Connecting...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    results = []
    for f in FOUNDERS:
        identity_id = hashlib.sha256(f"{f['username']}:{f['email']}".encode()).hexdigest()
        hashed = bcrypt.hashpw(f["password"].encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

        cur.execute("SELECT id FROM users WHERE username = %s", (f["username"],))
        row = cur.fetchone()

        if row:
            cur.execute("""
                UPDATE users SET role=%s, email=%s, identity_id=%s, hashed_password=%s, is_active=TRUE
                WHERE username=%s
            """, (f["role"], f["email"], identity_id, hashed, f["username"]))
            results.append({"username": f["username"], "status": "updated"})
            print(f"Updated: {f['username']} -> super_admin")
        else:
            cur.execute("""
                INSERT INTO users (id, username, role, email, identity_id, hashed_password, is_active)
                VALUES (gen_random_uuid()::text, %s, %s, %s, %s, %s, TRUE)
            """, (f["username"], f["role"], f["email"], identity_id, hashed))
            results.append({"username": f["username"], "status": "created"})
            print(f"Created: {f['username']} -> super_admin")

    cur.execute("SELECT id FROM users WHERE username = 'admin'")
    if cur.fetchone():
        cur.execute("UPDATE users SET is_active = FALSE WHERE username = 'admin'")
        results.append({"username": "admin", "status": "deactivated"})
        print("Deactivated: admin")

    print("\n--- Super Admin Users ---")
    cur.execute("SELECT id, username, email, role, is_active FROM users WHERE role = 'super_admin'")
    for r in cur.fetchall():
        print(f"  {r[1]} | {r[2]} | {r[3]} | active={r[4]}")

    cur.close()
    conn.close()
    print("\nDone!")

if __name__ == "__main__":
    run()