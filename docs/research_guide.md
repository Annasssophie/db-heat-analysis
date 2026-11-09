# Research Guide: Extreme Heat and Rail Delays in Germany (GTFS-RT, 2022)

**Research question:** How does extreme heat affect rail service delays, measured with archived GTFS-RT data?

**Scope for now:** Germany, calendar year 2022, rail services only.

This guide runs from raw data to a defensible result. Each phase lists what to do, what to produce, and the common mistakes. The phases are in order, but expect to go back to earlier ones. Data quality problems found in Phase 4 usually mean changes to Phase 2.

---

## Phase 0: Sharpen the question before touching data

Turn the broad question into hypotheses you can test. Write them down in the README or a `docs/hypotheses.md` file, so later choices don't drift.

1. **Define "extreme heat."** Pick one main definition and keep the others for robustness checks:
   - DWD *Heißer Tag*: daily maximum temperature ≥ 30 °C (standard in German climate reporting).
   - Absolute thresholds or bins: < 20, 20–25, 25–30, 30–33, 33–35, ≥ 35 °C.
   - Relative: the station's 95th/99th percentile of daily Tmax. This accounts for regional adaptation (north vs. south).
   - Heatwave: ≥ 3 consecutive days ≥ 30 °C. This tests whether heat effects build up.
2. **Define "delay"** (you will likely report several):
   - Mean arrival delay in minutes per stop event.
   - Punctuality share: DB counts a stop as "on time" if the delay is **< 6 min** (≤ 5:59). Use the same threshold so your numbers compare with official DB statistics.
   - Share of severe delays (≥ 15 or ≥ 30 min).
   - Cancellations: trips or stops flagged `CANCELED` / `SKIPPED`. Heat can cancel trains outright, and ignoring cancellations biases delay estimates (see Phase 5).
3. **Decide the unit of analysis.** The recommended base unit is the **stop event**: one train (trip) at one stop on one service day. You can aggregate up from there to station-day, line-day or network-day.
4. **Name the mechanisms you expect.** This tells you which heterogeneity to test later:
   - Infrastructure: track buckling and heat-related speed restrictions, signal and switch failures, overhead-line sag.
   - Rolling stock: air-conditioning failures that take vehicles out of service.
   - Operations: wildfires near tracks, staff heat restrictions, more passengers (and longer dwell times).
   - Expected pattern: effects grow in the afternoon, under cumulative heat, on older or busier lines, and differ between long-distance and regional services.

**Output:** a one-page analysis plan listing the hypotheses, outcome definitions and the main model.

---

## Phase 1: Understand your data sources

### 1a. The GTFS-RT archive
Before downloading everything, answer these questions from the provider's documentation or a small sample:

- **Feed type(s):** Does it contain `TripUpdates` (delays and predictions), `VehiclePositions`, `ServiceAlerts`? You mainly need TripUpdates. ServiceAlerts can be a useful side source because they sometimes name heat-related disruptions explicitly.
- **Snapshot frequency:** Is the feed saved every 30 s, every minute, every 5 minutes? This sets data volume and how precisely you can recover the final delay.
- **Coverage:** Which operators are included? Many German real-time feeds (e.g. the DELFI/gtfs.de feeds) cover regional rail (DB Regio, private operators, S-Bahn) well but long-distance DB Fernverkehr only partially or not at all. Find out what you actually have before you claim results for "German rail."
- **File format:** raw protobuf (`.pb`), gzipped protobuf, or already flattened (CSV/Parquet)?
- **Gaps:** Are there days or hours with no snapshots (archiver outages)? You need a coverage table (Phase 4).
- **Size:** estimate total volume. A full year of nationwide snapshots can be hundreds of GB to several TB.

### 1b. The matching static GTFS
GTFS-RT only gives *deviations*. You need the **static GTFS schedule that was valid at the same time** to get:
- scheduled arrival and departure times (`stop_times.txt`),
- stop coordinates (`stops.txt`) for matching weather,
- route type (`routes.txt`) to keep rail only,
- service calendars (`calendar.txt`, `calendar_dates.txt`).

