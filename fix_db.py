import sqlite3

conn = sqlite3.connect('expenses.db')
c = conn.cursor()

# tambah column date kalau belum ada
try:
    c.execute("ALTER TABLE expenses ADD COLUMN date TEXT")
    print("Column date added")
except:
    print("Column already exists")

conn.commit()
conn.close()