# routing/ build checklist

Build order for the design in `DESIGN.md`.

Rules:

- Build only what is listed, in order.
- Tick an item only after its check has been run and gave the expected result.
- Stop at the end of each phase for review.
- Commit on branch `tushaar` at the end of each phase. Never push.
- Tests live in `routing/tests/` and use the small synthetic grids from `conftest.py`. Only phase 7 reads `data/out/`.
- Commands run from the repo root with `.venv` active.

Each item: **task** · file · check.

## Phase 1: config + grid

- [x] **1.0** Confirm the search interface. · no file · `python -c "import skimage, scipy, pytest"` exits 0, and `python -c "from skimage.graph import MCP_Geometric; help(MCP_Geometric)"` shows `sampling`, `fully_connected`, `find_costs` and `traceback`.
- [x] **1.1** Write the full config from DESIGN section 10. · `routing/config.toml` · `python -c "import tomllib; tomllib.load(open('routing/config.toml','rb'))"` exits 0.
- [x] **1.2** Config loader that rejects a parameter missing `value`, `unit`, `type` or `source`, or with an unknown type. · `routing/config.py` · `test_config.py::test_every_parameter_has_four_keys`, `::test_unknown_type_rejected`.
- [x] **1.3** Gravity check at load, covering `v_flat` and every sensitivity value. · `routing/config.py` · `test_config.py::test_walk_run_transition_is_4_65_kmh`, `::test_v_flat_above_transition_fails`.
- [x] **1.4** Test fixtures: flat grid, tilted plane, red wall, and a 120 x 80 grid with 10 m cells. · `routing/tests/conftest.py` · `pytest --fixtures routing/tests` lists all four.
- [x] **1.5** Read the grid size from `layers.json`. · `routing/grid.py` · `test_grid.py::test_grid_comes_from_layers_json` (uses the 120 x 80 fixture).
- [x] **1.6** Cell ↔ metre conversion. · `routing/grid.py` · `test_grid.py::test_cell_centre_matches_contract` (row 0, column 0 on 400 x 400 at 5 m gives x 2.5, y 1997.5), `::test_xy_cell_round_trip`.
- [x] **1.7** Load `dem.tif` and `hazard.tif`; reject a wrong shape or a hazard value outside 0–2. · `routing/grid.py` · `test_grid.py::test_shape_mismatch_fails`, `::test_bad_hazard_value_fails`.
- [x] **1.8** Terrain slope in degrees. · `routing/grid.py` · `test_grid.py::test_slope_of_10pct_plane_is_5_71_deg`.
- [x] **End of phase 1:** `pytest routing/tests` passes · commit.

## Phase 2: speed + cost

- [x] **2.1** Walking speed. · `routing/walking.py` · `test_walking.py::test_flat_speed_is_v_flat`, `::test_uphill_equals_downhill`, `::test_10pct_slope_factor_is_0_705`.
- [x] **2.2** Hard mask: red, slope limit, cliff buffer, sealed diagonal gaps. · `routing/cost.py` · `test_cost.py::test_red_blocked`, `::test_over_limit_slope_blocked`, `::test_buffer_ring_blocked`, `::test_buffer_zero_disables`, `::test_diagonal_gap_sealed`.
- [x] **2.3** Risk rate: yellow, steep ramp, near-red. · `routing/cost.py` · `test_cost.py::test_yellow_rate`, `::test_steep_ramp_zero_at_onset_full_at_limit` (sets a non-zero rate; the config default is 0), `::test_near_red_zero_at_radius`.
- [x] **2.4** Time-rate and planning-cost arrays in minutes per metre, −1 where blocked. · `routing/cost.py` · `test_cost.py::test_flat_rate_is_0_0222_min_per_m`, `::test_blocked_cells_are_negative`, `::test_w_zero_cost_equals_time_rate`.
- [x] **End of phase 2:** `pytest routing/tests` passes · commit.

## Phase 3: routing + profiles

