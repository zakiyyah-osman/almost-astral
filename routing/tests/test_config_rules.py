"""Value ranges, parameter names, the gravity limit and file errors for routing/config.toml."""
import copy
import math

import pytest

from config import (
    EXPECTED_PARAMS, LIST_PARAMS, Config, ConfigError, load_config, walk_run_transition_kmh,
)


@pytest.fixture
def raw():
    return copy.deepcopy(load_config().raw)


def _set(raw, key, value):
    section, name = key.split(".")
    raw[section][name]["value"] = value


def _set_bad(raw, key, bad):
    """Put `bad` into the parameter; in a list parameter it goes in the middle, not last."""
    if key in LIST_PARAMS:
        section, name = key.split(".")
        good = raw[section][name]["value"]
        _set(raw, key, [good[0], bad, good[-1]])
    else:
        _set(raw, key, bad)


NUMERIC_KEYS = [k for k in EXPECTED_PARAMS if k != "timeline.stop_order"]


# ---- NaN and inf -------------------------------------------------------------
@pytest.mark.parametrize("key", NUMERIC_KEYS)
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "-inf"])
def test_nan_and_inf_rejected_for_every_numeric_parameter(raw, key, bad):
    _set_bad(raw, key, bad)
    with pytest.raises(ConfigError, match=rf"{key}.*finite"):
        Config.from_dict(raw)


# ---- range rules: one row per rule -------------------------------------------
RANGE_RULES = [
    # key, values that must be rejected, values just inside the allowed range
    ("constraints.slope_max_deg", [0, -5, 90, 120], [0.5, 89.9]),
    ("constraints.cliff_buffer_m", [-1, -0.001], [0, 5]),
    ("risk.yellow_rate", [-0.1], [0, 2]),
    ("risk.steep_rate_max", [-0.1], [0, 2]),
    ("risk.near_red_rate_max", [-0.1], [0, 2]),
    ("risk.near_red_radius_m", [0, -1], [0.5, 30]),
    ("profiles.w_fastest", [-1, -0.001], [0, 3]),
    ("profiles.w_balanced", [-1], [0, 3]),
    ("profiles.w_safest", [-1], [0, 3]),
    ("profiles.sweep_w", [-0.5, -1e-9], [0.0, 4.0]),
    ("sensitivity.w", [-1, -0.001], [0.0, 4.0]),
    ("sensitivity.slope_max_deg", [0, -5, 90, 100], [1, 89]),
    ("timeline.optimise_max_stops", [0, -1], [1, 8, 20]),
    ("timeline.ingress_min", [-1, -0.001], [0, 20]),
    ("timeline.reserve_pct", [-1, 100, 150], [0, 99.9]),
    ("timeline.eva_max_min", [0, -60], [1, 480]),
    ("storm.sample_spacing_m", [0, -10], [1, 200]),
    ("track.spacing_m", [0, -10], [1, 50]),
    ("shelter_map.contour_interval_min", [0, -5], [1, 15]),
]
RULE_IDS = [r[0] for r in RANGE_RULES]


@pytest.mark.parametrize("key,bad,_good", RANGE_RULES, ids=RULE_IDS)
def test_range_rule_rejects(raw, key, bad, _good):
    for b in bad:
        trial = copy.deepcopy(raw)
        _set_bad(trial, key, b)
        with pytest.raises(ConfigError, match=rf"{key}: must be"):
            Config.from_dict(trial)


@pytest.mark.parametrize("key,_bad,good", RANGE_RULES, ids=RULE_IDS)
def test_range_rule_accepts_values_inside(raw, key, _bad, good):
    for g in good:
        trial = copy.deepcopy(raw)
        _set_bad(trial, key, g)
        Config.from_dict(trial)


@pytest.mark.parametrize("bad", [0, -1, 2.5, 2.0, True, "2"])
def test_crew_size_must_be_a_positive_integer(raw, bad):
    _set(raw, "crew.size", bad)
    with pytest.raises(ConfigError, match="crew.size"):
        Config.from_dict(raw)
    _set(raw, "crew.size", 4)
    Config.from_dict(raw)


