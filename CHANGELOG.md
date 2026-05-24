# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-05

### Added
- **`number` platform** — editable «новое показание» per meter with
  RestoreNumber, prefilled from cabinet, persisted across HA restarts.
  Per-meter `step` derived from the cabinet's `cabinet_change` formatter
  (different meters can have 3 vs 4 digits after the dot).
- **`binary_sensor` «Есть задолженность»** — `due_payment > 0`
  (`device_class=problem`).
- **Payment breakdown sensors** — `opening_balance`, `accrued`, `paid`
  as separate top-level sensors (RUB, monetary).
- **Per-meter «потребление» sensor** with `state_class=TOTAL_INCREASING`
  for Home Assistant Water Dashboard.
- **Per-meter «дата показаний» sensor** (parsed from the readings table).
- **ЕЛС on DeviceInfo.serial_number** — exposed on the HA device page.
- **`repairs.py`** — actionable Repair Issue when the cabinet HTML changes
  shape (`BCNNParseError`); auto-resolved on the next successful refresh.
- **`diagnostics.py`** — redacted entry data + coordinator snapshot.
- **`config_flow` reauth** — change the password without removing the entry.
- **Multi-account setup** — one cabinet login can register all linked
  accounts in a single flow.
- **Retry/backoff** on transient connection errors in the coordinator.
- **HACS / hassfest CI** + ruff lint + pytest with 86+ tests covering
  parsing, HTTP flows, config flow, coordinator, sensors, number, services,
  diagnostics and the new binary sensor.

### Changed
- **`send_readings` service** rewritten. Three input modes with priority:
  meter slots (`meter_N` + `meter_N_value`), an optional `readings` dict
  for automations, fallback to the per-meter `number` entities. All selected
  meters are validated against the chosen account — meters from other ЛС
  are rejected with a clear error.
- `BCNNApi.VERSION` is read from `manifest.json` at runtime, no more
  hardcoded `0.0.1`.
- Sensor values appear immediately after setup, not only after the first
  manual refresh.
- `transliterate` is warmed up in `async_setup_entry` (off the event loop)
  to satisfy HA's blocking-call detector.

### Fixed
- `BCNNMeterSensor.avabl_fn` no longer crashes with `TypeError` when a
  meter row disappears from the API response — the sensor becomes
  unavailable instead.
- Form-token cache (`self.devices`) is cleared between calls to
  `get_information_on_water_meters` — no leftover entries from a previous
  refresh leak into `send_meter_readings`.
- `sleep(30)` removed from `send_meter_readings`; `locale.setlocale` removed
  from module import; raw `raise` without an active exception fixed.
- Passwords are no longer written to the HA log on entry setup.

### Migration notes
- `meter_1..meter_4` slots in `send_readings` keep working. The new
  `readings` dict is preferred for automations.
- `services.yaml` continues to declare the UI selectors; the
  `strings.json` / `translations/*` files now only carry names and
  descriptions (per hassfest validation).
