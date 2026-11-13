import copy
import re
import tomllib
from pathlib import Path

import pytest

from config import Config, ConfigError, load_config, walk_run_transition_kmh

DESIGN = Path(__file__).resolve().parents[1] / "docs" / "DESIGN.md"


@pytest.fixture
def raw():
    return copy.deepcopy(load_config().raw)


def test_every_parameter_has_four_keys(raw):
    cfg = load_config()
    assert len(cfg.assumptions()) > 30
    for key, param in cfg.assumptions().items():
        for k in ("value", "unit", "type", "source"):
            assert k in param, f"{key} lacks {k}"
    # A parameter missing any one key is rejected, naming the parameter and the key.
    for k in ("value", "unit", "type", "source"):
        bad = copy.deepcopy(raw)
        del bad["walking"]["v_flat_kmh"][k]
        with pytest.raises(ConfigError, match=rf"walking\.v_flat_kmh.*{k}"):
            Config.from_dict(bad)


def test_unknown_type_rejected(raw):
    raw["walking"]["v_flat_kmh"]["type"] = "guess"
    with pytest.raises(ConfigError, match="unknown type"):
        Config.from_dict(raw)


def test_walk_run_transition_is_4_65_kmh():
    assert walk_run_transition_kmh(3.71, 0.9, 0.5) == pytest.approx(4.65, abs=0.005)
    assert load_config().transition_kmh() == pytest.approx(4.65, abs=0.005)
    # The shipped speeds pass.
    cfg = load_config()
    assert cfg.value("walking.v_flat_kmh") == 2.7
    assert cfg.value("sensitivity.v_flat_kmh") == [2.7, 3.4]


def test_v_flat_above_transition_fails(raw):
    raw["walking"]["v_flat_kmh"]["value"] = 4.7
    with pytest.raises(ConfigError, match="walk-run transition"):
        Config.from_dict(raw)


def test_sensitivity_speed_above_transition_fails(raw):
    raw["sensitivity"]["v_flat_kmh"]["value"] = [2.7, 5.0]
    with pytest.raises(ConfigError, match="sensitivity.v_flat_kmh"):
        Config.from_dict(raw)


@pytest.mark.parametrize("bad", ["2.7", True, None, [2.7]])
def test_scalar_parameter_must_be_a_number(raw, bad):
    raw["walking"]["v_flat_kmh"]["value"] = bad
    with pytest.raises(ConfigError, match="walking.v_flat_kmh"):
        Config.from_dict(raw)


def test_bool_rejected_for_other_numeric_parameters(raw):
    raw["timeline"]["ingress_min"]["value"] = False
    with pytest.raises(ConfigError, match="timeline.ingress_min"):
        Config.from_dict(raw)


@pytest.mark.parametrize("bad", [3.4, "x", [], [2.7, "3.4"], [2.7, True]])
def test_list_parameter_must_be_list_of_numbers(raw, bad):
    raw["sensitivity"]["v_flat_kmh"]["value"] = bad
    with pytest.raises(ConfigError, match="sensitivity.v_flat_kmh"):
        Config.from_dict(raw)


def test_sweep_list_must_be_list_of_numbers(raw):
    raw["profiles"]["sweep_w"]["value"] = [0.0, "1.0"]
    with pytest.raises(ConfigError, match="profiles.sweep_w"):
        Config.from_dict(raw)


@pytest.mark.parametrize("bad", [0, 0.0, -1.0])
def test_v_flat_must_be_positive(raw, bad):
    raw["walking"]["v_flat_kmh"]["value"] = bad
    with pytest.raises(ConfigError, match="must be > 0"):
        Config.from_dict(raw)


@pytest.mark.parametrize("bad", [[0.0, 3.4], [2.7, -3.4]])
def test_sensitivity_speeds_must_be_positive(raw, bad):
    raw["sensitivity"]["v_flat_kmh"]["value"] = bad
    with pytest.raises(ConfigError, match="sensitivity.v_flat_kmh"):
        Config.from_dict(raw)


@pytest.mark.parametrize("key", ["gravity_m_s2", "leg_length_m", "froude_walk_run"])
def test_gravity_inputs_must_be_positive(raw, key):
    raw["walking"][key]["value"] = -1.0
    with pytest.raises(ConfigError, match=key):
        Config.from_dict(raw)


def test_stop_order_must_be_a_known_mode(raw):
    raw["timeline"]["stop_order"]["value"] = "random"
    with pytest.raises(ConfigError, match="timeline.stop_order"):
        Config.from_dict(raw)
    raw["timeline"]["stop_order"]["value"] = "optimise"
    Config.from_dict(raw)


def test_config_matches_design():
    """The TOML block in DESIGN.md section 10 parses equal to routing/config.toml."""
    text = DESIGN.read_text(encoding="utf-8")
    section = text.split("## 10.", 1)[1].split("\n## ", 1)[0]
    blocks = re.findall(r"```toml\n(.*?)```", section, re.S)
    assert len(blocks) == 1
    assert tomllib.loads(blocks[0]) == load_config().raw
