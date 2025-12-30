from sqlalchemy import create_engine, text
import sys
import os

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import DATABASE_URL

def add_column():
    print(f"Connecting to: {DATABASE_URL}")
    if DATABASE_URL.startswith("sqlite"):
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    else:
        engine = create_engine(DATABASE_URL)
    
    # Check if column exists first (naive check)
    try:
        with engine.connect() as conn:
            # Try to select the column
            try:
                conn.execute(text("SELECT scale_category FROM companies LIMIT 1"))
                print("Column 'scale_category' already exists.")
                return
            except Exception:
                print("Column 'scale_category' does not exist. Adding it...")

            # Add column
            # Syntax depends on DB type, but ADD COLUMN is standard
            # SQLite supports ADD COLUMN
            conn.execute(text("ALTER TABLE companies ADD COLUMN scale_category VARCHAR"))
            print("Successfully added column 'scale_category'.")
            
    except Exception as e:
        print(f"Error adding column: {e}")

if __name__ == "__main__":
    add_column()
