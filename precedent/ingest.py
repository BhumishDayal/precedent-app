"""Stream Backblaze quarterly zips into one slim parquet: one row per drive per day.

Usage: python -m precedent.ingest data/raw/data_Q1_2026.zip data/raw/data_Q2_2026.zip
"""
import os
import sys
import tempfile
import zipfile

import duckdb

from precedent.config import DAILY_DIR, SMART_ATTRS


def ingest_zip(path: str) -> None:
    os.makedirs(DAILY_DIR, exist_ok=True)
    con = duckdb.connect()
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        members = sorted(m for m in z.namelist() if m.endswith(".csv") and "__MACOSX" not in m)
        for i, m in enumerate(members):
            day = os.path.basename(m)[:-4]
            out = os.path.join(DAILY_DIR, f"{day}.parquet")
            if os.path.exists(out):
                continue
            src = z.extract(m, tmp)
            smart = ", ".join(f"TRY_CAST(smart_{a}_raw AS BIGINT) AS s{a}" for a in SMART_ATTRS)
            con.execute(f"""
                COPY (
                  SELECT CAST(date AS DATE) AS date, serial_number AS serial, model,
                         CAST(failure AS INTEGER) AS failure, {smart}
                  FROM read_csv('{src}', all_varchar=true, header=true)
                ) TO '{out}' (FORMAT parquet)
            """)
            os.remove(src)
            if i % 10 == 0:
                print(f"{path}: {i + 1}/{len(members)} {day}", flush=True)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        ingest_zip(p)
    print("done")
