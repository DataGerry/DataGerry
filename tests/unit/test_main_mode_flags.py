# DATAGERRY - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
Unit tests for the mode flags ``cmdb.__main__.build_arg_parser`` accepts

Three modes exist: no flag (on premise), ``--cloud`` (the hosted cloud product) and ``--cloud --local`` (the cloud
product on a developer machine). ``--local`` alone used to start an on-premise process that every licence gate took
for the cloud product - every licensed feature unlocked by one flag - so it is refused before anything starts.

**They run in a subprocess.** Importing ``cmdb.__main__`` applies the application's logging configuration at module
level, which disables every logger created before it - in the test process that would silently empty ``caplog`` for
every later test
"""
import subprocess
import sys
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
ARGPARSE_ERROR_STATUS: int = 2
# The banner line a started process prints first - never reached when the flags are refused
WELCOME_BANNER: str = 'Welcome to DataGerry'

# Parses the given argv the way ``python -m cmdb`` does, and prints the two flags it kept
PROBE: str = '''
import sys

import cmdb.__main__ as main_module

sys.argv = ['cmdb', *sys.argv[1:]]
args = main_module.build_arg_parser()
print(f'cloud={args.cloud} local={args.local}')
'''


def _refusal_message() -> str:
    """LOCAL_WITHOUT_CLOUD_MESSAGE, read in a fresh interpreter as well"""
    probe = 'import cmdb.__main__ as main_module; print(main_module.LOCAL_WITHOUT_CLOUD_MESSAGE)'

    return subprocess.run(
        [sys.executable, '-c', probe], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=True,
    ).stdout.strip().splitlines()[-1]


def _parse(*flags: str) -> subprocess.CompletedProcess:
    """Runs build_arg_parser over the flags in a fresh interpreter"""
    return subprocess.run(
        [sys.executable, '-c', PROBE, *flags], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60, check=False,
    )


@pytest.mark.parametrize('flags, expected', [
    ((), 'cloud=False local=False'),
    (('--cloud',), 'cloud=True local=False'),
    (('--cloud', '--local'), 'cloud=True local=True'),
    (('--local', '--cloud'), 'cloud=True local=True'),
], ids=['on-premise', 'hosted-cloud', 'developer-cloud', 'developer-cloud-reordered'])
def test_the_three_modes_are_accepted(flags: tuple[str, ...], expected: str) -> None:
    """Each real mode parses, whatever the order of its flags"""
    result = _parse(*flags)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith(expected)


def test_local_alone_is_refused_naming_the_rule() -> None:
    """Exit status 2 with the reason, before anything starts - not an on-premise process without licence gates"""
    result = _parse('--local')

    assert result.returncode == ARGPARSE_ERROR_STATUS
    assert _refusal_message() in result.stderr
    assert 'cloud=' not in result.stdout


def test_python_dash_m_cmdb_refuses_local_alone() -> None:
    """The real entry point: ``python -m cmdb --local`` stops at the argument check, before the banner"""
    result = subprocess.run(
        [sys.executable, '-m', 'cmdb', '--local'], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        check=False,
    )

    assert result.returncode == ARGPARSE_ERROR_STATUS
    assert _refusal_message() in result.stderr
    assert WELCOME_BANNER not in result.stdout