# ---- the gravity limit -------------------------------------------------------
def test_speed_exactly_at_the_limit_fails(raw):
    limit = walk_run_transition_kmh(3.71, 0.9, 0.5)
    _set(raw, "walking.v_flat_kmh", limit)
    with pytest.raises(ConfigError, match="walk-run transition"):
        Config.from_dict(raw)
    _set(raw, "walking.v_flat_kmh", math.nextafter(limit, 0))
    Config.from_dict(raw)


def test_sensitivity_speed_exactly_at_the_limit_fails(raw):
    _set(raw, "sensitivity.v_flat_kmh", [2.7, walk_run_transition_kmh(3.71, 0.9, 0.5)])
    with pytest.raises(ConfigError, match=r"sensitivity.v_flat_kmh\[1\]"):
        Config.from_dict(raw)


def test_bad_sensitivity_speed_not_last_is_found(raw):
    _set(raw, "sensitivity.v_flat_kmh", [2.7, 5.0, 3.4])
    with pytest.raises(ConfigError, match=r"sensitivity.v_flat_kmh\[1\]"):
        Config.from_dict(raw)
    _set(raw, "sensitivity.v_flat_kmh", [5.0, 2.7])
    with pytest.raises(ConfigError, match=r"sensitivity.v_flat_kmh\[0\]"):
        Config.from_dict(raw)


def test_changing_gravity_moves_the_limit(raw):
    _set(raw, "walking.v_flat_kmh", 5.0)
    with pytest.raises(ConfigError, match="walk-run transition"):
        Config.from_dict(raw)                # 5.0 km/h is above the Mars limit of 4.65
    _set(raw, "walking.gravity_m_s2", 9.81)  # Earth gravity: the limit rises to about 7.56 km/h
    assert Config.from_dict(raw).transition_kmh() == pytest.approx(7.56, abs=0.01)


def test_changing_leg_length_moves_the_limit(raw):
    _set(raw, "walking.leg_length_m", 0.3)   # limit falls to about 2.68 km/h; v_flat is 2.7
    with pytest.raises(ConfigError, match="walk-run transition"):
        Config.from_dict(raw)
    _set(raw, "walking.leg_length_m", 1.2)
    assert Config.from_dict(raw).transition_kmh() == pytest.approx(5.37, abs=0.01)


def test_changing_froude_number_moves_the_limit(raw):
    _set(raw, "walking.froude_walk_run", 0.25)
    with pytest.raises(ConfigError, match="walk-run transition"):
        Config.from_dict(raw)


# ---- key and type checks outside [walking] -----------------------------------
OTHER_SECTION_KEYS = [
    "crew.size", "constraints.slope_max_deg", "risk.yellow_rate", "profiles.sweep_w",
    "sensitivity.w", "timeline.ingress_min", "radiation.limit_usv", "storm.sample_spacing_m",
    "shelter_map.colour_max_min", "track.spacing_m", "search.connectivity",
]


@pytest.mark.parametrize("key", OTHER_SECTION_KEYS)
@pytest.mark.parametrize("missing", ["value", "unit", "type", "source"])
def test_missing_key_rejected_in_any_section(raw, key, missing):
    section, name = key.split(".")
    del raw[section][name][missing]
    with pytest.raises(ConfigError, match=rf"{key}: missing {missing}"):
        Config.from_dict(raw)


@pytest.mark.parametrize("key", OTHER_SECTION_KEYS)
def test_unknown_type_rejected_in_any_section(raw, key):
    section, name = key.split(".")
    raw[section][name]["type"] = "estimate"
    with pytest.raises(ConfigError, match=rf"{key}: unknown type"):
        Config.from_dict(raw)


# ---- parameter names ---------------------------------------------------------
def test_expected_parameters_match_the_shipped_config():
    assert set(EXPECTED_PARAMS) == set(load_config().assumptions())
    assert len(EXPECTED_PARAMS) == len(set(EXPECTED_PARAMS))


