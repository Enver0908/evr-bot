"""
Hafif migration runner.

Amaç:
- create_all() sonrasinda kontrollu, versiyonlu degisiklikler uygulamak
- SQLite ve PostgreSQL ile calismak
- Alembic'e gecmeden once minimum guvenli migration zemini saglamak
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from sqlalchemy import inspect, text


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable


def _ensure_migration_table(connection) -> None:
    dialect = connection.dialect.name
    if dialect == "postgresql":
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name VARCHAR(255) NOT NULL,
                    applied_at TIMESTAMP NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        return

    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )


def _index_exists(connection, table_name: str, index_name: str) -> bool:
    inspector = inspect(connection)
    indexes = inspector.get_indexes(table_name)
    return any(index["name"] == index_name for index in indexes)


def _column_exists(connection, table_name: str, column_name: str) -> bool:
    inspector = inspect(connection)
    columns = inspector.get_columns(table_name)
    return any(column["name"] == column_name for column in columns)


def _create_index_if_missing(connection, table_name: str, index_name: str, columns: str, unique: bool = False) -> None:
    if _index_exists(connection, table_name, index_name):
        return
    unique_str = "UNIQUE " if unique else ""
    connection.execute(text(f"CREATE {unique_str}INDEX IF NOT EXISTS {index_name} ON {table_name} ({columns})"))


def _migration_001_add_trade_log_execution_status(connection) -> None:
    if _column_exists(connection, "trade_logs", "execution_status"):
        return

    connection.execute(
        text(
            """
            ALTER TABLE trade_logs
            ADD COLUMN execution_status VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'
            """
        )
    )


def _migration_002_trade_log_recovery_indexes(connection) -> None:
    _create_index_if_missing(
        connection,
        "trade_logs",
        "ix_trade_logs_execution_status_timestamp",
        "execution_status, timestamp",
    )
    _create_index_if_missing(
        connection,
        "trade_logs",
        "ix_trade_logs_user_execution_status",
        "user_id, execution_status",
    )


def _migration_003_market_data_nullable_evr(connection) -> None:
    if connection.dialect.name != "postgresql":
        return

    if _column_exists(connection, "market_data", "evr_raw"):
        connection.execute(text("ALTER TABLE market_data ALTER COLUMN evr_raw DROP NOT NULL"))
    if _column_exists(connection, "market_data", "evr_index"):
        connection.execute(text("ALTER TABLE market_data ALTER COLUMN evr_index DROP NOT NULL"))


def _migration_004_add_client_order_id(connection) -> None:
    if not _column_exists(connection, "trade_logs", "client_order_id"):
        connection.execute(text("ALTER TABLE trade_logs ADD COLUMN client_order_id VARCHAR(100)"))

    _create_index_if_missing(
        connection,
        "trade_logs",
        "ix_trade_logs_client_order_id",
        "client_order_id",
        unique=True
    )
def _migration_005_ensure_client_order_id_unique(connection) -> None:
    # Versiyon 4 uzerinde sonradan yapilan index guncellemesinin
    # eski kurulumlara da tasinmasini garanti altina almak icin:
    _create_index_if_missing(
        connection,
        "trade_logs",
        "ix_trade_logs_client_order_id",
        "client_order_id",
        unique=True
    )


def _migration_006_add_lifetime_membership(connection) -> None:
    if _column_exists(connection, "users", "is_lifetime_member"):
        return

    connection.execute(
        text(
            """
            ALTER TABLE users
            ADD COLUMN is_lifetime_member BOOLEAN NOT NULL DEFAULT FALSE
            """
        )
    )

def _migration_007_create_portfolio_snapshots(connection) -> None:
    """portfolio_snapshots tablosu ve unique constraint'i garanti et."""
    # create_all() zaten tabloyu olusturur; burada sadece
    # unique index'in varligini garanti altina aliyoruz.
    _create_index_if_missing(
        connection,
        "portfolio_snapshots",
        "uq_portfolio_user_date",
        "user_id, snapshot_date",
        unique=True,
    )


def _migration_008_backfill_lifetime_members(connection) -> None:
    # Sadece is_lifetime_member'ı güncelle; subscription_status'a dokunma
    # PostgreSQL CHECK constraint (subscription_status_enum) uyumsuzluğunu önler
    connection.execute(
        text(
            """
            UPDATE users
            SET is_lifetime_member = TRUE
            WHERE lower(email) IN ('olkuenver@gmail.com', 'talha@gmail.com')
              AND is_lifetime_member IS NOT TRUE
            """
        )
    )


