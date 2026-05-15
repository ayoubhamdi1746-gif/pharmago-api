"""
migrate_users.py — Railway Job script: add missing columns to users table.
Run via: Railway Dashboard → web service → New Job → python migrate_users.py
"""
import os, sys

try:
    import psycopg2
except ImportError:
    os.system(f"{sys.executable} -m pip install psycopg2-binary -q")
    import psycopg2

db_url = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
if not db_url:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

conn = psycopg2.connect(db_url)
conn.autocommit = True
cur = conn.cursor()

migrations = [
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS pharmacy_id VARCHAR(36)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS city VARCHAR(100)",
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255)",
]

for sql in migrations:
    try:
        cur.execute(sql)
        print(f"OK: {sql}")
    except Exception as e:
        print(f"ERROR: {sql} -> {e}")

cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'users' ORDER BY ordinal_position")
print(f"Columns: {[r[0] for r in cur.fetchall()]}")

cur.close()
conn.close()
print("Done.")