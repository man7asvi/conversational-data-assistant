import sqlite3

def init_db():
    conn=sqlite3.connect("sales.db")
    cursor=conn.cursor()

# Create Sales table
    cursor.execute("""

    CREATE TABLE IF NOT EXISTS sales(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    region TEXT NOT NULL, 
    product TEXT NOT NULL, 
    amount REAL NOT NULL
    )
    """)

    # Insert some fake sales data
    cursor.executemany("""
    INSERT INTO sales (date, region, product, amount)
    VALUES (?,?,?,?)
    """,
    [
    ("2026-01-15", "NY", "Laptop", 1200),
    ("2026-01-20", "LA", "Phone", 800),
    ("2026-02-10", "NY", "Tablet", 600),
    ("2026-02-15", "CH", "Laptop", 1500),
    ("2026-03-01", "LA", "Phone", 950),
    ("2026-03-10", "NY", "Laptop", 1100),
    ("2026-03-15", "CH", "Tablet", 700),
    ("2026-03-20", "LA", "Laptop", 1300),
    ])

    conn.commit()
    conn.close()
    print("Database initialized successfully!")

if __name__ == '__main__':
    init_db()