- [x] **3.1** Search wrapper returning the path, physical minutes and risk minutes separately. · `routing/search.py` · `test_search.py::test_straight_on_open_flat_grid`, `::test_flat_5m_step_is_0_111_min`, `::test_diagonal_is_root2_longer`, `::test_goes_round_red_wall`, `::test_unreachable_reported`, `::test_time_not_changed_by_w_on_same_path`.
- [x] **3.2** Load waypoints; fail by name on a blocked or unreachable stop. · `routing/tour.py` · `test_tour.py::test_stop_on_red_names_stop`, `::test_unreachable_stop_names_stop`, `::test_at_most_one_start_and_at_least_one_stop`.
- [x] **3.3** Stop order, both modes. · `routing/tour.py` · `test_tour.py::test_as_listed_keeps_file_order`, `::test_optimise_minimises_balanced_cost`, `::test_tie_follows_file_order`.
- [x] **3.4** The three profile routes. · `routing/tour.py` · `test_tour.py::test_route_is_start_to_start_through_all_stops`, `::test_time_fastest_le_balanced_le_safest`, `::test_risk_fastest_ge_balanced_ge_safest`.
- [x] **End of phase 3:** `pytest routing/tests` passes · commit.

## Phase 4: back-to-start map + storm

- [x] **4.1** Back-to-start time array, ingress included. · `routing/shelter.py` · `test_shelter.py::test_start_cell_equals_ingress`, `::test_flat_matches_distance_over_speed`, `::test_blocked_cells_are_nan`.
- [x] **4.2** Render the PNG with contour lines. · `routing/shelter.py` · `test_shelter.py::test_png_is_grid_sized_rgba`, `::test_blocked_cells_transparent`, `::test_contours_at_interval`.
- [x] **4.3** Storm return table. · `routing/storm.py` · `test_storm.py::test_samples_include_every_stop`, `::test_return_path_ends_at_start`, `::test_return_min_equals_minutes_back_to_start`, `::test_worst_point_is_maximum`.
- [x] **End of phase 4:** `pytest routing/tests` passes · commit.

## Phase 5: timeline + radiation + outputs

- [x] **5.1** Legs and totals. · `routing/timeline.py` · `test_timeline.py::test_total_is_walk_plus_stops_plus_ingress`, `::test_legs_chain_start_to_start`.
- [x] **5.2** Budget checks and status. · `routing/timeline.py` · `test_timeline.py::test_usable_is_252_min_for_360_and_30pct`, `::test_over_reserve_flags_status`, `::test_abort_check_uses_elapsed_plus_return`.
- [x] **5.3** Radiation. · `routing/timeline.py` · `test_timeline.py::test_background_dose_180_min_is_80_usv`, `::test_solar_event_is_8_1_mgy_in_its_own_field`, `::test_event_dose_not_added_to_sv`, `::test_csv_baseline_mismatch_warns`.
- [x] **5.4** Track samples. · `routing/timeline.py` · `test_timeline.py::test_track_spacing`, `::test_elapsed_never_decreases`, `::test_elapsed_includes_stop_time`.
- [x] **5.5** Writers for the three route files. · `routing/outputs.py` · `test_outputs.py::test_single_linestring_inside_extent`, `::test_no_fake_property`.
- [x] **5.6** `plan.json` writer. · `routing/outputs.py` · `test_outputs.py::test_all_contract_keys_present`, `::test_assumptions_match_config`, `::test_two_runs_identical`.
- [x] **5.7** Wire the entry point, with `--in DIR` (default `data/out`), `--out DIR` (default: the value of `--in`) and `--config FILE` (default `routing/config.toml`), as in DESIGN section 2. · `routing/plan_route.py` · `test_plan_route.py::test_in_out_config_options` (runs on a temp copy, `data/out` untouched); `python routing/plan_route.py` exits 0 and writes `route.geojson`, `route_fastest.geojson`, `route_safest.geojson`, `shelter_time.png` and `plan.json`; `python data/validate.py` prints `OK`.
- [x] **End of phase 5:** `pytest routing/tests` passes · `python data/validate.py` passes · commit.

## Phase 6: sweep + sensitivity

- [x] **6.1** w-sweep. The sweep function lives in `analysis.py`. `plan_route.py` calls it and writes the `sweep` block in `plan.json`. `analysis.py` run as a script takes `--in DIR`, `--config FILE` and `--reports DIR` (default `routing/reports`), as in DESIGN section 2; it writes `sweep.csv` and the other CSVs only and never writes to `data/out`. · `routing/analysis.py`, `routing/plan_route.py` · `test_analysis.py::test_sweep_time_rises_risk_falls`, `::test_in_config_reports_options` (runs on a temp copy, `data/out` and `routing/reports` untouched); after `python routing/plan_route.py`, `plan.json` `sweep` has 7 rows; after `python routing/analysis.py`, `routing/reports/sweep.csv` has the same 7 rows.
- [x] **6.2** Sensitivity over `v_flat`, slope limit and w. · `routing/analysis.py` · `python routing/analysis.py` writes `routing/reports/sensitivity.csv` with 18 rows; `test_analysis.py::test_faster_v_flat_shortens_walk`.
- [ ] **6.3** Validate the hard mask against the Perseverance traverse: share of traverse points on passable cells. **Blocked until Yaj supplies the traverse in grid coordinates.** · `routing/analysis.py` · `test_analysis.py::test_traverse_share_on_synthetic_mask`; the run writes `routing/reports/validation.csv` with the number of traverse points, the number on passable cells and the share.
- [ ] **End of phase 6:** `pytest routing/tests` passes · `python data/validate.py` passes · commit.

