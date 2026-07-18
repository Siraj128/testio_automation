import sqlite3
import os

db_path = 'data/stats.db'

if not os.path.exists(db_path):
    print("Database not found!")
    exit(1)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM processed_emails")
    conn.commit()
    print("✅ Successfully cleared all processed emails from the database!")
    conn.close()
except sqlite3.OperationalError as e:
    if "no such table" in str(e):
        print("Table 'processed_emails' doesn't exist yet (bot hasn't created it).")
    else:
        print(f"Error: {e}")
