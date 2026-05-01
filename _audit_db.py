import json
from sqlalchemy import inspect, text
from evr_bot.database import engine

def main():
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    print("=== TABLES ===")
    print(json.dumps(tables, indent=2))
    
    with engine.connect() as conn:
        for t in tables:
            cnt = conn.execute(text(f"SELECT count(*) FROM {t}")).scalar()
            cols = inspector.get_columns(t)
            print(f"\n=== {t} ({cnt} rows) ===")
            for col in cols:
                nullable_str = not col.get('nullable', True)
                print(f"  {col['name']}: {col['type']} | NOT_NULL={nullable_str} | DEFAULT={col.get('default')}")
            
            indexes = inspector.get_indexes(t)
            if indexes:
                print(f"  -- Indexes:")
                for idx in indexes:
                    print(f"     {idx['name']} (unique={idx['unique']})")

        print("\n=== SCHEMA_MIGRATIONS ===")
        if "schema_migrations" in tables:
            rows = conn.execute(text("SELECT version, name, applied_at FROM schema_migrations ORDER BY version")).fetchall()
            for r in rows:
                print(f"  v{r[0]}: {r[1]} ({r[2]})")
        else:
            print("  (table not found)")

        if "users" in tables:
            print("\n=== USERS ===")
            rows = conn.execute(text("SELECT id, email, subscription_status, is_lifetime_member, api_key_encrypted IS NOT NULL, created_at FROM users")).fetchall()
            for r in rows:
                print(f"  ID={r[0]} | {r[1]} | sub={r[2]} | lifetime={r[3]} | has_key={r[4]} | created={r[5]}")

        if "bot_states" in tables:
            print("\n=== BOT_STATES ===")
            rows = conn.execute(text("SELECT id, user_id, current_state, eski_zirve_fiyati, breakdown_reference_price, last_evr_value, last_btc_price, last_ma600, last_run_at, shield_pending FROM bot_states")).fetchall()
            for r in rows:
                print(f"  {r}")

        if "market_data" in tables:
            total = conn.execute(text("SELECT count(*) FROM market_data")).scalar()
            null_evr = conn.execute(text("SELECT count(*) FROM market_data WHERE evr_raw IS NULL")).scalar()
            null_ma = conn.execute(text("SELECT count(*) FROM market_data WHERE ma_600 IS NULL")).scalar()
            dt_range = conn.execute(text("SELECT min(date_str), max(date_str) FROM market_data")).fetchone()
            
            print(f"\n=== MARKET_DATA ({total} rows) ===")
            print(f"  Range: {dt_range[0]} to {dt_range[1]}")
            print(f"  NULL evr_raw: {null_evr} | NULL ma_600: {null_ma}")

            print("\n  -- Last 5:")
            for r in conn.execute(text("SELECT date_str, btc_price, evr_raw, evr_index, ma_600 FROM market_data ORDER BY date_str DESC LIMIT 5")).fetchall():
                print(f"     {r}")

            print("  -- First 3:")
            for r in conn.execute(text("SELECT date_str, btc_price, evr_raw, evr_index, ma_600 FROM market_data ORDER BY date_str ASC LIMIT 3")).fetchall():
                print(f"     {r}")

        if "trade_logs" in tables:
            print("\n=== TRADE_LOGS ===")
            tl_cnt = conn.execute(text("SELECT count(*) FROM trade_logs")).scalar()
            print(f"  Total: {tl_cnt}")
            if tl_cnt > 0:
                print("  -- Last 10:")
                for r in conn.execute(text("SELECT id, user_id, timestamp, action, execution_status, amount_btc, price FROM trade_logs ORDER BY timestamp DESC LIMIT 10")).fetchall():
                    print(f"     {r}")

        if "portfolio_snapshots" in tables:
            print("\n=== PORTFOLIO_SNAPSHOTS ===")
            ps_cnt = conn.execute(text("SELECT count(*) FROM portfolio_snapshots")).scalar()
            print(f"  Total: {ps_cnt}")
            if ps_cnt > 0:
                print("  -- Last 5:")
                for r in conn.execute(text("SELECT id, user_id, snapshot_date, btc_amount, usdt_amount, total_equity_usdt, btc_price FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 5")).fetchall():
                    print(f"     {r}")

        print("\n=== INTEGRITY CHECKS ===")
        if "bot_states" in tables and "users" in tables:
            o_bs = conn.execute(text("SELECT count(*) FROM bot_states bs LEFT JOIN users u ON bs.user_id = u.id WHERE u.id IS NULL")).scalar()
            print(f"  Orphan bot_states: {o_bs}")
            
        if "trade_logs" in tables and "users" in tables:
            o_tl = conn.execute(text("SELECT count(*) FROM trade_logs tl LEFT JOIN users u ON tl.user_id = u.id WHERE u.id IS NULL")).scalar()
            print(f"  Orphan trade_logs: {o_tl}")
            
        if "portfolio_snapshots" in tables and "users" in tables:
            o_ps = conn.execute(text("SELECT count(*) FROM portfolio_snapshots ps LEFT JOIN users u ON ps.user_id = u.id WHERE u.id IS NULL")).scalar()
            print(f"  Orphan portfolio_snapshots: {o_ps}")

        if "market_data" in tables:
            dupes = conn.execute(text("SELECT date_str, count(*) as cnt FROM market_data GROUP BY date_str HAVING count(*) > 1")).fetchall()
            print(f"  Duplicate market_data dates: {len(dupes)}")

        if "trade_logs" in tables:
            pending = conn.execute(text("SELECT count(*) FROM trade_logs WHERE execution_status = 'PENDING'")).scalar()
            print(f"  PENDING trade_logs: {pending}")

if __name__ == '__main__':
    main()
