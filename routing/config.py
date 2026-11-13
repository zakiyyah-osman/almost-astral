"""Load and validate routing/config.toml.

Every parameter is a table with value, unit, type and source. The loader rejects a
file that is missing, unreadable or invalid TOML, a parameter that is missing or
misspelt (the full list is DESIGN section 10), a parameter that lacks one of its four
keys or has an unknown type, a value that is not a finite number of the right kind or
is out of range, and a walking speed at or above the walk-run limit (DESIGN sections
5 and 10).
"""
import copy
import difflib
import math
import tomllib
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "config.toml"

REQUIRED_KEYS = ("value", "unit", "type", "source")
PARAM_TYPES = ("observation", "proxy", "scenario")

# Every parameter of DESIGN section 10. A file with one missing or one more is rejected.
EXPECTED_PARAMS = (
    "crew.size",
    "walking.v_flat_kmh", "walking.tobler_k", "walking.tobler_offset", "walking.gravity_m_s2",
    "walking.leg_length_m", "walking.froude_walk_run",
    "constraints.slope_max_deg", "constraints.cliff_buffer_m",
    "risk.yellow_rate", "risk.steep_onset_deg", "risk.steep_rate_max",
    "risk.near_red_radius_m", "risk.near_red_rate_max",
    "profiles.w_fastest", "profiles.w_balanced", "profiles.w_safest", "profiles.sweep_w",
    "sensitivity.v_flat_kmh", "sensitivity.slope_max_deg", "sensitivity.w",
    "timeline.stop_order", "timeline.stop_min_default", "timeline.ingress_min",
    "timeline.eva_max_min", "timeline.reserve_pct",
    "radiation.background_dose_rate_msv_day", "radiation.limit_usv",
    "radiation.solar_event_dose_mgy", "radiation.baseline_tolerance_pct",
    "radiation.storm_detect_factor",
    "storm.sample_spacing_m",
    "shelter_map.contour_interval_min", "shelter_map.colour_max_min",
    "track.spacing_m",
    "search.connectivity",
)

# Parameters whose value is not a single number.
LIST_PARAMS = {
    "profiles.sweep_w", "sensitivity.v_flat_kmh", "sensitivity.slope_max_deg", "sensitivity.w",
}
STRING_PARAMS = {"timeline.stop_order": ("as_listed", "optimise")}
INT_PARAMS = {"crew.size"}


def _range(lo=-math.inf, hi=math.inf, lo_in=True, hi_in=True):
    return (lo, hi, lo_in, hi_in)


_POS = _range(0, lo_in=False)       # > 0
_NONNEG = _range(0)                 # >= 0

# Allowed range of each parameter (applied to every element of a list parameter).
# A parameter not listed here only has to be a finite number.
RANGES = {
    "crew.size": _POS,
    "walking.v_flat_kmh": _POS,
    "walking.gravity_m_s2": _POS,
    "walking.leg_length_m": _POS,
    "walking.froude_walk_run": _POS,
    "constraints.slope_max_deg": _range(0, 90, lo_in=False, hi_in=False),
    "constraints.cliff_buffer_m": _NONNEG,
    "risk.yellow_rate": _NONNEG,
    "risk.steep_rate_max": _NONNEG,
    "risk.near_red_radius_m": _POS,
    "risk.near_red_rate_max": _NONNEG,
    "profiles.w_fastest": _NONNEG,
    "profiles.w_balanced": _NONNEG,
    "profiles.w_safest": _NONNEG,
    "profiles.sweep_w": _NONNEG,
    "sensitivity.v_flat_kmh": _POS,
    "sensitivity.slope_max_deg": _range(0, 90, lo_in=False, hi_in=False),
    "sensitivity.w": _NONNEG,
    "timeline.ingress_min": _NONNEG,
    "timeline.eva_max_min": _POS,
    "timeline.reserve_pct": _range(0, 100, hi_in=False),
    "storm.sample_spacing_m": _POS,
    "shelter_map.contour_interval_min": _POS,
    "track.spacing_m": _POS,
}


