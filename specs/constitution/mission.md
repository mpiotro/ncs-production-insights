# Mission — the WHY

## Vision
Give Norwegian Continental Shelf (NCS) analysts and engineers a fast, trustworthy view of field
production, with **credible, backtested decline forecasts** — built entirely from open data, spec-first.

## Users
- Primary: reservoir/production engineers and data analysts working NCS fields.
- Secondary: the demo audience evaluating multi-agent spec-driven development.

## In scope
- Ingest SODIR open data: **monthly production per field** (full history) and **field geometry**.
- Per-field **decline forecasting**, 24-month horizon, with held-out backtest accuracy.
- Dashboard: per-field production history + forecast charts, and a map of fields.
- Coverage: **all NCS producing fields** the data contract defines.

## Out of scope (explicit)
- Real-time / streaming data — SODIR is periodic open data.
- Economics, reserves, or volumetric modelling.
- Authentication, accounts, multi-tenancy.
- Wellbore / facility / discovery layers — only field production + field geometry this cycle.

## Done — the demo succeeds when
A viewer opens the dashboard, picks a representative NCS field, and sees its historical monthly
production with a **24-month forecast that passed the < 15% MAPE backtest gate**, and the field
located on the map — all served from the frozen data contract through the API.
**And** the process is visible: phases 002 / 003 / 004 were built in **parallel worktrees** off the
frozen 001 contract, each carrying its spec → plan → tasks → tests → implementation artifacts.
