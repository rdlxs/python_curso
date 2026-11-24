"""Reading the file and turning a section name into connections (docs/format.md)."""

import json
import os
import re
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

from .discovery import expand_path, find_config_file, requested_section, section_name
from .environment import apply_environment, environment_connections, wanted_kinds
from .errors import ConfigError
from .secrets import SECRETS, resolve_secrets

__all__ = [
    "Connection",
    "expand_env_vars",
    "expand_section",
    "load",
    "merged_section",
    "read_config",
    "section_connection",
]

Config = dict[str, dict[str, Any]]

STRUCTURAL_KEYS = ("contains", "inherits", "disable")
OLD_PREFIX = "caldav_"
OLD_ALIASES = {"user": "username", "pass": "password"}
GLOB_CHARACTERS = frozenset("*?[")


def _is_new_style_key(key: str) -> bool:
    """A connection key an old-style section must spell with the prefix; other plain keys may stand beside it."""
    return key in ("url", "username", *SECRETS) or key.endswith(("_command", "_keyring"))


def _looks_secret(key: str) -> bool:
    """Masked in a ``repr``: the secrets, and keys named like one."""
    return key in SECRETS or any(w in key for w in ("pass", "token", "secret")) or key.endswith("_key")


@dataclass(frozen=True)
class Connection:
    """One backend: its section, its kind, and the keyword arguments for its ``connect()``.

    ``kind`` is ``None`` when the section names none; the reader then decides
    from ``params["url"]``.  Secrets in ``params`` are resolved, and masked in
    the ``repr``.
    """

    name: str
    kind: str | None
    params: dict[str, Any]

    def __repr__(self) -> str:
        shown = {k: "***" if _looks_secret(k) else v for k, v in self.params.items()}
        return f"Connection(name={self.name!r}, kind={self.kind!r}, params={shown!r})"


