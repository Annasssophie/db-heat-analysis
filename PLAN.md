# Rail heat resilience – analysis plan & handoff

Goal: analyse the resilience of the German rail system against extreme heat, using the
Bahn-Vorhersage dataset (Döllmann 2025) plus weather data. Scope: June–August (JJA), starting
with 2022, later extended to 2023–2025.

## Status

- Repo contains only `.gitignore` and an **empty (0-byte) `notebooks/data_exploration.ipynb`**
  (invalid JSON – recreate it).
- Data (`data/`, `*.parquet`, `*.csv`) is gitignored and was **never inspected**: the cloud
  session could not reach the local machine. First task in a local session = data audit.
- No analysis code written yet. Nothing below has been run.

## Open questions (answer these first)

1. Python or R? (Notebook kernel was `.venv` Python 3.12 → Python assumed.)
2. Which weather sources / variables / resolution? (DWD station data, ERA5, gridded, …)
3. Is the DB data the "Parsed Tabular Data" from Mobilithek (Table 4 schema below)?
4. Definition of "resilience": performance loss per °C, tipping point, spread, or recovery time?
5. DB operators only, or all operators?

## Dataset facts that matter (Döllmann 2025)

- One row = one arrival **or** departure event. Key columns: `trip_id`, `stop_id`, `stop_sequence`,
  `time_schedule`, `time_real`, `delay` (seconds), `is_final`, `is_arrival`, `is_cancelled`,
  `is_regional`, `category`, `line`, `operator`, `lat`, `lon`, `distance_traveled`,
  `is_betriebshalt`, `message_codes`.
- **All timestamps are UTC** → convert to Europe/Berlin before assigning dates / joining hourly weather.
- `time_real` is the actual time only if `is_final == True`. `is_final` is a heuristic (last known
  update). Before Sep 2023 only the final state was kept; from Sep 2023 the full update history is
  stored → **filter to `is_final` for 2023–25** to stay comparable with 2022.
- Delays are minute-rounded, with artifacts at 20/30/40/50/60 min.
- Replacement buses mostly lack real-time data; stops outside Germany exist; cancelled stops can
  be flagged even if adjacent stops were cancelled.
- Punctuality (DB definition): arrival delay < 6 min, cancelled stops excluded.
  Use to sanity-check against official DB monthly stats.
- Known gaps: Jan 2023, Mar 2024, Sep 2025 – none fall in JJA (verify per day anyway).
- Long-distance categories: IC, EC, ECE, ICE, EN, RJ, RJX, TGV, FLX, NJ, THA, NEX, EIC, UEX, EST, WB
  (`is_regional` encodes this).
- Delay propagates along a trip → consider delay *increment* between consecutive stops.

## Confounders to handle

- **9-Euro-Ticket Jun–Aug 2022** (demand surge, regional); Deutschlandticket from May 2023.
- Construction works, staggered state school holidays, public holidays, weekday/hour patterns.
- Thunderstorms/wind/rain often follow heat → control for precipitation and wind.
- Few heat events in 2022 alone → power improves a lot with 2023–25.

## Plan

**Phase 0 – Audit.** Schema, row counts, daily coverage in JJA, share with real-time data, nulls,
operator/category mix; reproduce DB punctuality as sanity check.

**Phase 1 – Build analysis dataset.** Clean stop events (tz, `is_final`, drop buses/non-German/
`is_betriebshalt`, handle cancellations separately) → match stops to weather (nearest station or
grid cell) → heat metrics (daily Tmax, hours >30 °C, flags ≥30/32/35 °C, consecutive heat days,
3-day mean, tropical nights) + controls (precip, wind, storm proxy, holidays, traffic volume) →
aggregate to station×hour or station×day.

**Phase 2 – Descriptives.** JJA time series (punctuality, mean/p90 delay, cancellation share) vs
temperature; outcomes by temperature bin and train type (long-distance / regional / S-Bahn);
maps of delay on hot vs normal days; hour-of-day profiles; heat-wave event studies
(e.g. 19–20 Jul 2022) incl. recovery time; tail/distribution plots.

**Phase 3 – Fixed-effects panel.**
- Unit: station×hour or station×day (robustness: trip-level FE on stop events).
- Outcomes: late6 share, winsorized mean delay, cancellation share, delay increment, p90.
- Spec: outcome ~ temperature bins (ref 15–20 °C) + precip + wind + station FE + hour×weekday FE
  + week-of-year/month FE (+ holidays, volume). Year FE once pooled.
- SEs clustered by date (or two-way station×date); consider Conley spatial HAC.
- Heterogeneity: train type, region, urban/rural, time of day.
- Falsification: lead temperature, alternative heat definitions, lags.
- Note: full date FE would absorb most temperature variation (spatially correlated) – avoid.

**Phase 4 – Resilience framing.** (1) loss per °C above threshold, (2) tipping point,
(3) spatial concentration vs system-wide, (4) recovery time after heat waves.

## Proposed repo layout (not created yet)

```
data/            # gitignored: raw/, interim/, processed/
src/ config.py audit_data.py clean_db.py weather.py stations.py build_panel.py descriptives.py models.py
notebooks/       # 00_audit, 01_descriptives, 02_models (thin, call src/)
outputs/         # figures, tables
requirements.txt, README.md
```

Tooling suggestion: DuckDB/Polars (lazy parquet scans), GeoPandas, `pyfixest`, matplotlib.
Everything keyed off `YEARS = [2022]` in `config.py` so 2023–25 is a one-line extension.

## Prompt to paste into the local session

> Read `PLAN.md`. Data lives in `data/` in this repo. Do not write analysis scripts yet.
> 1. Inventory `data/` (files, sizes, formats) and inspect schemas of the DB parquet and each
>    weather source. Check the DB schema against Table 4 in the plan.
> 2. Audit JJA 2022 coverage per day (row counts, share with real-time data, nulls), after
>    converting UTC to Europe/Berlin.
> 3. Report what's missing or surprising, then help me resolve the open questions above and set up
>    the repo skeleton, `requirements.txt` and `config.py`.

Reference: Döllmann, T. (2025). *Bahn-Vorhersage dataset: an open archive of most train delays in
Germany since September 2021.* Universität Augsburg. Data: Mobilithek (ODbL).