`trip_id`s change between static feed versions, often weekly. Get **every static feed version published in 2022** and match each RT snapshot to the version valid on that date. A wrong version is the most common reason for low match rates.

### 1c. Weather data
- **DWD Climate Data Center** (`opendata.dwd.de/climate_environment/CDC/`):
  - Daily station data (`kl` product): `TXK` = daily maximum temperature, `TMK` = daily mean, `RSK` = precipitation.
  - Hourly air temperature (`air_temperature`), if you want the temperature at the time of each train.
  - Station metadata with coordinates.
- **Gridded alternatives:** DWD HYRAS or ERA5-Land (via the Copernicus CDS). These give temperature at every rail stop without the choice of a nearest station.
- **Other weather controls:** precipitation, wind gusts and thunderstorms. Summer storms often follow heat, and they also cause delays, so they are a confounder.

### 1d. Context and confounders specific to 2022 (very important)
- **9-Euro-Ticket (June 1 – August 31, 2022):** extremely cheap regional transport led to much higher ridership, crowding and longer dwell times. It overlaps **exactly** with the heat season, so a naive summer-vs-rest comparison would mix up heat and crowding. Your design has to separate the two (Phase 6).
- **Major heat episodes in 2022:** roughly mid-June (~18–19 June), **18–20 July** (40 °C+ in parts of Germany), and early-to-mid August. Check the exact dates against DWD data.
- **Construction works and timetable changes** (DB Netz *Baustellen*), school holidays by Bundesland, public holidays, strikes, and storms (e.g. February 2022 storms *Ylenia/Zeynep/Antonia*).
- If you can get it: DB punctuality statistics or press releases for 2022, to validate your aggregate numbers.

**Output:** a data inventory table (source, coverage, format, size, licence, access method), saved as `docs/data_sources.md`.

---

## Phase 2: Set up the project and the processing pipeline

### 2a. Repository structure (suggested)
```
db-heat-analysis/
├── data/                 # git-ignored (already in .gitignore)
│   ├── raw/              # untouched downloads (RT snapshots, static GTFS, DWD)
│   ├── interim/          # parsed / flattened RT, filtered to rail
│   └── processed/        # analysis-ready panels
├── src/                  # reusable code (parsing, matching, weather join)
├── notebooks/            # exploration and figures; import from src/
├── docs/                 # this guide, data inventory, analysis plan
├── results/              # tables and figures
├── requirements.txt / pyproject.toml
└── README.md
```

### 2b. Tooling
- `gtfs-realtime-bindings` + `protobuf` to decode `.pb` files.
- `pyarrow` / Parquet for storage, **DuckDB** or **Polars** for queries on large data. pandas alone will not handle a year of snapshots.
- `geopandas` / `scipy.spatial.cKDTree` to match stops to weather stations.
- `statsmodels` and/or `pyfixest` / `linearmodels` for fixed-effects regressions.
- Pin versions in `requirements.txt` so the work can be reproduced.

### 2c. Start with a pilot, not the full year
Pick **one normal week and one heat week** (e.g. a cooler week in early June and **18–20 July 2022**). Build and debug the whole pipeline on these before scaling up. The existing `01_explore_june28.ipynb` is a natural place for this first look.

**Output:** a working environment and the pilot week of raw data downloaded.

---

## Phase 3: Parse GTFS-RT into a clean stop-event table

This is the most technically demanding step.

1. **Decode snapshots** (TripUpdates). For each `StopTimeUpdate`, extract:
   `snapshot_timestamp, trip_id, start_date, route_id, stop_id, stop_sequence, arrival_delay, arrival_time, departure_delay, departure_time, schedule_relationship` (trip- and stop-level).
2. **Filter to rail early** to save space: join on `route_id` → `routes.route_type` and keep `2` (rail) plus the extended rail types `100–117` (and `109` suburban rail / S-Bahn, `400–405` urban rail if you want U-Bahn; decide and document). Decide also whether trams and metros count as "rail" for your question.
3. **Collapse snapshots into one observation per stop event.** Each trip-stop appears in many snapshots. Early values are *predictions*, the last ones are close to what actually happened. A standard approach:
   - Keep the **last update received before or shortly after the scheduled or actual stop time** as the "realised" delay.
   - Record how many updates the stop event had, and the time gap between the last update and the stop time, as quality indicators.
   - Be aware that some feeds propagate one delay value to all later stops; a stop that has passed may never get a fresh value.
