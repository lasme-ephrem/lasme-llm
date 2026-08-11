import sqlite3

GLIMMER = "muse-glimmer:30b-q4_K_M-dflash"
OLD = ("gemma-4-chat", "gemma-4-fable")

db = sqlite3.connect("lasme_llm.db")
c = db.cursor()

p = c.execute(
    "UPDATE projects SET default_model=? WHERE default_model IN (?, ?)",
    (GLIMMER, *OLD),
).rowcount
s = c.execute(
    "UPDATE sessions SET model=? WHERE model IN (?, ?)",
    (GLIMMER, *OLD),
).rowcount
db.commit()

print(f"Projets migrés: {p}")
print(f"Sessions migrées: {s}")
print("--- projects ---")
for r in c.execute("SELECT id, name, default_model FROM projects"):
    print(r)
print("--- sessions (models distincts) ---")
for r in c.execute("SELECT DISTINCT model FROM sessions"):
    print(r)