## Phase 7: end-to-end run

- [x] **7.1** Full rebuild, in this order. · no file · `python data/make_fake.py`, then `python routing/plan_route.py`, then `python data/validate.py` prints `OK` with no warning for `plan.json` or `route.geojson`. **`make_fake.py` overwrites `route.geojson`, `plan.json` and `shelter_time.png` with fake versions, so `plan_route.py` must always run after it.**
- [x] **7.2** Checks on the real outputs. · `routing/tests/test_end_to_end.py` · `::test_no_route_touches_red` (no route cell is red; diagonal steps past a red corner are allowed), `::test_route_slope_under_limit`, `::test_plan_status_ok`.
- [x] **7.3** Site-agnostic. · `routing/tests/test_end_to_end.py` · `::test_runs_on_120x80_grid`; a search for `400`, `2000` and `5.0` in `routing/*.py` finds nothing.
- [x] **7.4** The web app still builds. · no file · `cd web && npm run build` exits 0.
- [x] **7.5** Update the run instructions. · `routing/README.md` · every command in it runs as written.
- [x] **End of phase 7:** `pytest routing/tests` passes · `python data/validate.py` passes · commit · hand over to `QA.md`.

## Phases 8 and 9: fixed starts and the per-start reach export (superseded by phase 10)

Phase 8 added a configured start and a reach export (one search per profile from the start, with time, distance, risk, direction and reason grids in `data/out/reach/`). Phase 9 made the start a list of three landing spots copied from the web app's own output. Both were built and checked at the time, then **removed in phase 10**: those landing spots came from fake data, and the browser now searches from any landing spot itself. What survives: the blocked-reason codes (`start.py`), the start checks, the `rover` deprecation alias, and the one-way over-budget rule (now `budget.destination_stop`, DESIGN section 15.5).

## Phase 10: landing safety and the browser's cost surface

The user clicks anywhere to choose a landing zone; an unsafe click moves to the nearest safe spot; from it the user clicks a destination and the browser finds three walking paths. DESIGN sections 4.9, 14 and 15. Walking model, constraints, budgets, radiation and the one-way over-budget rule are unchanged.

