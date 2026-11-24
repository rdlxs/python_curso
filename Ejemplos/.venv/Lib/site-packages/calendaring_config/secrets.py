"""``_command`` and ``_keyring`` secrets (docs/format.md, "Secrets").

No message raised here contains a secret or a command's output.
"""

import os
import subprocess
from pathlib import Path
from typing import Any

from .errors import ConfigError

__all__ = ["SECRETS", "resolve_secrets"]

SECRETS = ("password", "token")
COMMAND_TIMEOUT = 60  # seconds; a helper waiting on a pinentry gets this long


def _check_file_is_safe(path: Path | None, section: str, key: str) -> None:
    if path is None:  # from the environment, which cannot give a list
        return
    try:
        st = path.stat()
    except OSError as e:
        raise ConfigError(f"cannot check {path} before running {key} of section {section}: {e.strerror}") from None
    if st.st_uid not in (os.getuid(), 0):
        raise ConfigError(f"{path} is owned by uid {st.st_uid}; refusing to run {key} of section {section}")
    if st.st_mode & 0o022:
        raise ConfigError(f"{path} is writable by group or others; refusing to run {key} of section {section}")


def _run(command: Any, section: str, key: str, path: Path | None) -> str:
    if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
        raise ConfigError(f"{key} of section {section} must be a list of the program and its arguments")
    _check_file_is_safe(path, section, key)
    try:
        # stderr is left on the terminal: it is not the secret, and it says why a helper failed
        result = subprocess.run(command, stdout=subprocess.PIPE, text=True, check=False, timeout=COMMAND_TIMEOUT)
    except OSError as e:
        raise ConfigError(f"{key} of section {section}: cannot run {command[0]}: {e.strerror}") from e
    except subprocess.TimeoutExpired:
        raise ConfigError(f"{key} of section {section} did not finish in {COMMAND_TIMEOUT} s") from None
    if result.returncode != 0:
        raise ConfigError(f"{key} of section {section} exited with status {result.returncode}")
    out = result.stdout
    return out[:-2] if out.endswith("\r\n") else out.removesuffix("\n")


def _look_up(service: Any, username: Any, section: str, key: str) -> str:
    if username is None:
        raise ConfigError(f"{key} of section {section} needs a username")
    try:
        import keyring
        import keyring.errors
    except ImportError:
        raise ConfigError(
            f"{key} of section {section} needs the keyring package (calendaring-config[keyring])"
        ) from None
    try:
        secret = keyring.get_password(str(service), str(username))
    except keyring.errors.KeyringError as e:
        raise ConfigError(f"{key} of section {section}: the keyring failed: {type(e).__name__}") from None
    if secret is None:
        raise ConfigError(f"{key} of section {section}: no keyring entry for service {service}")
    return secret


def resolve_secrets(section: str, params: dict[str, Any], path: Path | None) -> None:
    """Replace ``password_command``, ``token_keyring`` and the like in ``params`` with the secret."""
    for secret in SECRETS:
        command, keyring_key = f"{secret}_command", f"{secret}_keyring"
        sources = [k for k in (secret, command, keyring_key) if k in params]
        if len(sources) > 1:
            raise ConfigError(f"section {section} gives {secret} more than once: {', '.join(sources)}")
        if command in params:
            params[secret] = _run(params.pop(command), section, command, path)
        elif keyring_key in params:
            params[secret] = _look_up(params.pop(keyring_key), params.get("username"), section, keyring_key)
