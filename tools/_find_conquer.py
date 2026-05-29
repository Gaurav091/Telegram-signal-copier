"""Query the Telethon session SQLite cache for FOREX MARKET CONQUER without connecting."""
import re
import sqlite3

DB = "runtime/sessions/telegram-signal-copier.session"

con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
rows = list(con.execute("SELECT id, hash, username, name FROM entities ORDER BY name"))
con.close()
print(f"Total entities cached: {len(rows)}")
found = []
for row in rows:
    name = row[3] or ""
    username = row[2] or ""
    if re.search(r"conquer|forex.{0,5}market", name, re.IGNORECASE) or \
       re.search(r"conquer|forex.{0,5}market", username, re.IGNORECASE):
        found.append(row)
        print(f"FOUND  id={row[0]}  hash={row[1]}  username={username!r}  name={name!r}")

if not found:
    print("Group not in entity cache — not yet seen by listener.")
    print("\nAll cached entities:")
    for row in rows:
        name = row[3] or ""
        print(f"  {name:60s}  @{row[2] or '':30s}  id={row[0]}")
