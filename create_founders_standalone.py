"""
create_founders_standalone.py — Seed co-founder super_admin accounts via direct PostgreSQL.
Usage (local): export DATABASE_URL="..." && python create_founders_standalone.py
Usage (Railway): Railway Dashboard → New Job → python create_founders_standalone.py
"""
import os
import sys
import hashlib

psycopg2 = None
try:
    import psycopg2
    from psycopg2 import sql
except ImportError:
    print("Installing psycopg2-binary...")
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2
    from psycopg2 import sql

BCRYPT_COST = 12


def bcrypt_hash(password: str) -> str:
    import bcrypt
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_COST)).decode("utf-8")


FOUNDERS = [
    {
        "username": "ayoub",
        "email": "ayoubhamdi1746@gmail.com",
        "password": "youpipo19",
        "role": "super_admin",
    },
    {
        "username": "eya",
        "email": "eyarzeigui218@gmail.com",
        "password": "israbestie4life",
        "role": "super_admin",
    },
]


def run():
    db_url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    print(f"Connecting to database...")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    # 1. Ensure super_admin role exists in enum
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_type WHERE typname = 'role_enum'
            ) THEN
                -- Try to add to user_role enum
                ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'super_admin';
            END IF;
        EXCEPTION WHEN OTHERS THEN
            RAISE NOTICE 'Enum alter skipped (may already exist or different type): %', SQLERRM;
        END
        $$;
    """)
    print("Checked/updated role enum")

    # 2. Insert or update founders
    results = []
    for f in FOUNDERS:
        identity_id = hashlib.sha256(f"{f['username']}:{f['email']}".encode()).hexdigest()
        hashed_pw = bcrypt_hash(f["password"])

        cur.execute("SELECT id FROM users WHERE username = %s", (f["username"],))
        row = cur.fetchone()

        if row:
            cur.execute("""
                UPDATE users SET
                    role = %s,
                    email = %s,
                    identity_id = %s,
                    hashed_password = %s,
                    is_active = TRUE
                WHERE username = %s
            """, (f["role"], f["email"], identity_id, hashed_pw, f["username"]))
            results.append({"username": f["username"], "status": "updated"})
            print(f"Updated: {f['username']} -> super_admin")
        else:
            cur.execute("""
                INSERT INTO users (id, username, role, email, identity_id, hashed_password, is_active)
                VALUES (gen_random_uuid()::text, %s, %s, %s, %s, %s, TRUE)
            """, (f["username"], f["role"], f["email"], identity_id, hashed_pw))
            results.append({"username": f["username"], "status": "created"})
            print(f"Created: {f['username']} -> super_admin")

    # 3. Deactivate demo admin
    cur.execute("SELECT id FROM users WHERE username = 'admin'")
    if cur.fetchone():
        cur.execute("UPDATE users SET is_active = FALSE WHERE username = 'admin'")
        results.append({"username": "admin", "status": "deactivated"})
        print("Deactivated: admin")
    else:
        results.append({"username": "admin", "status": "not_found"})
        print("Info: no admin account found")

    # 4. Show all super_admin users
    print("\n--- Super Admin Users ---")
    cur.execute("SELECT id, username, email, role, is_active FROM users WHERE role = 'super_admin'")
    rows = cur.fetchall()
    for row in rows:
        print(f"  {row[0]} | {row[1]} | {row[2]} | {row[3]} | active={row[4]}")
    if not rows:
        print("  (none found)")

    cur.close()
    conn.close()
    print("\nDone!")
    return results


if __name__ == "__main__":
    run()