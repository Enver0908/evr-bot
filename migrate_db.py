import os
import sqlite3
import psycopg2
from psycopg2.extras import execute_values
import urllib.parse

print("Starting migration process...")

# PostgreSQL baglanti URL'sini al
pg_url = os.getenv("DATABASE_URL")
if not pg_url:
    print("Error: DATABASE_URL environment variable is missing.")
    exit(1)

# PostgreSQL veritabanina baglan
try:
    pg_conn = psycopg2.connect(pg_url)
    pg_cursor = pg_conn.cursor()
    print("Connected to PostgreSQL successfully.")
except Exception as e:
    print(f"Error connecting to PostgreSQL: {e}")
    exit(1)

# SQLite veritabanina baglan
sqlite_db_path = "evr_bot.db"
if not os.path.exists(sqlite_db_path):
    print(f"Error: {sqlite_db_path} not found.")
    exit(1)

try:
    sqlite_conn = sqlite3.connect(sqlite_db_path)
    sqlite_cursor = sqlite_conn.cursor()
    print("Connected to SQLite successfully.")
except Exception as e:
    print(f"Error connecting to SQLite: {e}")
    exit(1)

# SQLite'tan market_data tablosunu oku
try:
    sqlite_cursor.execute("SELECT date_str, btc_price, evr_raw, evr_index, ma_600, created_at FROM market_data ORDER BY date_str ASC")
    rows = sqlite_cursor.fetchall()
    print(f"Fetched {len(rows)} rows from SQLite market_data table.")
except Exception as e:
    print(f"Error fetching data from SQLite: {e}")
    exit(1)

# PostgreSQL'e yaz (ON CONFLICT DO NOTHING ile cakisani atla)
if rows:
    try:
        # PostgreSQL tablosunun mevcut oldugundan emin olalim (uygulama baslarken zaten create_all yapiliyor)
        insert_query = """
            INSERT INTO market_data (date_str, btc_price, evr_raw, evr_index, ma_600, created_at)
            VALUES %s
            ON CONFLICT (date_str) DO NOTHING;
        """
        execute_values(pg_cursor, insert_query, rows)
        pg_conn.commit()
        print("Data successfully inserted/upserted into PostgreSQL.")
        
        # Kac satir oldugunu kontrol edelim
        pg_cursor.execute("SELECT COUNT(*) FROM market_data;")
        count = pg_cursor.fetchone()[0]
        print(f"PostgreSQL market_data now has {count} rows.")
        
    except Exception as e:
        print(f"Error inserting data to PostgreSQL: {e}")
        pg_conn.rollback()
else:
    print("No data found in SQLite to migrate.")

# Baglantilari kapat
pg_cursor.close()
pg_conn.close()
sqlite_cursor.close()
sqlite_conn.close()

print("Migration completed.")
