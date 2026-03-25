# precompute.py
import os

# 1. FORCE Development Mode (Must be before importing app)
os.environ["ENV_MODE"] = "development"

# 2. Import your logic
from app import run_full_pipeline, app_state
from src.ingest import SUPPORTED_ASINS

def main():
    print(f"🚀 Starting bulk precompute for {len(SUPPORTED_ASINS)} ASINs...")
    
    # 3. MANUALLY Initialize app_state
    # This fixes the 'supported_asins' KeyError because we aren't running via 'fastapi dev'
    app_state["supported_asins"] = SUPPORTED_ASINS
    app_state["cache"] = {}

    for asin, name in SUPPORTED_ASINS.items():
        print(f"\n📦 Processing: {name} ({asin})")
        try:
            # Now this will trigger the local NLP pipeline instead of bailing out
            run_full_pipeline(asin)
            print(f"✅ Successfully cached {asin}")
        except Exception as e:
            print(f"❌ Failed to process {asin}: {e}")

    print("\n✨ All precomputed data is ready in data/processed/")

if __name__ == "__main__":
    main()