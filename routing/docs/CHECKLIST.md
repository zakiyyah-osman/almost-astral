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

## Phase 8: fixed start + reach export (the single `start.xy_m` of this phase became the `[starts.*]` list in phase 9)

The walker is an astronaut on foot only. Every walk starts at the configured start (landing spot L1, temporary; phase 9 made it a list). DESIGN sections 4.9 and 13.

- [x] **8.1** `[start]`, `[reach]` in the config, checked at load: two non-negative numbers for the start, `"full"` or a valid box for the crop, a whole-number downsample ≥ 1, a true/false destination stop. · `routing/config.toml`, `routing/config.py` · `test_start.py::test_the_shipped_config_has_three_temporary_landing_spots`, `::test_a_start_must_be_two_non_negative_numbers`; `test_export_reach.py::test_crop_in_the_config_is_validated`; `test_config.py::test_config_matches_design`.
- [x] **8.2** Start validation: outside the grid and every blocked reason are errors naming the reason; yellow or slope over the onset is a warning. · `routing/start.py` · `test_start.py::test_start_outside_the_grid_fails`, `::test_blocked_start_fails_and_says_why` (red, nodata, slope, buffer, sealed), `::test_start_on_yellow_ground_only_warns`, `::test_start_on_slope_over_the_onset_only_warns`.
- [x] **8.3** Kind `rover` renamed `start`; `rover` still accepted with a logged deprecation warning that reaches `plan.json`. · `routing/tour.py` · `test_start.py::test_rover_kind_is_still_accepted_with_a_deprecation_warning`, `::test_rover_kind_warning_reaches_plan_json`, `::test_start_and_rover_together_are_two_starts`.
- [x] **8.4** One start: `plan_route.py` and `analysis.py` use the configured default start; a waypoint more than half a cell away gives a warning. Back-to-start map is "minutes back to start" (maths unchanged). · `routing/tour.py`, `plan_route.py`, `analysis.py`, `shelter.py`, `outputs.py` · `test_start.py::test_config_start_wins_and_far_waypoint_warns`, `::test_plan_starts_at_the_config_start_and_warns_about_the_waypoint`, `::test_blocked_config_start_stops_plan_route_and_writes_nothing`; the earlier phases' tests still pass with their renamed test names.
- [x] **8.5** Reach export: one search per profile from the start; time, distance, risk, direction and reason grids; manifest. · `routing/export_reach.py` · `test_export_reach.py::test_traceback_matches_the_search_path_and_totals_for_every_start`, `::test_traceback_matches_the_search_on_the_real_site_for_every_start`, `::test_time_rises_and_risk_falls_from_fastest_to_safest_for_every_start`, `::test_unreachable_reason_codes`, `::test_manifest_round_trips`, `::test_two_runs_give_identical_bytes`.
- [x] **8.6** Over-budget rule in the manifest, with the destination-stop switch. · `routing/export_reach.py` · `test_export_reach.py::test_budget_rule_is_one_way_with_one_stop_at_the_destination` (212 min), `::test_destination_stop_switch_sets_the_stop_to_zero`, `::test_over_budget_flag_follows_the_walk_limit`.
- [x] **8.7** Crop and resolution options. · `routing/export_reach.py` · `test_export_reach.py::test_crop_exports_only_the_box_and_places_every_start_in_it`, `::test_downsample_halves_the_grid_and_every_start_moves`, `::test_downsample_keeps_the_worst_hazard_and_no_data`, `::test_bad_crop_fails_clearly`, `::test_a_start_outside_the_exported_area_is_named`.
- [x] **8.8** Reference traceback documented for the front end. · `routing/export_reach.py` (`Reach.trace`), `docs/DESIGN.md` section 13.3 · `test_export_reach.py::test_trace_explains_an_unreachable_destination`, `::test_destination_at_the_start_is_a_zero_length_line`.
- [x] **8.9** Run on the shared data. · no file · `python routing/plan_route.py`, `python routing/export_reach.py` (14 files, 6,406,394 bytes in `data/out/reach/`) and `python data/validate.py` all exit 0; `validate.py` warns only about layers still marked FAKE.
- [ ] **End of phase 8:** `pytest routing/tests` passes (744 passed) · `python data/validate.py` passes · commit (left to Tushaar) · teammate follow-ups in DESIGN section 12 ("Phase 8").

## Phase 9: three selectable starts (L1, L2, L3)

