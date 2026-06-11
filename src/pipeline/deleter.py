from pathlib import Path

BASE = Path(__file__).resolve().parents[2]   # project root
price_dir = BASE / "data" / "raw" / "price"
options_dir = BASE / "data" / "raw" / "options"

for folder in [price_dir, options_dir]:
    for file in folder.glob("*.csv"):
        file.unlink()

print("Deleted all CSV files from price and options.")
