import sqlite3

def check_models():
    conn = sqlite3.connect("g:/AG SM/.backend/metadata.sqlite")
    cursor = conn.cursor()
    cursor.execute("SELECT m.name, m.file_path, c.name FROM models m JOIN categories c ON m.category_id = c.id WHERE c.name = 'vaes' OR c.name = 'vae'")
    rows = cursor.fetchall()
    print("VAEs:")
    for row in rows:
        print(row)
    
    conn.close()

if __name__ == "__main__":
    check_models()
