from sqlalchemy import inspect, text
from evr_bot.database import engine

def main():
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    with engine.connect() as conn:
        if "trade_logs" in tables:
            pending = conn.execute(text("SELECT count(*) FROM trade_logs WHERE execution_status = 'PENDING'")).scalar()
            print(f"PENDING trade_logs: {pending}")

        if "users" in tables and "bot_states" in tables:
            no_bs = conn.execute(text("SELECT u.id, u.email FROM users u LEFT JOIN bot_states bs ON u.id = bs.user_id WHERE bs.id IS NULL")).fetchall()
            print(f"Users without bot_state: {len(no_bs)}")

            active_non_lifetime = conn.execute(text("SELECT id, email, subscription_status, subscription_expires FROM users WHERE subscription_status = 'ACTIVE' AND is_lifetime_member = false")).fetchall()
            for r in active_non_lifetime:
                print(f"Active non-lifetime: ID={r[0]} {r[1]} expires={r[3]}")

        if "schema_migrations" in tables:
            versions = [r[0] for r in conn.execute(text("SELECT version FROM schema_migrations ORDER BY version")).fetchall()]
            print(f"Migration versions: {versions}")
            missing = [v for v in range(1, 13) if v not in versions]
            print(f"Missing migrations: {missing}")

        if "bot_states" in tables:
            cols = [c['name'] for c in inspector.get_columns('bot_states')]
            print(f"bot_states columns: {cols}")

        if "market_data" in tables:
            null_2021 = conn.execute(text("SELECT count(*) FROM market_data WHERE evr_raw IS NULL AND date_str >= '2021-05-01'")).scalar()
            print(f"NULL evr_raw since 2021-05-01: {null_2021}")

            null_2024 = conn.execute(text("SELECT count(*) FROM market_data WHERE evr_raw IS NULL AND date_str >= '2024-01-01'")).scalar()
            print(f"NULL evr_raw since 2024-01-01: {null_2024}")

            recent_nulls = [r[0] for r in conn.execute(text("SELECT date_str FROM market_data WHERE evr_raw IS NULL AND date_str >= '2024-01-01' ORDER BY date_str DESC LIMIT 10")).fetchall()]
            print(f"Recent NULL evr dates: {recent_nulls}")

            ma600_pop = conn.execute(text("SELECT count(*) FROM market_data WHERE ma_600 IS NOT NULL")).scalar()
            print(f"MA600 populated: {ma600_pop}")
            
            ma600_start = conn.execute(text("SELECT min(date_str) FROM market_data WHERE ma_600 IS NOT NULL")).scalar()
            print(f"MA600 starts from: {ma600_start}")

            dates = [r[0] for r in conn.execute(text("SELECT date_str FROM market_data WHERE date_str >= '2026-03-01' ORDER BY date_str ASC")).fetchall()]
            from datetime import datetime
            gaps = []
            for i in range(1, len(dates)):
                d1 = datetime.strptime(dates[i-1], "%Y-%m-%d")
                d2 = datetime.strptime(dates[i], "%Y-%m-%d")
                if (d2 - d1).days > 1:
                    gaps.append(f"{dates[i-1]} -> {dates[i]} ({(d2-d1).days} days)")
            print(f"Date gaps (since 2026-03-01): {gaps if gaps else 'None'}")

if __name__ == '__main__':
    main()
