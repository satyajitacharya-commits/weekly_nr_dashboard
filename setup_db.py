import sqlite3

# 1. Create a new database file in your folder called 'finance_data.db'
conn = sqlite3.connect('finance_data.db')
cursor = conn.cursor()

# 2. Create the table for your "1-Times" manual inputs
cursor.execute('''
CREATE TABLE IF NOT EXISTS manual_one_times (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT,
    year TEXT,
    product TEXT,
    adjustment_amount REAL,
    comment TEXT
)
''')

# 3. Create the table for your "ACT=FCST OVERRIDE" checkboxes
cursor.execute('''
CREATE TABLE IF NOT EXISTS user_overrides (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT,
    product TEXT,
    act_equals_fcst_flag BOOLEAN
)
''')

# Save and close
conn.commit()
conn.close()

print("Database and tables created successfully!")