def _migration_009_add_shield_pending(connection) -> None:
    """bot_states tablosuna shield_pending alanini ekle."""
    if _column_exists(connection, "bot_states", "shield_pending"):
        return

    connection.execute(
        text(
            """
            ALTER TABLE bot_states
            ADD COLUMN shield_pending BOOLEAN NOT NULL DEFAULT FALSE
            """
        )
    )


def _migration_010_backfill_lifetime_members_from_env(connection) -> None:
    """Config'deki omur boyu uyeleri mevcut kullanicilar icin backfill et."""
    from evr_bot.config import LIFETIME_MEMBER_EMAILS

    emails = sorted({email.strip().lower() for email in LIFETIME_MEMBER_EMAILS if email.strip()})
    if not emails:
        return

    placeholders = ", ".join(f":email_{idx}" for idx in range(len(emails)))
    params = {f"email_{idx}": email for idx, email in enumerate(emails)}
    connection.execute(
        text(
            f"""
            UPDATE users
            SET is_lifetime_member = TRUE
            WHERE lower(email) IN ({placeholders})
              AND is_lifetime_member IS NOT TRUE
            """
        ),
        params,
    )


def _migration_011_trade_log_query_indexes(connection) -> None:
    """Dashboard, portfolio ve recovery sorgulari icin composite index'ler."""
    _create_index_if_missing(
        connection,
        "trade_logs",
        "ix_trade_logs_user_execution_status_timestamp",
        "user_id, execution_status, timestamp",
    )
    _create_index_if_missing(
        connection,
        "trade_logs",
        "ix_trade_logs_user_timestamp",
        "user_id, timestamp",
    )


def _migration_012_users_email_lower_index(connection) -> None:
    """lower(email) filtrelerini hizlandiran fonksiyonel index."""
    connection.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_users_email_lower
            ON users (lower(email))
            """
        )
    )


MIGRATIONS = [
    Migration(
        version=1,
        name="add_trade_log_execution_status",
        apply=_migration_001_add_trade_log_execution_status,
    ),
    Migration(
        version=2,
        name="trade_log_recovery_indexes",
        apply=_migration_002_trade_log_recovery_indexes,
    ),
    Migration(
        version=3,
        name="market_data_nullable_evr",
        apply=_migration_003_market_data_nullable_evr,
    ),
    Migration(
        version=4,
        name="add_client_order_id",
        apply=_migration_004_add_client_order_id,
    ),
    Migration(
        version=5,
        name="ensure_client_order_id_unique",
        apply=_migration_005_ensure_client_order_id_unique,
    ),
    Migration(
        version=6,
        name="add_lifetime_membership",
        apply=_migration_006_add_lifetime_membership,
    ),
    Migration(
        version=7,
        name="create_portfolio_snapshots",
        apply=_migration_007_create_portfolio_snapshots,
    ),
    Migration(
        version=8,
        name="backfill_lifetime_members",
        apply=_migration_008_backfill_lifetime_members,
    ),
    Migration(
        version=9,
        name="add_shield_pending",
        apply=_migration_009_add_shield_pending,
    ),
    Migration(
        version=10,
        name="backfill_lifetime_members_from_env",
        apply=_migration_010_backfill_lifetime_members_from_env,
    ),
    Migration(
        version=11,
        name="trade_log_query_indexes",
        apply=_migration_011_trade_log_query_indexes,
    ),
    Migration(
        version=12,
        name="users_email_lower_index",
        apply=_migration_012_users_email_lower_index,
    ),
]


def run_migrations(engine) -> None:
    """Tum bekleyen migration'lari sirayla uygula."""
    with engine.begin() as connection:
        dialect = connection.dialect.name
        if dialect == "postgresql":
            # Race condition'i onlemek icin global transaction kilidi
            connection.execute(text("SELECT pg_advisory_xact_lock(hashtext('evr_migrations'))"))
            
        from evr_bot.models import Base
        Base.metadata.create_all(bind=connection)
        
        _ensure_migration_table(connection)
        applied_versions = {
            row[0]
            for row in connection.execute(text("SELECT version FROM schema_migrations"))
        }

        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                continue

            migration.apply(connection)
            if dialect == "postgresql":
                connection.execute(
                    text(
                        """
                        INSERT INTO schema_migrations (version, name)
                        VALUES (:version, :name)
                        ON CONFLICT (version) DO NOTHING
                        """
                    ),
                    {"version": migration.version, "name": migration.name},
                )
            else:
                connection.execute(
                    text(
                        """
                        INSERT OR IGNORE INTO schema_migrations (version, name)
                        VALUES (:version, :name)
                        """
                    ),
                    {"version": migration.version, "name": migration.name},
                )


def main() -> None:
    from evr_bot.database import engine

    run_migrations(engine)
    print("Migrations tamamlandi.")


if __name__ == "__main__":
    main()
