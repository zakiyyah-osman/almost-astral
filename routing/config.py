"""Load and validate routing/config.toml.

Every parameter is a table with value, unit, type and source. The loader rejects a
parameter that lacks one of them or has an unknown type, and runs the walk-run
gravity check on the walking speeds (DESIGN sections 5 and 10).
"""
import copy
import math
import tomllib
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "config.toml"

REQUIRED_KEYS = ("value", "unit", "type", "source")
PARAM_TYPES = ("observation", "proxy", "scenario")


class ConfigError(ValueError):
    """The config file is malformed or breaks a physical check."""


def walk_run_transition_kmh(gravity_m_s2, leg_length_m, froude):
    """Fastest possible walk: sqrt(froude * g * leg_length), in km/h."""
    return math.sqrt(froude * gravity_m_s2 * leg_length_m) * 3.6


class Config:
    """A validated config. `raw` is the nested dict exactly as read from the file."""

    def __init__(self, raw):
        self.raw = copy.deepcopy(raw)
        self._validate_parameters()
        self._check_gravity()

    # -- loading -----------------------------------------------------------
    @classmethod
    def from_dict(cls, raw):
        return cls(raw)

    @classmethod
    def from_file(cls, path=None):
        path = Path(path) if path is not None else DEFAULT_PATH
        with open(path, "rb") as f:
            return cls(tomllib.load(f))

    # -- access ------------------------------------------------------------
    def value(self, key):
        """Value of a parameter given as 'section.name', e.g. 'walking.v_flat_kmh'."""
        section, _, name = key.partition(".")
        try:
            return self.raw[section][name]["value"]
        except KeyError:
            raise ConfigError(f"unknown parameter: {key}") from None

    def assumptions(self):
        """The whole config as {'section.name': {value, unit, type, source}}."""
        return {
            f"{section}.{name}": copy.deepcopy(param)
            for section, params in self.raw.items()
            for name, param in params.items()
        }

    # -- checks ------------------------------------------------------------
    def _validate_parameters(self):
        for section, params in self.raw.items():
            if not isinstance(params, dict):
                raise ConfigError(f"[{section}] must be a table of parameters")
            for name, param in params.items():
                label = f"{section}.{name}"
                if not isinstance(param, dict):
                    raise ConfigError(f"{label}: must be a table with value, unit, type, source")
                missing = [k for k in REQUIRED_KEYS if k not in param]
                if missing:
                    raise ConfigError(f"{label}: missing {', '.join(missing)}")
                if param["type"] not in PARAM_TYPES:
                    raise ConfigError(
                        f"{label}: unknown type {param['type']!r} "
                        f"(expected one of {', '.join(PARAM_TYPES)})"
                    )

    def transition_kmh(self):
        return walk_run_transition_kmh(
            self.value("walking.gravity_m_s2"),
            self.value("walking.leg_length_m"),
            self.value("walking.froude_walk_run"),
        )

    def _check_gravity(self):
        limit = self.transition_kmh()
        speeds = {"walking.v_flat_kmh": self.value("walking.v_flat_kmh")}
        for i, v in enumerate(self.value("sensitivity.v_flat_kmh")):
            speeds[f"sensitivity.v_flat_kmh[{i}]"] = v
        for label, v in speeds.items():
            if v >= limit:
                raise ConfigError(
                    f"{label} = {v} km/h is at or above the walk-run transition "
                    f"{limit:.2f} km/h for g = {self.value('walking.gravity_m_s2')} m/s^2"
                )


def load_config(path=None):
    return Config.from_file(path)
