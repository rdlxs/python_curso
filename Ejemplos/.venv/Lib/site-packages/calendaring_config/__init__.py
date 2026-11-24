"""The shared configuration file of caldav, calendaring and calendaring-jmap.

The format is specified in ``docs/format.md``.
"""

from .discovery import find_config_file, search_path, section_name
from .environment import environment_connections
from .errors import ConfigError
from .loader import Connection, expand_env_vars, expand_section, load, merged_section, read_config, section_connection

__all__ = [
    "ConfigError",
    "Connection",
    "environment_connections",
    "expand_env_vars",
    "expand_section",
    "find_config_file",
    "load",
    "merged_section",
    "read_config",
    "search_path",
    "section_connection",
    "section_name",
]