def test_missing_parameter_rejected(raw):
    del raw["risk"]["yellow_rate"]
    with pytest.raises(ConfigError, match="missing parameter risk.yellow_rate"):
        Config.from_dict(raw)


def test_whole_missing_section_rejected(raw):
    del raw["storm"]
    with pytest.raises(ConfigError, match="missing parameter storm.sample_spacing_m"):
        Config.from_dict(raw)


def test_misspelt_parameter_rejected_with_both_names(raw):
    raw["risk"]["yelow_rate"] = raw["risk"].pop("yellow_rate")
    with pytest.raises(ConfigError) as e:
        Config.from_dict(raw)
    msg = str(e.value)
    assert "unknown parameter risk.yelow_rate" in msg
    assert "did you mean risk.yellow_rate" in msg
    assert "missing parameter risk.yellow_rate" in msg


def test_unknown_extra_parameter_rejected(raw):
    raw["risk"]["extra_rate"] = copy.deepcopy(raw["risk"]["yellow_rate"])
    with pytest.raises(ConfigError, match="unknown parameter risk.extra_rate"):
        Config.from_dict(raw)


def test_unknown_section_rejected(raw):
    raw["weather"] = {"temp": {"value": 1, "unit": "C", "type": "scenario", "source": "x"}}
    with pytest.raises(ConfigError, match="unknown parameter weather.temp"):
        Config.from_dict(raw)


def test_section_that_is_not_a_table_rejected(raw):
    raw["crew"] = 3
    with pytest.raises(ConfigError, match=r"\[crew\]"):
        Config.from_dict(raw)


# ---- file errors -------------------------------------------------------------
def test_missing_config_file_names_the_file(tmp_path):
    with pytest.raises(ConfigError, match=r"nope\.toml"):
        load_config(tmp_path / "nope.toml")


def test_unreadable_config_names_the_file(tmp_path):
    folder = tmp_path / "dir.toml"
    folder.mkdir()
    with pytest.raises(ConfigError, match=r"dir\.toml.*cannot read"):
        load_config(folder)


def test_invalid_toml_names_the_file(tmp_path):
    bad = tmp_path / "broken.toml"
    bad.write_text("x = [1, 2\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"broken\.toml.*invalid TOML"):
        load_config(bad)


def test_non_utf8_config_names_the_file(tmp_path):
    bad = tmp_path / "binary.toml"
    bad.write_bytes(b"\xff\xfe\x00bad")
    with pytest.raises(ConfigError, match=r"binary\.toml"):
        load_config(bad)


def test_errors_in_a_file_name_the_file(tmp_path):
    bad = tmp_path / "partial.toml"
    bad.write_text('[crew.size]\nvalue = 2\nunit = "people"\ntype = "scenario"\nsource = "x"\n')
    with pytest.raises(ConfigError, match=r"partial\.toml: .*missing parameter walking.v_flat_kmh"):
        load_config(bad)


# ---- search.connectivity and optimise_max_stops ------------------------------
@pytest.mark.parametrize("good", [4, 8])
def test_connectivity_4_and_8_accepted(raw, good):
    _set(raw, "search.connectivity", good)
    assert Config.from_dict(raw).value("search.connectivity") == good


@pytest.mark.parametrize("bad", [5, 6, 0, 1, 16, -8, 8.0, 4.5, True, False, "8", [8], None, math.nan, math.inf])
def test_connectivity_must_be_4_or_8(raw, bad):
    _set(raw, "search.connectivity", bad)
    with pytest.raises(ConfigError, match="search.connectivity"):
        Config.from_dict(raw)


def test_connectivity_error_says_what_is_allowed(raw):
    _set(raw, "search.connectivity", 6)
    with pytest.raises(ConfigError, match=r"search\.connectivity: must be one of 4, 8, got 6"):
        Config.from_dict(raw)


@pytest.mark.parametrize("bad", [8.5, 8.0, True, "8"])
def test_optimise_max_stops_must_be_an_integer(raw, bad):
    _set(raw, "timeline.optimise_max_stops", bad)
    with pytest.raises(ConfigError, match="optimise_max_stops"):
        Config.from_dict(raw)