4. **Join to the static schedule** (correct feed version!) on `trip_id` + `start_date` + `stop_sequence` (or `stop_id`). Report the **match rate** for each day. Below ~90%, investigate before going on.
5. **Compute delays** where the feed gives absolute times instead of delay fields: `delay = actual_time − scheduled_time`. Handle times past midnight (GTFS allows `25:10:00`).
6. **Time zones:** RT timestamps are POSIX/UTC. GTFS schedule times are local (Europe/Berlin). Note the DST switches on 27 March and 30 October 2022.
7. **Cancellations:** keep stop events with `schedule_relationship = CANCELED/SKIPPED` as a separate outcome. Don't drop them silently.
8. **Store** the result as partitioned Parquet (`data/interim/stop_events/date=2022-07-19/…`).

**Output:** `stop_events` table with one row per (trip, stop, service date): scheduled time, realised delay, cancellation flag, route type, operator, stop coordinates, quality indicators.

---

## Phase 4: Data quality checks (don't skip this)

Make a short notebook or report with:
- **Coverage per day and hour:** number of snapshots, trips and stop events. Mark archiver outages. Missing data must never be read as "no delays."
- **Match rate** to the static schedule per day.
- **Delay distribution:** look for negative delays (early trains) and implausible values (e.g. > 300 min or < −30 min). Decide on rules for trimming or capping and document them.
- **Representativeness:** which operators and lines are present all year? An unbalanced panel (lines appearing or disappearing) can create fake time trends. You may want to restrict to lines with stable coverage.
- **Validation:** compare monthly punctuality (< 6 min) with published DB figures. They won't match exactly, but they should follow similar patterns.

**Output:** `docs/data_quality.md` with these figures and the exclusion rules you decided on.

---

## Phase 5: Build the weather exposure and join it

1. **Download DWD daily (and optionally hourly) data for 2022** for all stations, plus the station list.
2. **Match each rail stop to weather.** Choose one:
   - Nearest DWD station within, for example, 25 km (also check elevation differences), or
   - Inverse-distance weighting of the 3 nearest stations, or
   - Value from the gridded product at the stop location (cleanest).
3. **Create exposure variables** per stop and day: `tmax`, `heat_day = tmax ≥ 30`, temperature bins, station-relative percentiles, number of consecutive hot days, and the lagged temperature of the previous day.
4. **Think about where the heat matters.** Delay at a stop reflects conditions **along the whole route up to that stop**, not just at the stop itself. Two ways to handle this:
   - **Segment-level delay increments:** `Δdelay = delay_at_stop_k − delay_at_stop_(k−1)`, matched to the temperature of segment k. This isolates delay *created* on that segment and is the cleanest way to link local heat to local delay.
   - **Trip-level exposure:** maximum or mean temperature along the route of the trip.
5. **Join controls:** precipitation, wind gusts and thunderstorm indicators (same matching).
6. **Calendar controls:** day of week, public holidays and school holidays by Bundesland, a 9-Euro-Ticket period dummy, and known strike or storm days.

**Output:** `data/processed/analysis_panel.parquet`, the stop events (or segments) together with weather and calendar variables.

---

## Phase 6: Analysis

Work from simple to rigorous.

### 6a. Descriptive analysis
- Time series of daily mean delay and punctuality for 2022, with heat days shaded.
- Binned scatter: mean delay vs. daily Tmax (e.g. 1 °C bins). This shows whether the relation is non-linear, for example flat until about 28–30 °C, then rising.
- Hour-of-day profiles on hot vs. normal days. If heat is the cause, the gap should be largest in the afternoon and evening.
- Maps of the delay increase on heat days by region or line.

### 6b. Main regression model (panel, fixed effects)
A typical specification at the stop-event or segment level:

```
delay_ist = Σ_b β_b · 1[Tmax_st ∈ bin_b] + γ · precip_st + δ · wind_st
            + α_s (stop/line FE) + λ_dow + μ_week (or month) + θ_hour
            + 9EuroTicket_t + holiday_t + ε_ist
```

