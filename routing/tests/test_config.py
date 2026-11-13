import copy

import pytest

import config as cfgmod
from config import Config, ConfigError, load_config, walk_run_transition_kmh


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
