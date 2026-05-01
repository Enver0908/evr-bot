import os
import sqlite3

import psycopg2
from psycopg2.extras import execute_values


TABLES = [
    {
        "name": "users",
        "columns": [
            "id",
            "email",
            "password_hash",
            "subscription_status",
            "subscription_expires",
            "is_lifetime_member",
            "api_key_encrypted",
            "api_secret_encrypted",
            "created_at",
            "updated_at",
        ],
        "conflict": ["id"],
        "bool_columns": {"is_lifetime_member"},
        "sequence": "id",
    },
    {
        "name": "bot_states",
        "columns": [
            "id",
            "user_id",
            "current_state",
            "eski_zirve_fiyati",
            "breakdown_reference_price",
            "last_evr_value",
            "last_btc_price",
            "last_ma600",
            "last_run_at",
            "shield_pending",
            "updated_at",
        ],
        "conflict": ["id"],
        "bool_columns": {"shield_pending"},
        "sequence": "id",
    },
    {
        "name": "trade_logs",
        "columns": [
            "id",
            "user_id",
            "timestamp",
            "action",
            "execution_status",
            "symbol",
            "side",
            "amount_btc",
            "amount_usdt",
            "price",
            "order_id",
            "client_order_id",
            "evr_value",
            "bot_state_at",
            "note",
        ],
        "conflict": ["id"],
        "bool_columns": set(),
        "sequence": "id",
    },
    {
        "name": "market_data",
        "columns": [
            "id",
            "date_str",
            "btc_price",
            "evr_raw",
            "evr_index",
            "ma_600",
            "created_at",
        ],
        "conflict": ["date_str"],
        "bool_columns": set(),
        "sequence": "id",
    },
    {
        "name": "portfolio_snapshots",
        "columns": [
            "id",
            "user_id",
            "snapshot_date",
            "snapshot_at",
            "btc_amount",
            "usdt_amount",
            "total_equity_usdt",
            "btc_price",
        ],
        "conflict": ["id"],
        "bool_columns": set(),
        "sequence": "id",
    },
]


def sqlite_table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def postgres_table_exists(cursor, table_name: str) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        )
        """,
        (table_name,),
    )
    return bool(cursor.fetchone()[0])


def fetch_sqlite_rows(cursor: sqlite3.Cursor, table: dict) -> list[tuple]:
    table_name = table["name"]
    if not sqlite_table_exists(cursor, table_name):
        print(f"Skip: SQLite table not found -> {table_name}")
        return []

    cols = ", ".join(table["columns"])
    cursor.execute(f"SELECT {cols} FROM {table_name} ORDER BY 1 ASC")
    rows = cursor.fetchall()
    print(f"Fetched {len(rows)} rows from SQLite table '{table_name}'.")
    return [normalize_row(table, row) for row in rows]


def normalize_row(table: dict, row: tuple) -> tuple:
    values = list(row)
    bool_columns = table.get("bool_columns", set())
    if bool_columns:
        for idx, col in enumerate(table["columns"]):
            if col in bool_columns and values[idx] is not None:
                values[idx] = bool(values[idx])
    return tuple(values)


def build_upsert_query(table: dict) -> str:
    table_name = table["name"]
    columns = table["columns"]
    conflict_cols = table["conflict"]
    assignments = ", ".join(
        f"{col} = EXCLUDED.{col}"
        for col in columns
        if col not in conflict_cols
    )
    col_sql = ", ".join(columns)
    conflict_sql = ", ".join(conflict_cols)
    return f"""
        INSERT INTO {table_name} ({col_sql})
        VALUES %s
        ON CONFLICT ({conflict_sql}) DO UPDATE
        SET {assignments};
    """


def reset_sequence(cursor, table_name: str, sequence_column: str) -> None:
    cursor.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table_name}', '{sequence_column}'),
            COALESCE((SELECT MAX({sequence_column}) FROM {table_name}), 1),
            (SELECT COUNT(*) > 0 FROM {table_name})
        )
        """
    )


def copy_table(sqlite_cursor: sqlite3.Cursor, pg_cursor, table: dict) -> None:
    table_name = table["name"]
    if not postgres_table_exists(pg_cursor, table_name):
        raise RuntimeError(
            f"PostgreSQL table '{table_name}' bulunamadi. "
            "Once hedef veritabaninda migration'lari calistirin."
        )

    rows = fetch_sqlite_rows(sqlite_cursor, table)
    if not rows:
        return

    query = build_upsert_query(table)
    execute_values(pg_cursor, query, rows, page_size=500)
    print(f"Upsert OK -> {table_name}: {len(rows)} rows")

    sequence_column = table.get("sequence")
    if sequence_column:
        reset_sequence(pg_cursor, table_name, sequence_column)


def main() -> None:
    print("Starting SQLite -> PostgreSQL migration...")

    pg_url = os.getenv("DATABASE_URL")
    if not pg_url:
        print("Error: DATABASE_URL environment variable is missing.")
        raise SystemExit(1)

    sqlite_db_path = os.getenv("SQLITE_DB_PATH", "evr_bot.db")
    if not os.path.exists(sqlite_db_path):
        print(f"Error: SQLite database not found -> {sqlite_db_path}")
        raise SystemExit(1)

    try:
        pg_conn = psycopg2.connect(pg_url)
        pg_cursor = pg_conn.cursor()
        print("Connected to PostgreSQL successfully.")
    except Exception as exc:
        print(f"Error connecting to PostgreSQL: {exc}")
        raise SystemExit(1)

    try:
        sqlite_conn = sqlite3.connect(sqlite_db_path)
        sqlite_cursor = sqlite_conn.cursor()
        print("Connected to SQLite successfully.")
    except Exception as exc:
        print(f"Error connecting to SQLite: {exc}")
        pg_cursor.close()
        pg_conn.close()
        raise SystemExit(1)

    try:
        for table in TABLES:
            copy_table(sqlite_cursor, pg_cursor, table)
        pg_conn.commit()
        print("Migration completed successfully.")
    except Exception as exc:
        pg_conn.rollback()
        print(f"Migration failed: {exc}")
        raise SystemExit(1)
    finally:
        pg_cursor.close()
        pg_conn.close()
        sqlite_cursor.close()
        sqlite_conn.close()


if __name__ == "__main__":
    main()
