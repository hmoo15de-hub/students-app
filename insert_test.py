import sqlite3
conn = sqlite3.connect("students_web.db")
cur = conn.cursor()
cur.execute(
    "INSERT INTO students(name, uni, year, mid, final, percent, letter, active) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
    ("TEST_USER", "99999", 3, 10, 20, 30, "F", 1)
)
conn.commit()
cur.execute("SELECT id, name FROM students ORDER BY id DESC LIMIT 1")
print("last inserted:", cur.fetchone())
conn.close()
