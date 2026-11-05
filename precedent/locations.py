"""Physical location per drive (datacenter / cluster / vault / pod / slot) from the Backblaze zips.

Locations are stable, so we read one day per week plus every day a drive failed, keeping each
serial's latest row. Usage: python -m precedent.locations data/raw/data_Q1_2026.zip data/raw/data_Q2_2026.zip
"""
import os
import sys
import tempfile
import zipfile

import duckdb

from precedent.config import DATA, DB_PATH

OUT = os.path.join(DATA, "locations.parquet")


def build(zips: list) -> None:
    con = duckdb.connect(DB_PATH, read_only=True)
    fail_days = {str(d[0]) for d in con.execute("SELECT DISTINCT failed_on FROM drives WHERE failed_on IS NOT NULL").fetchall()}
    con.close()
    parts = []
    with tempfile.TemporaryDirectory() as tmp:
        for path in zips:
            with zipfile.ZipFile(path) as z:
                members = sorted(m for m in z.namelist() if m.endswith(".csv") and "__MACOSX" not in m)
                for i, m in enumerate(members):
                    day = os.path.basename(m)[:-4]
                    if not (i % 7 == 0 or i == len(members) - 1 or day in fail_days):
                        continue
                    src = z.extract(m, tmp)
                    part = os.path.join(tmp, f"{day}.parquet")
                    duckdb.execute(f"""
                        COPY (SELECT CAST(date AS DATE) AS date, serial_number AS serial, datacenter, cluster_id,
                                     vault_id, pod_id, pod_slot_num
                              FROM read_csv('{src}', all_varchar=true, header=true)) TO '{part}' (FORMAT parquet)
                    """)
                    os.remove(src)
                    parts.append(part)
            print(f"{path}: {len(parts)} days sampled", flush=True)
        duckdb.execute(f"""
            COPY (SELECT serial, arg_max(datacenter, date) AS datacenter, arg_max(cluster_id, date) AS cluster_id,
                         arg_max(vault_id, date) AS vault_id, arg_max(pod_id, date) AS pod_id,
                         arg_max(pod_slot_num, date) AS pod_slot_num
                  FROM read_parquet({parts!r}) GROUP BY serial) TO '{OUT}' (FORMAT parquet)
        """)
    print("wrote", OUT, duckdb.execute(f"SELECT count(*) FROM '{OUT}'").fetchone())


if __name__ == "__main__":
    build(sys.argv[1:])
