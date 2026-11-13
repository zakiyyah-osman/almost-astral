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

- [ ] **3.1** Search wrapper returning the path, physical minutes and risk minutes separately. · `routing/search.py` · `test_search.py::test_straight_on_open_flat_grid`, `::test_flat_5m_step_is_0_111_min`, `::test_diagonal_is_root2_longer`, `::test_goes_round_red_wall`, `::test_unreachable_reported`, `::test_time_not_changed_by_w_on_same_path`.
- [ ] **3.2** Load waypoints; fail by name on a blocked or unreachable stop. · `routing/tour.py` · `test_tour.py::test_stop_on_red_names_stop`, `::test_unreachable_stop_names_stop`, `::test_needs_exactly_one_rover`.
- [ ] **3.3** Stop order, both modes. · `routing/tour.py` · `test_tour.py::test_as_listed_keeps_file_order`, `::test_optimise_minimises_balanced_cost`, `::test_tie_follows_file_order`.
- [ ] **3.4** The three profile routes. · `routing/tour.py` · `test_tour.py::test_route_is_rover_to_rover_through_all_stops`, `::test_time_fastest_le_balanced_le_safest`, `::test_risk_fastest_ge_balanced_ge_safest`.
- [ ] **End of phase 3:** `pytest routing/tests` passes · commit.

## Phase 4: shelter + storm

- [ ] **4.1** Shelter-time array, ingress included. · `routing/shelter.py` · `test_shelter.py::test_rover_cell_equals_ingress`, `::test_flat_matches_distance_over_speed`, `::test_blocked_cells_are_nan`.
- [ ] **4.2** Render the PNG with contour lines. · `routing/shelter.py` · `test_shelter.py::test_png_is_grid_sized_rgba`, `::test_blocked_cells_transparent`, `::test_contours_at_interval`.
- [ ] **4.3** Storm return table. · `routing/storm.py` · `test_storm.py::test_samples_include_every_stop`, `::test_return_path_ends_at_rover`, `::test_return_min_equals_shelter_time`, `::test_worst_point_is_maximum`.
- [ ] **End of phase 4:** `pytest routing/tests` passes · commit.

## Phase 5: timeline + radiation + outputs

- [ ] **5.1** Legs and totals. · `routing/timeline.py` · `test_timeline.py::test_total_is_walk_plus_stops_plus_ingress`, `::test_legs_chain_rover_to_rover`.
- [ ] **5.2** Budget checks and status. · `routing/timeline.py` · `test_timeline.py::test_usable_is_252_min_for_360_and_30pct`, `::test_over_reserve_flags_status`, `::test_abort_check_uses_elapsed_plus_return`.
- [ ] **5.3** Radiation. · `routing/timeline.py` · `test_timeline.py::test_background_dose_180_min_is_80_usv`, `::test_solar_event_is_8_1_mgy_in_its_own_field`, `::test_event_dose_not_added_to_sv`, `::test_csv_baseline_mismatch_warns`.
- [ ] **5.4** Track samples. · `routing/timeline.py` · `test_timeline.py::test_track_spacing`, `::test_elapsed_never_decreases`, `::test_elapsed_includes_stop_time`.
- [ ] **5.5** Writers for the three route files. · `routing/outputs.py` · `test_outputs.py::test_single_linestring_inside_extent`, `::test_no_fake_property`.
- [ ] **5.6** `plan.json` writer. · `routing/outputs.py` · `test_outputs.py::test_all_contract_keys_present`, `::test_assumptions_match_config`, `::test_two_runs_identical`.
- [ ] **5.7** Wire the entry point, with `--in DIR` (default `data/out`), `--out DIR` (default: the value of `--in`) and `--config FILE` (default `routing/config.toml`), as in DESIGN section 2. · `routing/plan_route.py` · `test_plan_route.py::test_in_out_config_options` (runs on a temp copy, `data/out` untouched); `python routing/plan_route.py` exits 0 and writes `route.geojson`, `route_fastest.geojson`, `route_safest.geojson`, `shelter_time.png` and `plan.json`; `python data/validate.py` prints `OK`.
- [ ] **End of phase 5:** `pytest routing/tests` passes · `python data/validate.py` passes · commit.

## Phase 6: sweep + sensitivity

- [ ] **6.1** w-sweep. The sweep function lives in `analysis.py`. `plan_route.py` calls it and writes the `sweep` block in `plan.json`. `analysis.py` run as a script takes `--in DIR`, `--config FILE` and `--reports DIR` (default `routing/reports`), as in DESIGN section 2; it writes `sweep.csv` and the other CSVs only and never writes to `data/out`. · `routing/analysis.py`, `routing/plan_route.py` · `test_analysis.py::test_sweep_time_rises_risk_falls`, `::test_in_config_reports_options` (runs on a temp copy, `data/out` and `routing/reports` untouched); after `python routing/plan_route.py`, `plan.json` `sweep` has 7 rows; after `python routing/analysis.py`, `routing/reports/sweep.csv` has the same 7 rows.
- [ ] **6.2** Sensitivity over `v_flat`, slope limit and w. · `routing/analysis.py` · `python routing/analysis.py` writes `routing/reports/sensitivity.csv` with 18 rows; `test_analysis.py::test_faster_v_flat_shortens_walk`.
- [ ] **6.3** Validate the hard mask against the Perseverance traverse: share of traverse points on passable cells. **Blocked until Yaj supplies the traverse in grid coordinates.** · `routing/analysis.py` · `test_analysis.py::test_traverse_share_on_synthetic_mask`; the run writes `routing/reports/validation.csv` with the number of traverse points, the number on passable cells and the share.
- [ ] **End of phase 6:** `pytest routing/tests` passes · `python data/validate.py` passes · commit.

## Phase 7: end-to-end run

- [ ] **7.1** Full rebuild, in this order. · no file · `python data/make_fake.py`, then `python routing/plan_route.py`, then `python data/validate.py` prints `OK` with no warning for `plan.json` or `route.geojson`. **`make_fake.py` overwrites `route.geojson`, `plan.json` and `shelter_time.png` with fake versions, so `plan_route.py` must always run after it.**
- [ ] **7.2** Checks on the real outputs. · `routing/tests/test_end_to_end.py` · `::test_no_route_touches_red`, `::test_route_slope_under_limit`, `::test_plan_status_ok`.
- [ ] **7.3** Site-agnostic. · `routing/tests/test_end_to_end.py` · `::test_runs_on_120x80_grid`; a search for `400`, `2000` and `5.0` in `routing/*.py` finds nothing.
- [ ] **7.4** The web app still builds. · no file · `cd web && npm run build` exits 0.
- [ ] **7.5** Update the run instructions. · `routing/README.md` · every command in it runs as written.
- [ ] **End of phase 7:** `pytest routing/tests` passes · `python data/validate.py` passes · commit · hand over to `QA.md`.