- [x] **10.1** Remove the fixed starts: `[starts.*]`, `start.default`, the data hashes and the `reach.*` parameters from `config.toml` and `config.py`; `export_reach.py` and its tests deleted; `data/out/reach/` deleted (53 files). · `routing/config.toml`, `routing/config.py`, `routing/start.py` · `test_start.py::test_the_config_has_no_starts_and_no_landing_spot_coordinates`; `test_config_rules.py::test_expected_parameters_match_the_shipped_config`; `ls data/out` shows no `reach`.
- [x] **10.2** `[landing]` thresholds in metres and degrees, type `assumption`, sources citing the current terrain files; window and tile size. · `routing/config.toml`, `routing/config.py` · `test_config_rules.py::test_landing_thresholds_are_assumptions_with_a_source`, `::test_window_values_are_checked`, the `landing.*` rows of `::test_range_rule_rejects`.
- [x] **10.3** Landing safety codes 0-7 with the documented priority, marginal band, thermal-inertia warning bits. · `routing/landing.py` · `test_landing.py::test_no_data_on_the_pad`, `::test_a_yellow_cell_on_the_pad_fails`, `::test_red_within_the_clearance_fails_and_beyond_it_passes`, `::test_too_steep`, `::test_height_range_from_one_step`, `::test_too_rough_on_a_checkerboard`, `::test_the_most_serious_reason_wins`, `::test_marginal_band_is_within_20_percent_of_a_limit`, `::test_marginal_on_real_geometry`, `::test_low_and_missing_thermal_inertia_are_warning_bits_only`, `::test_thermal_inertia_is_only_used_when_the_layer_is_real`.
- [x] **10.4** Nearest safe cell, with ties and the no-safe-cell error; `landing_check`. · `routing/landing.py` · `test_landing.py::test_nearest_safe_matches_brute_force`, `::test_nearest_safe_tie_is_one_of_the_tied_cells_and_repeatable`, `::test_no_safe_cell_is_a_clear_error`, `::test_a_safe_click_stays_where_it_is`, `::test_an_unsafe_click_moves_to_the_nearest_safe_cell`, `::test_a_marginal_click_stays_and_says_which_limit`.
- [x] **10.5** Cost-surface export identical to `cost.build`; edge rule written in DESIGN 15 and checked bit for bit against MCP. · `routing/export_landing.py`, `docs/DESIGN.md` · `test_export_landing.py::test_exported_surface_is_identical_to_cost_build`, `::test_the_edge_rule_reproduces_mcp_cumulative_costs_bit_for_bit`, `::test_route_follows_search_py_on_the_original_cost`.
- [x] **10.6** Golden cases (10 pairs x 3 profiles, one unreachable, one over budget under its own test budget) and the reference `route`; an independent Dijkstra replays them. · `routing/export_landing.py`, `routing/tests/replay.py` · `test_export_landing.py::test_golden_cases_cover_pairs_an_unreachable_and_an_over_budget_destination`, `::test_replay_reproduces_the_golden_cases_on_the_synthetic_site`, `::test_replay_reproduces_the_golden_cases_on_the_real_site`.
- [x] **10.7** One output folder with a manifest; window and tiles; `nearest_safe` computed on the whole window before tiling. · `routing/export_landing.py` · `test_export_landing.py::test_manifest_round_trips`, `::test_tiles_stitch_back_to_the_single_tile_export`, `::test_a_window_exports_only_that_box_in_site_metres`, `::test_a_bad_window_fails_clearly`, `::test_a_tile_size_that_is_not_whole_cells_fails`, `::test_two_runs_give_identical_bytes`, `::test_no_safe_cell_fails_and_writes_nothing`.
- [x] **10.8** `plan_route.py` / `analysis.py`: `--start x,y`, or the demo start; `plan.json` keys unchanged apart from the start record; unverified-stops warning. · `routing/tour.py`, `plan_route.py`, `analysis.py`, `outputs.py` · `test_start.py::test_plan_route_with_start`, `::test_plan_route_command_line_start`, `::test_plan_route_with_the_demo_start`, `::test_demo_start_is_the_safe_cell_nearest_the_grid_centre`, `::test_plan_json_keys_are_unchanged_apart_from_the_start_record`, `::test_plan_json_warns_that_the_stops_are_unverified`, `::test_a_start_waypoint_is_ignored_with_a_warning`.
- [x] **10.9** Run on the shared data. · no file · `python routing/export_landing.py` (9 files, 4,506,482 bytes in `data/out/landing/`), `python routing/plan_route.py` (demo start), `python routing/analysis.py` and `python data/validate.py` all exit 0.
- [ ] **End of phase 10:** `pytest routing/tests` passes · `python data/validate.py` passes · commit (left to Tushaar) · teammate requests in DESIGN section 12 ("Phase 10").

## Phase 11: measured landing values, the zones image and the messages

The front end shows why a landing spot was accepted or moved, with the numbers. DESIGN section 14.5. `format_version` stays 1 (files and fields are only added).

