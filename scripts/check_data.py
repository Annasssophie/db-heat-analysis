"""Check that all input data for the heat x long-distance delay analysis is present.

Run from the repository root:
    python scripts/check_data.py            # looks in ./data
    python scripts/check_data.py path/to/data

It searches the data folder recursively (file names, not folder layout, matter)
and prints a checklist. Nothing is modified.

Needs: pandas, duckdb, xarray, netCDF4 (pip install pandas duckdb xarray netCDF4)
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

YEARS = [2022, 2023, 2024, 2025]
MONTHS = [6, 7, 8]
DAYS_JJA = 92            # June 30 + July 31 + August 31
HOURS_JJA = DAYS_JJA * 24

TRAIN_COLUMNS = [
    "trip_id", "time_schedule", "time_real", "delay", "is_final", "is_arrival",
    "is_cancelled", "is_regional", "category", "stop_id", "lat", "lon",
    "stop_sequence", "distance_traveled", "is_betriebshalt", "message_codes",
]

# ERA5 short names as they appear in CDS NetCDF downloads
ERA5_VARS = {
    "t2m": "2m temperature",
    "ssrd": "surface solar radiation downwards",
    "fg10": "10m wind gust since previous post-processing",
    "tp": "total precipitation",
}
ERA5_OPTIONAL = {"mx2t": "maximum 2m temperature since previous post-processing"}

results: list[tuple[str, str, str]] = []   # (status, item, detail)


def report(ok: bool | None, item: str, detail: str = "") -> None:
    status = {True: "OK     ", False: "MISSING", None: "CHECK  "}[ok]
    results.append((status, item, detail))


def find(root: Path, *patterns: str) -> list[Path]:
    out: set[Path] = set()
    for pat in patterns:
        out.update(p for p in root.rglob(pat) if p.is_file())
    return sorted(out)


# --------------------------------------------------------------------------- #
# 1. Train data (Bahn-Vorhersage tabular export, Parquet)
# --------------------------------------------------------------------------- #
def check_train(root: Path) -> None:
    files = find(root, "*.parquet")
    if not files:
        report(False, "Train data (Parquet)", "no .parquet files found")
        return
    report(True, "Train data (Parquet)", f"{len(files)} files")

    import duckdb

    con = duckdb.connect()
    glob = [str(f) for f in files]
    cols = con.execute(
        "SELECT column_name FROM (DESCRIBE SELECT * FROM read_parquet(?, union_by_name=true))",
        [glob],
    ).fetchall()
    cols = {c[0] for c in cols}
    missing = [c for c in TRAIN_COLUMNS if c not in cols]
    report(not missing, "Train data: expected columns",
           "all present" if not missing else "missing: " + ", ".join(missing))
    if "time_schedule" not in cols:
        return

    # Days covered per summer, using local (Berlin) scheduled time.
    # Long-distance only, if the flag exists.
    ld = "WHERE NOT is_regional" if "is_regional" in cols else ""
    rows = con.execute(f"""
        WITH ev AS (
            SELECT timezone('Europe/Berlin', time_schedule::TIMESTAMPTZ) AS t
            FROM read_parquet(?, union_by_name=true)
            {ld}
        )
        SELECT year(t) AS y, count(DISTINCT CAST(t AS DATE)) AS days, count(*) AS n
        FROM ev
        WHERE month(t) IN (6, 7, 8)
        GROUP BY 1 ORDER BY 1
    """, [glob]).fetchall()
    found = {r[0]: (r[1], r[2]) for r in rows}
    for y in YEARS:
        if y not in found:
            report(False, f"Train data {y} Jun-Aug", "no events")
        else:
            days, n = found[y]
            report(days == DAYS_JJA, f"Train data {y} Jun-Aug",
                   f"{days}/{DAYS_JJA} days, {n:,} long-distance events")


# --------------------------------------------------------------------------- #
# 2. HYRAS-DE daily Tmax
# --------------------------------------------------------------------------- #
def check_hyras(root: Path) -> None:
    import xarray as xr

    for y in YEARS:
        hits = find(root, f"tasmax_hyras_1_{y}_*.nc")
        if not hits:
            report(False, f"HYRAS tasmax {y}", "file not found")
            continue
        f = hits[0]
        note = "" if "v6-1" in f.name else " (not v6-1: use the same version for all years)"
        try:
            with xr.open_dataset(f) as ds:
                n = ds.sizes.get("time", 0)
            expected = 366 if y % 4 == 0 else 365
            report(n == expected and not note, f"HYRAS tasmax {y}",
                   f"{f.name}: {n}/{expected} days{note}")
        except Exception as e:  # noqa: BLE001
            report(False, f"HYRAS tasmax {y}", f"{f.name}: cannot open ({e})")
        if len(hits) > 1:
            report(None, f"HYRAS tasmax {y}", "several versions found: " +
                   ", ".join(h.name for h in hits))


# --------------------------------------------------------------------------- #
# 3. ERA5 hourly (single levels)
# --------------------------------------------------------------------------- #
def check_era5(root: Path) -> None:
    import xarray as xr

    zips = find(root, "*.zip")
    for z in zips:
        try:
            if any(n.endswith(".nc") for n in zipfile.ZipFile(z).namelist()):
                report(None, "ERA5 zip archive", f"{z.name} contains .nc files: unzip it first")
        except zipfile.BadZipFile:
            pass

    ncs = [f for f in find(root, "*.nc") if not f.name.startswith("tasmax_hyras")]
    if not ncs:
        report(False, "ERA5 NetCDF files", "none found")
        return

    # hours[var][year] = set of timestamps
    hours: dict[str, dict[int, set]] = {}
    for f in ncs:
        try:
            ds = xr.open_dataset(f)
        except Exception as e:  # noqa: BLE001
            report(None, "ERA5 file", f"{f.name}: cannot open ({e})")
            continue
        tname = "valid_time" if "valid_time" in ds.coords else "time" if "time" in ds.coords else None
        if tname is None:
            ds.close()
            continue
        times = ds[tname].to_index()
        for v in ds.data_vars:
            if v in ERA5_VARS or v in ERA5_OPTIONAL:
                per_year = hours.setdefault(v, {})
                for y in YEARS:
                    per_year.setdefault(y, set()).update(
                        times[(times.year == y) & times.month.isin(MONTHS)])
        ds.close()

    for v, label in {**ERA5_VARS, **ERA5_OPTIONAL}.items():
        optional = v in ERA5_OPTIONAL
        if v not in hours:
            report(None if optional else False, f"ERA5 {label} ({v})",
                   "optional, not found" if optional else "variable not found")
            continue
        for y in YEARS:
            n = len(hours[v].get(y, ()))
            report(n == HOURS_JJA, f"ERA5 {label} ({v}) {y}", f"{n}/{HOURS_JJA} hours Jun-Aug")


# --------------------------------------------------------------------------- #
# 4. Supporting files (matched by name, so check the 'CHECK' lines by hand)
# --------------------------------------------------------------------------- #
def check_support(root: Path) -> None:
    items = {
        "Stations / GTFS-Stops (Bahn-Vorhersage)": ["*stop*", "*station*"],
        "Operator code mapping (iris-owner-matchings / Resource_1.csv)": ["*owner*", "*operator*", "Resource_1*"],
        "IRIS message code list": ["*message*", "*code*"],
        "School holidays by state": ["*ferien*", "*holiday*", "*school*"],
        "Germany / state boundaries (e.g. BKG VG250)": ["*VG250*", "*vg250*", "*bundesl*", "*boundar*", "*.gpkg", "*.shp"],
        "Major events list (strikes, closures, floods, Euro 2024)": ["*event*", "*disruption*"],
        "OSM railway network (optional)": ["*.osm.pbf", "*railway*", "*osm*"],
        "DWD station data (optional, validation)": ["*produkt_*", "*stundenwerte*", "*tageswerte*"],
    }
    for label, pats in items.items():
        hits = [h for h in find(root, *pats) if h.suffix not in {".parquet", ".nc"}]
        optional = "optional" in label
        if hits:
            shown = ", ".join(h.name for h in hits[:3]) + (" ..." if len(hits) > 3 else "")
            report(None, label, f"candidates: {shown}")
        else:
            report(None if optional else False, label, "nothing matching found")

    try:
        import holidays  # noqa: F401
        report(True, "Public holidays", "python package 'holidays' installed")
    except ImportError:
        report(False, "Public holidays", "pip install holidays")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
    if not root.is_dir():
        sys.exit(f"Data folder not found: {root.resolve()}")
    print(f"Checking {root.resolve()}\n")

    for name, fn in [("train", check_train), ("HYRAS", check_hyras),
                     ("ERA5", check_era5), ("supporting", check_support)]:
        try:
            fn(root)
        except ImportError as e:
            report(False, f"{name} check", f"missing package: {e.name}")

    width = max(len(r[1]) for r in results)
    for status, item, detail in results:
        print(f"[{status}] {item:<{width}}  {detail}")
    n_missing = sum(r[0].startswith("MISSING") for r in results)
    print(f"\n{n_missing} item(s) missing. 'CHECK' lines are matched by file name only, "
          "please confirm them by eye.")


if __name__ == "__main__":
    main()
