"""Tests for the runtime-adaptive terminal-tool description (pwsh vs bash).

Covers the two helpers added for Windows PowerShell (pwsh) support in
``tools/terminal_tool.py``:

* ``_detect_shell_for_description`` — picks ``"pwsh"`` or ``"bash"`` based on
  platform + ``HERMES_SHELL_TYPE`` + ``find_pwsh()`` (which itself may
  auto-install). ``@lru_cache``-d, so the suite clears the cache around every
  case.
* ``_build_dynamic_terminal_description`` — rewrites the LLM-facing tool
  description so its platform sentence and forbidden-command references match
  the shell actually in use.

All cases mock ``platform.system`` and ``find_pwsh`` so they run identically on
Linux CI (where the real platform is never Windows).
"""

import os
from unittest import mock

import pytest

from tools.registry import registry
from tools.terminal_tool import (
    TERMINAL_TOOL_DESCRIPTION,
    _build_dynamic_terminal_description,
    _detect_shell_for_description,
)

DETECT = "tools.terminal_tool._detect_shell_for_description"
FIND_PWSH = "tools.terminal_tool.find_pwsh"
SYSTEM = "platform.system"


@pytest.fixture(autouse=True)
def _clear_detect_cache():
    """``_detect_shell_for_description`` is lru_cached — reset around each test."""
    _detect_shell_for_description.cache_clear()
    yield
    _detect_shell_for_description.cache_clear()


def _shell_type_env(value):
    """Patch HERMES_SHELL_TYPE; ``None`` removes it (exercise the default)."""
    env = dict(os.environ)
    env.pop("HERMES_SHELL_TYPE", None)
    if value is not None:
        env["HERMES_SHELL_TYPE"] = value
    return mock.patch.dict(os.environ, env, clear=True)


# --------------------------------------------------------------------------- #
# _detect_shell_for_description
# --------------------------------------------------------------------------- #


def test_detect_non_windows_is_bash():
    with mock.patch(SYSTEM, return_value="Linux"), mock.patch(FIND_PWSH) as fp:
        assert _detect_shell_for_description() == "bash"
        fp.assert_not_called()  # never probe/auto-install off Windows


def test_detect_macos_is_bash():
    with mock.patch(SYSTEM, return_value="Darwin"):
        assert _detect_shell_for_description() == "bash"


def test_detect_windows_explicit_bash_skips_pwsh_probe():
    with mock.patch(SYSTEM, return_value="Windows"), _shell_type_env("bash"), mock.patch(FIND_PWSH) as fp:
        assert _detect_shell_for_description() == "bash"
        fp.assert_not_called()


def test_detect_windows_auto_with_pwsh_available():
    with mock.patch(SYSTEM, return_value="Windows"), _shell_type_env("auto"), mock.patch(
        FIND_PWSH, return_value=r"C:\Program Files\PowerShell\7\pwsh.exe"
    ):
        assert _detect_shell_for_description() == "pwsh"


def test_detect_windows_auto_without_pwsh_falls_back_to_bash():
    with mock.patch(SYSTEM, return_value="Windows"), _shell_type_env("auto"), mock.patch(FIND_PWSH, return_value=None):
        assert _detect_shell_for_description() == "bash"


def test_detect_windows_default_unset_behaves_as_auto():
    # HERMES_SHELL_TYPE unset → defaults to "auto" → pwsh when available.
    with mock.patch(SYSTEM, return_value="Windows"), _shell_type_env(None), mock.patch(
        FIND_PWSH, return_value=r"C:\pwsh.exe"
    ):
        assert _detect_shell_for_description() == "pwsh"


def test_detect_windows_explicit_pwsh_reports_pwsh_even_if_missing():
    # Explicit pwsh request reports "pwsh" so _resolve_shell() can raise a clear
    # error downstream, rather than silently degrading to bash.
    with mock.patch(SYSTEM, return_value="Windows"), _shell_type_env("pwsh"), mock.patch(FIND_PWSH, return_value=None):
        assert _detect_shell_for_description() == "pwsh"