The user picks a start, clicks a destination and gets the three profile paths from it. DESIGN sections 4.9 and 13. `plan_route.py` plans the full outing from the default start only.

- [x] **9.1** Config: `[starts.<id>]` tables (any number, at least one), `start.default`, and the data hashes `start.dem_sha256` / `start.hazard_sha256`; the loader checks them. · `routing/config.toml`, `routing/config.py` · `test_start.py::test_the_shipped_config_has_three_temporary_landing_spots`, `::test_a_start_must_be_two_non_negative_numbers`, `::test_a_bad_start_id_is_rejected`, `::test_the_default_must_name_a_start`, `::test_at_least_one_start_is_needed`, `::test_starts_can_be_added_and_the_default_changed`, `::test_the_hash_parameters_must_be_sha256_text`; `test_config.py::test_config_matches_design`.
- [x] **9.2** L1, L2 and L3 taken from `web/src/lib/landing.js`'s own code (`recommendLanding`, hazards from `hazard.png`) run unchanged on the current `data/out/`; the three equal walk minutes explained (DESIGN 4.9). · no file (a Node script run in the scratchpad) · `test_export_reach.py::test_the_starts_in_the_config_were_computed_on_the_current_data`.
- [x] **9.3** Every start passes the start checks; a failure names the start and why. · `routing/start.py`, `routing/tour.py` · `test_start.py::test_blocked_start_fails_and_says_why`, `::test_an_invalid_start_fails_with_its_own_name`, `::test_a_start_outside_the_grid_is_named`, `::test_resolve_start_checks_every_start_not_only_the_default`, `::test_a_bad_start_that_is_not_the_default_still_stops_plan_route`; `test_export_reach.py::test_an_invalid_start_fails_with_its_name_and_writes_nothing`, `::test_a_start_outside_the_site_is_named`.
- [x] **9.4** `plan_route.py` plans from the default start only; `plan.json` keys unchanged apart from `start.landing_id`. · `routing/tour.py`, `plan_route.py`, `outputs.py` · `test_start.py::test_the_default_start_is_the_one_resolved`, `::test_plan_route_uses_the_default_start_and_records_it`, `::test_plan_json_keys_are_unchanged_apart_from_the_start_record`.
- [x] **9.5** Reach export per start in `reach/<id>/`, and one `reach/reach.json` listing the starts and their file paths. · `routing/export_reach.py` · `test_export_reach.py::test_manifest_lists_all_starts_with_their_files`, `::test_default_flag_follows_the_config`, `::test_manifest_round_trips`, `::test_total_size_is_forty_grids_of_the_site_per_start_plus_the_manifest`, `::test_default_out_is_the_reach_folder_inside_in`.
- [x] **9.6** Reason 6 (walled off) per start. · `routing/export_reach.py` · `test_export_reach.py::test_reason_6_walled_off_can_differ_between_starts`.
- [x] **9.7** Reference trace takes a start id; DESIGN 13.3 updated. · `routing/export_reach.py` (`Reach.trace`) · `test_export_reach.py::test_traceback_matches_the_search_path_and_totals_for_every_start`, `::test_traceback_matches_the_search_on_the_real_site_for_every_start`, `::test_trace_rejects_an_unknown_start_or_profile`, `::test_module_trace_loads_the_folder_and_takes_a_start_id`.
- [x] **9.8** Data-hash staleness warning in `plan.json` and `reach.json`. · `routing/start.py` · `test_start.py::test_staleness_warns_when_the_data_is_not_the_data_the_starts_were_computed_on`, `::test_staleness_reaches_plan_json`; `test_export_reach.py::test_stale_data_hashes_give_one_manifest_warning_each_and_print_once`.
- [x] **9.9** The export deletes the old one-start files and the folders of removed starts, and lists them. · `routing/export_reach.py` · `test_export_reach.py::test_the_export_deletes_the_old_layout_and_removed_starts_and_lists_them`, `::test_a_second_run_deletes_nothing`, `::test_stale_paths_lists_only_known_names`.
- [x] **9.10** Run on the shared data. · no file · `python routing/plan_route.py`, `python routing/export_reach.py` (40 files, 19,212,728 bytes in `data/out/reach/`; it deleted the 13 old files) and `python data/validate.py` all exit 0.
- [ ] **End of phase 9:** `pytest routing/tests` passes · `python data/validate.py` passes · commit (left to Tushaar) · teammate follow-ups in DESIGN section 12 ("Phase 8" block, Loick).