- [x] **11.1** Four measured grids per tile (float32), taken from `landing.measure`; NaN where not computed, `hazard_dist_m` never NaN and +Infinity with no hazard; units and limits in the manifest. · `routing/export_landing.py`, `routing/landing.py` · `test_export_landing.py::test_measured_grids_are_the_values_landing_py_checks`, `::test_hazard_distance_is_infinity_on_a_site_with_no_hazard`.
- [x] **11.2** `landing_zones.png` for the window, colours from `[landing]` `display_safe_rgba` / `display_marginal_rgba`, legend in the manifest. · `routing/export_landing.py`, `routing/config.toml`, `routing/config.py` · `test_export_landing.py::test_landing_zones_png_is_green_amber_and_transparent`, `::test_zone_colours_come_from_the_config`, `test_config_rules.py::test_display_colours_are_four_whole_numbers_from_0_to_255`.
- [x] **11.3** `landing_check` returns `measured`, `chosen_measured`, `messages` and `moved_text`; the templates are in the manifest and filling them from the files gives the same text. · `routing/landing.py`, `routing/export_landing.py` · `test_landing.py::test_every_code_and_every_reason_has_a_message_template`, `::test_fixed_rounds_halves_up_like_javascript`, `::test_a_steep_pad_reports_its_measured_tilt_and_the_limit`, `::test_hazard_message_gives_the_distance_only_when_the_distance_fails`, `::test_safe_and_marginal_messages`, `test_export_landing.py::test_messages_from_the_manifest_match_landing_check_everywhere`.
- [x] **11.4** Manifest round-trips with the new fields; a folder without them still loads. · `routing/export_landing.py` · `test_export_landing.py::test_manifest_round_trips`, `::test_an_older_folder_without_measured_grids_still_loads`.
- [x] **11.5** Run on the shared data. · no file · `python routing/export_landing.py` (14 files, 7,095,045 bytes in `data/out/landing/`) and `python data/validate.py` exit 0. `plan_route.py` was not rerun: the safety codes are unchanged.
- [ ] **End of phase 11:** `pytest routing/tests` passes · `python data/validate.py` passes · commit (left to Tushaar).

## Phase 12: escape rates out of a red zone

The web app times a walk out of a red zone when a Team outing starts inside blocked ground. DESIGN section 17. Nothing existing changes: the mask, the cost grids, `golden_cases.json` and `landing_zones.png` keep their bytes, and `format_version` stays 1.

- [x] **12.1** `[escape]` in `config.toml` (`zone_codes`, `risk_rate`, `max_slope_deg`, all `assumption` with sources) and copied into DESIGN section 10. The loader accepts only distinct codes from 2 to 5, `risk_rate` ≥ 0, and `max_slope_deg` in (0, 90). · `routing/config.toml`, `routing/config.py` · `test_escape.py::test_escape_config_is_three_team_assumptions`, `::test_zone_codes_never_include_no_data_or_unknown_codes`, `::test_escape_numbers_are_in_range`, `test_config.py` (DESIGN block equals the file).
- [x] **12.2** `escape_time_rate.f64` / `escape_risk_rate.f64` per tile, plus the manifest `grids` entries and the `escape` block. · `routing/escape.py`, `routing/export_landing.py` · `test_escape.py::test_zone_cells_get_finite_positive_rates_and_everything_else_minus_one_and_zero`, `::test_cells_above_max_slope_are_minus_one`, `::test_time_rate_is_the_walking_model_at_that_slope_unclipped`, `::test_zone_codes_from_the_config_are_honoured`, `::test_real_escape_rates_follow_the_rule`.
- [x] **12.3** Existing outputs unchanged: other escape settings give the same bytes for every other file, on the synthetic site and on the real data. The real files on disk match their manifest hashes and the pre-export SHA-256 (checked with `sha256sum -c`; only `manifest.json` changed). · no new file · `test_escape.py::test_escape_settings_never_change_the_existing_files`, `::test_real_existing_files_match_the_manifest_and_a_fresh_run`.
- [x] **12.4** The manifest round-trips, and a folder without the escape grids still loads (`Landing.escape` is `None`). · `routing/export_landing.py` · `test_escape.py::test_manifest_round_trips_with_the_escape_block`, `::test_an_older_folder_without_escape_grids_still_loads`, `test_export_landing.py::test_manifest_round_trips`, `::test_one_tile_size_and_total` (updated for the two grids).
- [x] **12.5** `golden_escape_cases.json`: 3 real escapes, `start_too_steep` and `no_exit` (a walled-off destination pocket), × 3 profiles, using escape.js's rule with the `start_too_steep` fix. · `routing/escape.py` · `test_escape.py::test_golden_escape_cases_have_the_expected_kinds`, `::test_replay_reproduces_the_golden_escape_cases`, `::test_escape_risk_counts_every_zone_minute`.
- [x] **12.6** Run on the shared data. · no file · `python routing/export_landing.py` (17 files, 9,695,355 bytes; 6,985 finite zone cells, 205 excluded by 35°), `pytest routing/tests` 868 passed, `python data/validate.py` exit 0.
- [ ] **End of phase 12:** commit (left to Tushaar) · web change to escape.js (Loick): never enter `escape_time_rate < 0`; a start cell < 0 → `no_exit` / `start_too_steep`; test against `golden_escape_cases.json`.