- Leave out a comfortable reference bin (e.g. 20–25 °C). Each β_b is then the extra delay at that temperature compared with a normal day **at the same stop, in the same week of the year, on the same day of the week**.
- **Week (or month) fixed effects** absorb seasonal effects and most of the 9-Euro-Ticket effect. Heat is then identified from day-to-day variation *within* summer, which is what you want.
- Cluster standard errors by line/route and by date (two-way), because delays are correlated across a network on the same day.
- Estimate it separately for each outcome: mean delay, P(delay ≥ 6 min), P(delay ≥ 15 min), P(cancelled).

### 6c. Complementary designs
- **Event study around heat waves:** daily delays from, say, 7 days before to 7 days after the start of each heatwave, compared with the same weekdays in neighbouring weeks.
- **Dose-response / cumulative heat:** does the third hot day in a row hurt more than the first?
- **Lag effects:** does damage from heat (e.g. speed restrictions after track buckling) last beyond the hot day?

### 6d. Heterogeneity (tests the mechanisms from Phase 0)
- Long-distance vs. regional vs. S-Bahn.
- Operator (DB vs. private operators; rolling stock age, if you can find it).
- Region (north vs. south, i.e. adaptation to heat) and urban vs. rural.
- Line or network utilisation. Busy corridors may spread delays more.
- Time of day.

### 6e. Robustness checks
- Other heat definitions (absolute vs. relative thresholds, hourly temperature at the time of the train).
- Other weather matching (nearest station vs. gridded).
- Leaving out storm days, strike days and archiver-gap days.
- Balanced panel (only lines covered all year).
- Placebo: use "future" temperature (t+7), which should show no effect.
- Possible selection bias from cancellations: if the worst trains are cancelled, delays among the remaining trains are *understated*. Report cancellations together with delays, or treat a cancellation as a large delay as a bounding exercise.

---

## Phase 7: Scale up to the full year

Once the pilot pipeline is checked:
1. Turn the notebook logic into scripts in `src/` that process **one day at a time** and can be resumed after errors.
2. Process all of 2022, partitioned by date. Log row counts and match rates per day.
3. Re-run the quality checks (Phase 4) on the full year.
4. Run the analysis notebooks against `data/processed/`.

Tip: keep the raw-to-stop-event step separate from analysis. Then analysis choices (heat thresholds, bins) don't require re-parsing terabytes.

---

## Phase 8: Interpret, write up, and plan extensions

- **Translate coefficients into concrete terms:** "On days ≥ 35 °C, average delay per stop rises by X minutes and punctuality drops by Y percentage points compared with a 20–25 °C day." Add an estimate of total extra delay-minutes or passenger-hours in 2022 if you can.
- **Limitations to state openly:** GTFS-RT values are predictions, operator coverage is incomplete, weather matching is approximate, the 9-Euro-Ticket overlapped with the heat season, and this is a single year.
- **Extensions:** add 2021, 2023, 2024 and 2025 (the pipeline should be year-agnostic). Several years let you separate heat from 2022-specific events, and test whether DB's heat adaptation measures change the effect over time. Climate projections can then be used to estimate future delay burdens.

---

## Checklist

- [ ] Analysis plan with hypotheses, heat definitions, outcome definitions (Phase 0)
- [ ] Data inventory: GTFS-RT archive, all 2022 static GTFS versions, DWD weather (Phase 1)
- [ ] Repository structure and pinned environment (Phase 2)
- [ ] Pilot weeks downloaded (one normal week, one heat week)
- [ ] RT parser → stop-event table, filtered to rail (Phase 3)
- [ ] Static schedule match rate ≥ ~90% on pilot days
- [ ] Data quality report and exclusion rules (Phase 4)
- [ ] Weather matched to stops/segments, calendar controls added (Phase 5)
- [ ] Descriptive figures (Phase 6a)
- [ ] Fixed-effects model with temperature bins (Phase 6b)
- [ ] Event study, heterogeneity, robustness (Phase 6c–e)
- [ ] Full-year processing (Phase 7)
- [ ] Write-up with limitations and extensions (Phase 8)