def read_config(path: str | Path) -> Config:
    """The file's sections: JSON, else YAML read with a safe loader."""
    try:
        with open(expand_path(path), "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ConfigError(f"cannot read {path}: {e.strerror}") from e
    try:
        data = json.loads(raw)
    except ValueError:
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            raise ConfigError(f"{path} is neither valid JSON nor YAML: {e}") from e
    if data is None:
        return {}
    if (
        not isinstance(data, dict)
        or not all(isinstance(k, str) for k in data)
        or not all(isinstance(v, dict) for v in data.values())
    ):
        raise ConfigError(f"{path} must be a mapping of section names to sections")
    return data


def _is_meta(config: Config, name: str) -> bool:
    return "contains" in config[name]


def _is_disabled(config: Config, name: str) -> bool:
    return bool(config[name].get("disable", False))


def _matches(config: Config, pattern: str) -> list[str]:
    return [s for s in config if fnmatchcase(s, pattern)]


def _expand(config: Config, name: str, seen: set[str], out: list[str], missing: list[str]) -> None:
    if name in seen:
        return
    seen.add(name)
    if _is_disabled(config, name):
        return
    if not _is_meta(config, name):
        out.append(name)
        return
    members = config[name]["contains"]
    if not isinstance(members, list) or not all(isinstance(m, str) for m in members):
        raise ConfigError(f"contains of section {name} must be a list of section names")
    for member in members:
        if GLOB_CHARACTERS & set(member):
            found = _matches(config, member)
        else:
            found = [member] if member in config else []
        if not found:
            missing.append(f"section {name} contains {member}, which matches no section")
        for match in found:
            _expand(config, match, seen, out, missing)


def expand_section(config: Config, name: str) -> list[str]:
    """The leaf sections ``name`` stands for: itself, a meta-section's members, ``*`` or a glob."""
    if name == "*":
        return [s for s in config if not _is_meta(config, s) and not _is_disabled(config, s)]
    if GLOB_CHARACTERS & set(name):
        roots = _matches(config, name)
        if not roots:
            raise ConfigError(f"no section matches {name}")
    elif name not in config:
        raise ConfigError(f"no section named {name}")
    elif _is_disabled(config, name):
        raise ConfigError(f"section {name} is disabled")
    else:
        roots = [name]
    out: list[str] = []
    seen: set[str] = set()
    missing: list[str] = []
    for root in roots:
        _expand(config, root, seen, out, missing)
    for message in missing:
        warnings.warn(message, UserWarning, stacklevel=2)
    return out


def _own_kind(section: dict[str, Any]) -> str | None:
    if "kind" in section:
        return str(section["kind"])
    if any(k.startswith(OLD_PREFIX) for k in section):
        return "caldav"
    return None


def _merged(config: Config, name: str, chain: tuple[str, ...] = ()) -> dict[str, Any]:
    if name in chain:
        raise ConfigError(f"inheritance cycle: {' -> '.join((*chain, name))}")
    if name not in config:
        if not chain:
            raise ConfigError(f"no section named {name}")
        raise ConfigError(f"section {chain[-1]} inherits from {name}, which does not exist")
    own = config[name]
    if "inherits" not in own:
        return dict(own)
    parent_name = own["inherits"]
    if not isinstance(parent_name, str):
        raise ConfigError(f"inherits of section {name} must be a section name")
    parent = _merged(config, parent_name, (*chain, name))
    child_kind, parent_kind = _own_kind(own), _own_kind(parent)
    if child_kind and parent_kind and child_kind != parent_kind:
        raise ConfigError(f"section {name} (kind {child_kind}) inherits from {parent_name} (kind {parent_kind})")
    for key in ("contains", "disable"):
        parent.pop(key, None)
    return {**parent, **own}


def merged_section(config: Config, name: str) -> dict[str, Any]:
    """Section ``name`` with what it ``inherits`` copied in.

    ``inherits`` itself is left out, and so are the parents' ``contains``
    and ``disable``, so a leaf can go to ``section_connection()``.  The
    section's own ``contains`` and ``disable`` are kept: a meta-section is
    still refused there, and the caller can see that a section is disabled.
    The result is a shallow copy; ``config`` is not modified.

    It exists for caldav's ``config_section()``, and may be deprecated
    once plann no longer uses that function
    (https://github.com/PyCalendar/plann/issues/84).  Callers that can
    should use ``load()``, which does the whole walk.
    """
    return {k: v for k, v in _merged(config, name).items() if k != "inherits"}


def expand_env_vars(value: Any) -> Any:
    """``${VAR}`` and ``${VAR:-default}`` in strings, recursively.  The default applies only when VAR is unset."""
    if isinstance(value, str):
        return re.sub(r"\$\{([^}:]+)(?::-([^}]*))?\}", lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: expand_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env_vars(v) for v in value]
    return value


def _normalise(name: str, section: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    """The section's kind, and its keys with structural keys removed, the old prefix dropped and nulls left out."""
    params = expand_env_vars({k: v for k, v in section.items() if k not in STRUCTURAL_KEYS})
    kind = params.pop("kind", None)
    if kind is not None and not isinstance(kind, str):
        raise ConfigError(f"kind of section {name} must be a string")
    if any(k.startswith(OLD_PREFIX) for k in params):
        new = sorted(k for k in params if not k.startswith(OLD_PREFIX) and _is_new_style_key(k))
        if new:
            raise ConfigError(f"section {name} mixes caldav_* keys with {', '.join(new)}")
        if kind not in (None, "caldav"):
            raise ConfigError(f"section {name} has caldav_* keys but kind {kind}")
        kind = "caldav"
        renamed: dict[str, Any] = {}
        for k, v in params.items():
            if k.startswith(OLD_PREFIX):
                k = k.removeprefix(OLD_PREFIX)
                k = OLD_ALIASES.get(k, k)
            renamed[k] = v
        params = renamed
    return kind, {k: v for k, v in params.items() if v is not None}


def section_connection(name: str, section: dict[str, Any], path: str | Path | None = None) -> Connection:
    """One section, already merged with what it ``inherits``, as a connection.

    For a reader that walks the file itself.  ``path`` must be the file the
    section really came from: a ``_command`` is run only after that file has
    been checked, so without it a command is an error.  No environment
    variable is applied.  Every other key is passed through, for the backend
    to check.
    """
    if not isinstance(section, dict):
        raise ConfigError(f"section {name} must be a mapping")
    structural = sorted(k for k in ("inherits", "contains") if k in section)
    if structural:
        raise ConfigError(f"section {name} has {', '.join(structural)}: pass it merged, as a leaf")
    kind, params = _normalise(name, section)
    if path is None and any(f"{secret}_command" in params for secret in SECRETS):
        raise ConfigError(f"section {name}: a _command needs the file the section came from")
    resolve_secrets(name, params, expand_path(path) if path is not None else None)
    return Connection(name, kind, params)


def load(
    path: str | Path | None = None,
    section: str | None = None,
    environment: bool = True,
    kinds: Iterable[str] | None = None,
) -> list[Connection]:
    """The connections a section stands for, ready for each backend's ``connect()``.

    A URL in the environment (``CALDAV_URL``, ``JMAP_URL``) replaces the file.
    No file and no such variable means no connections, and so does a file
    without a ``default`` section when no section was asked for.  With
    ``environment=False`` no ``CALDAV_*``, ``JMAP_*`` or ``CALENDARING_*``
    variable is read.  A reader of some kinds only passes ``kinds``: then
    only the URL of such a kind replaces the file, and only sections of
    those kinds, or of none, are returned.
    """
    chosen = wanted_kinds(kinds)
    from_environment = environment_connections(chosen) if environment else []
    if from_environment:
        return [Connection("environment", kind, params) for kind, params in from_environment]
    file = find_config_file(path, environment)
    if file is None:
        return []
    config = read_config(file)
    name = section_name(section, environment)
    if requested_section(section, environment) is None and name not in config:
        return []
    leaves = expand_section(config, name)
    connections = []
    for leaf in leaves:
        kind, params = _normalise(leaf, _merged(config, leaf))
        if chosen is not None and kind is not None and kind not in chosen:
            continue
        if environment and len(leaves) == 1 and kind is not None:
            apply_environment(kind, params)
        resolve_secrets(leaf, params, file)
        connections.append(Connection(leaf, kind, params))
    return connections
