import logging
from evr_bot.database import SessionLocal
from evr_bot.models import MarketData
from evr_scraper import scrape

logging.basicConfig(level=logging.INFO)

def run_oneoff():
    db = SessionLocal()
    print("Fetching last 30 days of EVR data...")
    records = scrape(headless=True, last_n_days=30)
    
    if records:
        updated = 0
        for rec in records:
            d = rec["date"]
            evr_val = int(rec["evr_value"])
            row = db.query(MarketData).filter(MarketData.date_str == d).first()
            if row and row.evr_raw is None:
                row.evr_raw = evr_val
                row.evr_index = round(evr_val / 10.0, 1)
                print(f"Updated {d} with EVR {evr_val}")
                updated += 1
            elif row:
                # Also update if it already exists, just to ensure consistency
                row.evr_raw = evr_val
                row.evr_index = round(evr_val / 10.0, 1)
        
        db.commit()
        print(f"Done! Evaluated {len(records)} records, filled {updated} previously missing EVR rows.")
    else:
        print("No records found or scrape failed.")

if __name__ == "__main__":
    run_oneoff()