def test_detect_windows_powershell_alias_available():
    with mock.patch(SYSTEM, return_value="Windows"), _shell_type_env("powershell"), mock.patch(
        FIND_PWSH, return_value=r"C:\pwsh.exe"
    ):
        assert _detect_shell_for_description() == "pwsh"


def test_detect_windows_unknown_shell_type_is_bash():
    with mock.patch(SYSTEM, return_value="Windows"), _shell_type_env("fish"), mock.patch(FIND_PWSH) as fp:
        assert _detect_shell_for_description() == "bash"
        fp.assert_not_called()


def test_detect_is_cached_until_cleared():
    with mock.patch(SYSTEM, return_value="Windows"), _shell_type_env("auto"), mock.patch(
        FIND_PWSH, return_value=r"C:\pwsh.exe"
    ) as fp:
        assert _detect_shell_for_description() == "pwsh"
        assert _detect_shell_for_description() == "pwsh"
        assert fp.call_count == 1  # second call served from lru_cache
        _detect_shell_for_description.cache_clear()
        assert _detect_shell_for_description() == "pwsh"
        assert fp.call_count == 2  # re-probed after cache_clear


# --------------------------------------------------------------------------- #
# _build_dynamic_terminal_description
# --------------------------------------------------------------------------- #


def test_build_returns_description_dict():
    with mock.patch(DETECT, return_value="bash"), mock.patch(SYSTEM, return_value="Linux"):
        out = _build_dynamic_terminal_description()
    assert isinstance(out, dict)
    assert set(out) == {"description"}
    assert isinstance(out["description"], str) and out["description"]


def test_build_pwsh_uses_powershell_sentence_and_cmdlet_refs():
    with mock.patch(DETECT, return_value="pwsh"), mock.patch(SYSTEM, return_value="Windows"):
        desc = _build_dynamic_terminal_description()["description"]
    assert "Windows PowerShell (pwsh) environment" in desc
    # pwsh-adapted forbidden-command references applied …
    assert "Do NOT use Get-Content/cat/type to read files" in desc
    assert "Do NOT use Select-String/findstr to search" in desc
    assert "Out-Host -Paging" in desc
    # … and the Linux/bash-only phrasings are gone.
    assert "Do NOT use cat/head/tail to read files" not in desc
    assert "Execute shell commands on a Linux environment." not in desc


def test_build_windows_bash_uses_git_bash_sentence():
    with mock.patch(DETECT, return_value="bash"), mock.patch(SYSTEM, return_value="Windows"):
        desc = _build_dynamic_terminal_description()["description"]
    assert "Windows Git Bash environment" in desc
    # bash path leaves the Linux command references untouched
    assert "Do NOT use cat/head/tail to read files" in desc


def test_build_non_windows_leaves_linux_references_intact():
    with mock.patch(DETECT, return_value="bash"), mock.patch(SYSTEM, return_value="Linux"):
        desc = _build_dynamic_terminal_description()["description"]
    assert "Linux environment" in desc
    assert "Do NOT use cat/head/tail to read files" in desc
    # no pwsh cmdlet substitutions on the bash/Linux path
    assert "Get-Content/cat/type" not in desc


def test_static_description_contains_phrases_the_pwsh_path_rewrites():
    # Guard against the static description drifting out from under the
    # str.replace() calls in _build_dynamic_terminal_description (a silent
    # no-op rewrite would otherwise pass the pwsh test above only by luck).
    for phrase in (
        "Execute shell commands on a Linux environment.",
        "Do NOT use cat/head/tail to read files",
        "Do NOT use grep/rg/find to search",
        "Pipe git output to cat if it might page.",
    ):
        assert phrase in TERMINAL_TOOL_DESCRIPTION


# --------------------------------------------------------------------------- #
# registry integration
# --------------------------------------------------------------------------- #


def test_terminal_registered_with_dynamic_override():
    entry = registry.get_entry("terminal")
    assert entry is not None
    assert entry.dynamic_schema_overrides is _build_dynamic_terminal_description
