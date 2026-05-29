"""Find FOREX MARKET CONQUER group ID in the session SQLite cache."""
import sqlite3
import pathlib

session_file = pathlib.Path("runtime/sessions/telegram-signal-copier-listener.session")
conn = sqlite3.connect(str(session_file))
cur = conn.cursor()

rows = cur.execute(
    "SELECT id, name, username FROM entities WHERE name LIKE '%onquer%' OR name LIKE '%FOREX%MARKET%'"
).fetchall()
if rows:
    for row in rows:
        print(f"ID: {row[0]}  Name: {row[1]}  Username: {row[2]}")
else:
    print("Not found — searching all FOREX-related entries:")
    rows2 = cur.execute("SELECT id, name, username FROM entities WHERE name LIKE '%orex%'").fetchall()
    for row in rows2:
        print(f"ID: {row[0]}  Name: {row[1]}  Username: {row[2]}")

conn.close()
