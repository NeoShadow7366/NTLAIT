import sqlite3
import json

def check_db():
    conn = sqlite3.connect('.backend/metadata.sqlite')
    try:
        cur = conn.cursor()
        print("--- PROMPTS ---")
        prompts = cur.execute('SELECT title, prompt, negative, model FROM prompts WHERE title LIKE "%Rainbow lady%"').fetchall()
        for p in prompts:
            print(p)
    except Exception as e:
        print("Error reading prompts:", e)

    try:
        cur = conn.cursor()
        print("\n--- MODELS ---")
        models = cur.execute('SELECT filename, vault_category FROM models').fetchall()
        for m in models:
            print(m)
    except Exception as e:
        print("Error reading models:", e)

if __name__ == "__main__":
    check_db()
