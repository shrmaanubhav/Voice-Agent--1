import sqlite3
import os
import json # Import the json library for data formatting

DB_FILE = 'transactions.sqlite' # Changed file extension to .sqlite

# --- 1. Clean up and setup ---

# Remove the file if it exists to ensure a fresh start
if os.path.exists(DB_FILE):
    os.remove(DB_FILE)
    print(f"Removed existing database file: {DB_FILE}")

# Connect to the SQLite database (creates the file if it doesn't exist)
conn = sqlite3.connect(DB_FILE)
cursor = conn.cursor()
print(f"Created a new database file: {DB_FILE}")

# --- 2. Define the Table Structure (DDL) ---

# The combined columns from your images are used to create the 'transactions' table.
# We infer appropriate SQLite data types (INTEGER, TEXT, REAL).
try:
    cursor.execute("""
    CREATE TABLE transactions (
        id INTEGER PRIMARY KEY,
        userName TEXT NOT NULL,
        securityId TEXT,       -- Stored as TEXT to preserve leading zeros if any
        cardEnding TEXT,       -- Stored as TEXT
        transactionDescription TEXT NOT NULL,
        transactionAmount REAL NOT NULL, -- REAL for currency values
        transactionTime TEXT,
        transactionWebsite TEXT,
        case_status TEXT,
        notes TEXT
    );
    """)
    print("Table 'transactions' created successfully.")
except sqlite3.Error as e:
    print(f"An error occurred during table creation: {e}")
    conn.close()
    exit()

# --- 3. Insert the Data (DML) ---

# Data extracted row by row from the uploaded images
transaction_data = [
    (1, 'Alice', '11122', '4521', 'Starbucks Coffee', 25.50, '8:30 AM EST', 'starbucks.com', 'confirmed_safe', 'User check complete'),
    (2, 'Bob', '22334', '3345', 'Apple Store', 1200.00, '2:45 PM EST', 'apple.com', 'confirmed_fraud', 'User initiated chargeback'),
    (3, 'James', '33445', '6677', 'Walmart ', 340.75, '10:15 AM EST', 'walmart.com', 'pending_review', 'Automated flag: High value'),
    (4, 'Mathews', '44556', '8899', 'Netflix Subscription', 15.99, '11:00 PM EST', 'netflix.com', 'pending_review', 'Automated flag: International'),
    (5, 'Jhon', '55667', '1122', 'Amazon Purchase', 85.99, '6:20 PM EST', 'amazon.com', 'pending_review', 'Automated flag: High frequency'),
]

try:
    cursor.executemany("""
    INSERT INTO transactions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, transaction_data)
    conn.commit()
    print("5 rows of data inserted successfully.")
except sqlite3.Error as e:
    print(f"An error occurred during data insertion: {e}")
    conn.close()
    exit()

# --- 4. Function to Extract and Format Data for Voice Agent ---

def get_all_transactions_as_json(cursor):
    """
    Queries all transactions and returns the data formatted as a JSON string.
    This is the ideal format to feed into a structured AI/Voice agent.
    """
    cursor.execute("SELECT * FROM transactions")
    # Get column names for use as keys in the resulting dictionary
    column_names = [description[0] for description in cursor.description]
    
    records = []
    for row in cursor.fetchall():
        # Create a dictionary for each row using column names as keys
        record = dict(zip(column_names, row))
        records.append(record)
        
    return json.dumps(records, indent=4)

# --- 5. Verification Query and JSON Output ---

print("\n--- Verification: Data Check ---")
cursor.execute("SELECT id, userName, transactionAmount, case_status FROM transactions LIMIT 5;")
rows = cursor.fetchall()
for row in rows:
    print(row)
print("---------------------------------")

print("\n--- AI/Voice Agent Input (JSON Format) ---")
json_output = get_all_transactions_as_json(cursor)
print(json_output)
print("-----------------------------------------")


# Close the connection
conn.close()
print(f"\nDatabase setup complete. The file '{DB_FILE}' is ready.")