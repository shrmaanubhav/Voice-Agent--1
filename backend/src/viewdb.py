import sqlite3
import os

DB_FILE = "transactions.sqlite"
REPORT_FILE = "db_report.md" # New file to store the readable output

def display_database_content():
    """
    Connects to the SQLite database, queries all transactions, formats
    the result as a Markdown table, and saves it to a file.
    """
    if not os.path.exists(DB_FILE):
        print(f"❌ Error: Database file '{DB_FILE}' not found.")
        print("Please run 'create_db.py' first to initialize the database.")
        return

    conn = None
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Query all records
        cursor.execute("SELECT * FROM transactions;")
        rows = cursor.fetchall()

        if not rows:
            print("The 'transactions' table is empty.")
            return

        # Get column names (headers)
        headers = [description[0] for description in cursor.description]
        
        # Start building the report content string
        report_content = f"## Current Fraud Case Status Report\n\n"
        report_content += f"**Database File:** `{DB_FILE}`\n"
        report_content += f"**Time Generated:** {os.path.getmtime(DB_FILE)}\n\n"
        
        # --- Build Markdown Table ---
        
        # 1. Header Row
        report_content += "| " + " | ".join(headers) + " |\n"
        
        # 2. Separator Row
        separators = ["---" for _ in headers]
        report_content += "| " + " | ".join(separators) + " |\n"
        
        # 3. Data Rows
        for row in rows:
            # Convert all elements to string before joining
            row_str = [str(col) for col in row]
            report_content += "| " + " | ".join(row_str) + " |\n"
        
        # --- Write content to file ---
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(report_content)
        
        print("\n" + "=" * 60)
        print(f"✅ Success! Database content saved to {REPORT_FILE}")
        print("Run this script again to see the latest updates in the file.")
        print("=" * 60 + "\n")


    except sqlite3.Error as e:
        print(f"An error occurred while accessing the database: {e}")
    except IOError as e:
        print(f"An error occurred while writing the file: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    display_database_content()