def _describe(rng):
    lo, hi, lo_in, hi_in = rng
    if hi == math.inf:
        return f"{'>=' if lo_in else '>'} {lo:g}"
    return f"in {'[' if lo_in else '('}{lo:g}, {hi:g}{']' if hi_in else ')'}"


def _in_range(v, rng):
    lo, hi, lo_in, hi_in = rng
    return (v >= lo if lo_in else v > lo) and (v <= hi if hi_in else v < hi)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class ConfigError(ValueError):
    """The config file is malformed or breaks a physical check."""


def walk_run_transition_kmh(gravity_m_s2, leg_length_m, froude):
    """Fastest possible walk: sqrt(froude * g * leg_length), in km/h."""
    return math.sqrt(froude * gravity_m_s2 * leg_length_m) * 3.6


class Config:
    """A validated config. `raw` is the nested dict exactly as read from the file."""

    def __init__(self, raw):
        if not isinstance(raw, dict):
            raise ConfigError("config must be a table of sections")
        self.raw = copy.deepcopy(raw)
        self._check_names()
        self._validate_parameters()
        self._check_gravity()

    # -- loading -----------------------------------------------------------
    @classmethod
    def from_dict(cls, raw):
        return cls(raw)

    @classmethod
    def from_file(cls, path=None):
        path = Path(path) if path is not None else DEFAULT_PATH
        try:
            with open(path, "rb") as f:
                raw = tomllib.load(f)
        except FileNotFoundError:
            raise ConfigError(f"{path.name}: config file not found ({path})") from None
        except OSError as e:
            raise ConfigError(f"{path.name}: cannot read config file ({path}): {e}") from None
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as e:
            raise ConfigError(f"{path.name}: invalid TOML: {e}") from None
        try:
            return cls(raw)
        except ConfigError as e:
            raise ConfigError(f"{path.name}: {e}") from None

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
    def _check_names(self):
        """Every parameter of DESIGN section 10 is present, and nothing else is."""
        found = []
        for section, params in self.raw.items():
            if not isinstance(params, dict):
                raise ConfigError(f"[{section}] must be a table of parameters")
            found.extend(f"{section}.{name}" for name in params)
        missing = [k for k in EXPECTED_PARAMS if k not in found]
        unknown = [k for k in found if k not in EXPECTED_PARAMS]
        problems = []
        for k in unknown:
            hint = difflib.get_close_matches(k, missing, n=1)
            problems.append(f"unknown parameter {k}" + (f" (did you mean {hint[0]}?)" if hint else ""))
        for k in missing:
            problems.append(f"missing parameter {k}")
        if problems:
            raise ConfigError("; ".join(problems))

    def _validate_parameters(self):
        for section, params in self.raw.items():
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
                self._check_value(label, param["value"])

    @staticmethod
    def _check_number(label, v):
        if not _is_number(v):
            raise ConfigError(f"{label}: must be a number, got {v!r}")
        if not math.isfinite(v):
            raise ConfigError(f"{label}: must be a finite number, got {v!r}")
        if label in INT_PARAMS and not isinstance(v, int):
            raise ConfigError(f"{label}: must be an integer, got {v!r}")
        rng = RANGES.get(label)
        if rng is not None and not _in_range(v, rng):
            raise ConfigError(f"{label}: must be {_describe(rng)}, got {v!r}")

    @classmethod
    def _check_value(cls, label, value):
        """Finite numbers (not bool) in range, lists of them for list parameters, one string."""
        if label in STRING_PARAMS:
            allowed = STRING_PARAMS[label]
            if value not in allowed:
                raise ConfigError(f"{label}: {value!r} is not one of {', '.join(allowed)}")
        elif label in LIST_PARAMS:
            if not isinstance(value, list) or not value or not all(_is_number(v) for v in value):
                raise ConfigError(f"{label}: must be a non-empty list of numbers, got {value!r}")
            for v in value:
                cls._check_number(label, v)
        else:
            cls._check_number(label, value)

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
