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
Unit tests for cmdb.security.license.machine_fingerprint

Covers the pure output parsers (_last_non_empty_line, _token_after, _value_for_label,
_read_first_available_file), the MAC formatting / fallback logic, the per-OS branching of the
identifier resolvers (with platform.system and the command runner monkeypatched), and the shape
of the assembled fingerprint. No real subprocesses are spawned. Pure tests
"""
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pytest

from cmdb.security.license import machine_fingerprint as mf
from cmdb.security.license.license_constants import (
    ActivationRequestKey,
    FINGERPRINT_FALLBACK,
    PlatformName,
)
# -------------------------------------------------------------------------------------------------------------------- #

# A unicast, locally-resolvable MAC integer (multicast bit of the first octet clear) and its formatting
UNICAST_NODE: int = 0x001122334455
UNICAST_NODE_FORMATTED: str = '00:11:22:33:44:55'

# A MAC integer with the multicast bit set, signalling uuid.getnode() invented a random node
MULTICAST_NODE: int = 0x010000000000


# -------------------------------------------------------------------------------------------------------------------- #
#                                          command runner                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_run_command_returns_none_on_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing executable (OSError) collapses to None"""
    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError('no such command')

    monkeypatch.setattr(mf.subprocess, 'run', _raise)

    assert mf._run_command(['nope']) is None


def test_run_command_returns_none_on_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero exit code collapses to None"""
    monkeypatch.setattr(mf.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='ignored'))

    assert mf._run_command(['failing']) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                          pure output parsers                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('text,expected', [
    ('UUID\n4C4C4544-1234\n', '4C4C4544-1234'),
    ('  value-with-padding  ', 'value-with-padding'),
    ('first\nsecond\n\n  \n', 'second'),
])
def test_last_non_empty_line_returns_last_value(text: str, expected: str) -> None:
    """The last non-blank, stripped line is returned regardless of header/padding lines"""
    assert mf._last_non_empty_line(text) == expected


def test_last_non_empty_line_all_blank_is_none() -> None:
    """All-whitespace output yields None so the caller can fall back"""
    assert mf._last_non_empty_line('\n  \n\t\n') is None


@pytest.mark.parametrize('text,marker,expected', [
    ('MachineGuid    REG_SZ    abc-guid', 'REG_SZ', 'abc-guid'),
    ('only one token here', 'REG_SZ', None),
    ('trailing marker REG_SZ', 'REG_SZ', None),
])
def test_token_after(text: str, marker: str, expected: Optional[str]) -> None:
    """The token following the marker is returned, or None when absent or last"""
    assert mf._token_after(text, marker) == expected


@pytest.mark.parametrize('text,label,separator,expected', [
    ('    "IOPlatformUUID" = "ABC-123"', 'IOPlatformUUID', '=', 'ABC-123'),
    ('      Hardware UUID: XYZ-789', 'Hardware UUID', ':', 'XYZ-789'),
    ('no matching label here', 'Hardware UUID', ':', None),
    ('Hardware UUID: ', 'Hardware UUID', ':', None),
])
def test_value_for_label(text: str, label: str, separator: str, expected: Optional[str]) -> None:
    """The value after the separator on the labelled line is returned, unquoted and trimmed"""
    assert mf._value_for_label(text, label, separator) == expected


def test_read_first_available_file_prefers_first_readable(tmp_path: Path) -> None:
    """The first existing, non-empty file in the list wins"""
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.write_text('first-id\n', encoding='utf-8')
    second.write_text('second-id\n', encoding='utf-8')

    assert mf._read_first_available_file([str(first), str(second)]) == 'first-id'


def test_read_first_available_file_skips_missing_and_empty(tmp_path: Path) -> None:
    """Missing and empty files are skipped in favour of the next readable file"""
    missing = tmp_path / 'missing'
    empty = tmp_path / 'empty'
    present = tmp_path / 'present'
    empty.write_text('   \n', encoding='utf-8')
    present.write_text('real-id', encoding='utf-8')

    assert mf._read_first_available_file([str(missing), str(empty), str(present)]) == 'real-id'


def test_read_first_available_file_none_when_all_unavailable(tmp_path: Path) -> None:
    """None is returned when no candidate file can be read"""
    assert mf._read_first_available_file([str(tmp_path / 'a'), str(tmp_path / 'b')]) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                              MAC address                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_mac_address_formats_unicast_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real (unicast) hardware node is formatted as a colon-separated lowercase MAC"""
    monkeypatch.setattr(mf.uuid, 'getnode', lambda: UNICAST_NODE)

    assert mf.get_mac_address() == UNICAST_NODE_FORMATTED


def test_get_mac_address_falls_back_on_multicast_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """An invented (multicast-bit-set) node is rejected in favour of the fallback"""
    monkeypatch.setattr(mf.uuid, 'getnode', lambda: MULTICAST_NODE)

    assert mf.get_mac_address() == FINGERPRINT_FALLBACK


# -------------------------------------------------------------------------------------------------------------------- #
#                                            computer name                                                             #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_computer_name_prefers_platform_node(monkeypatch: pytest.MonkeyPatch) -> None:
    """platform.node() is used when it yields a value"""
    monkeypatch.setattr(mf.platform, 'node', lambda: 'host-a')
    monkeypatch.setattr(mf.socket, 'gethostname', lambda: 'host-b')

    assert mf.get_computer_name() == 'host-a'


def test_get_computer_name_falls_back_to_hostname(monkeypatch: pytest.MonkeyPatch) -> None:
    """socket.gethostname() backs up an empty platform.node()"""
    monkeypatch.setattr(mf.platform, 'node', lambda: '')
    monkeypatch.setattr(mf.socket, 'gethostname', lambda: 'host-b')

    assert mf.get_computer_name() == 'host-b'


def test_get_computer_name_fallback_when_both_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback token is returned when neither source yields a name"""
    monkeypatch.setattr(mf.platform, 'node', lambda: '')
    monkeypatch.setattr(mf.socket, 'gethostname', lambda: '')

    assert mf.get_computer_name() == FINGERPRINT_FALLBACK


# -------------------------------------------------------------------------------------------------------------------- #
#                                      per-OS identifier resolvers                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_machine_uuid_linux_reads_machine_id_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux the machine id is read from the machine-id file"""
    monkeypatch.setattr(mf.platform, 'system', lambda: PlatformName.LINUX.value)
    monkeypatch.setattr(mf, '_read_first_available_file', lambda paths: 'linux-machine-id')

    assert mf.get_machine_uuid() == 'linux-machine-id'


def test_get_machine_uuid_windows_parses_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows the MachineGuid is parsed out of the reg query output"""
    monkeypatch.setattr(mf.platform, 'system', lambda: PlatformName.WINDOWS.value)
    monkeypatch.setattr(mf, '_run_command', lambda command: 'MachineGuid    REG_SZ    win-guid')

    assert mf.get_machine_uuid() == 'win-guid'


def test_get_machine_uuid_darwin_parses_ioreg(monkeypatch: pytest.MonkeyPatch) -> None:
    """On macOS the machine id is parsed from the ioreg IOPlatformUUID line"""
    monkeypatch.setattr(mf.platform, 'system', lambda: PlatformName.DARWIN.value)
    monkeypatch.setattr(mf, '_run_command', lambda command: '    "IOPlatformUUID" = "MAC-MACHINE-9"')

    assert mf.get_machine_uuid() == 'MAC-MACHINE-9'


def test_get_machine_uuid_unknown_os_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised OS yields the fallback token"""
    monkeypatch.setattr(mf.platform, 'system', lambda: 'Plan9')

    assert mf.get_machine_uuid() == FINGERPRINT_FALLBACK


def test_get_machine_uuid_fallback_when_command_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed probe (None output) degrades to the fallback token"""
    monkeypatch.setattr(mf.platform, 'system', lambda: PlatformName.WINDOWS.value)
    monkeypatch.setattr(mf, '_run_command', lambda command: None)

    assert mf.get_machine_uuid() == FINGERPRINT_FALLBACK


def test_get_system_uuid_linux_uses_dmidecode(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Linux the system UUID is taken from dmidecode output"""
    monkeypatch.setattr(mf.platform, 'system', lambda: PlatformName.LINUX.value)
    monkeypatch.setattr(mf, '_run_command', lambda command: 'DEAD-BEEF-UUID')

    assert mf.get_system_uuid() == 'DEAD-BEEF-UUID'


def test_get_system_uuid_darwin_parses_hardware_uuid(monkeypatch: pytest.MonkeyPatch) -> None:
    """On macOS the Hardware UUID line of system_profiler is parsed"""
    monkeypatch.setattr(mf.platform, 'system', lambda: PlatformName.DARWIN.value)
    monkeypatch.setattr(mf, '_run_command', lambda command: '      Hardware UUID: MAC-UUID-1')

    assert mf.get_system_uuid() == 'MAC-UUID-1'


def test_get_system_uuid_windows_uses_wmic(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows the system UUID is the last line of the wmic output"""
    monkeypatch.setattr(mf.platform, 'system', lambda: PlatformName.WINDOWS.value)
    monkeypatch.setattr(mf, '_run_command', lambda command: 'UUID\nWIN-SYS-UUID')

    assert mf.get_system_uuid() == 'WIN-SYS-UUID'


def test_get_system_uuid_unknown_os_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unrecognised OS yields the fallback token"""
    monkeypatch.setattr(mf.platform, 'system', lambda: 'Plan9')

    assert mf.get_system_uuid() == FINGERPRINT_FALLBACK


def test_get_system_uuid_fallback_when_command_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed probe degrades to the fallback token"""
    monkeypatch.setattr(mf.platform, 'system', lambda: PlatformName.LINUX.value)
    monkeypatch.setattr(mf, '_run_command', lambda command: None)

    assert mf.get_system_uuid() == FINGERPRINT_FALLBACK


# -------------------------------------------------------------------------------------------------------------------- #
#                                       assembled fingerprint shape                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_machine_fingerprint_assembles_wire_keyed_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fingerprint is keyed by the activation-request machine fields and carries each resolver's value"""
    monkeypatch.setattr(mf, 'get_machine_uuid', lambda: 'm-uuid')
    monkeypatch.setattr(mf, 'get_mac_address', lambda: 'm-mac')
    monkeypatch.setattr(mf, 'get_system_uuid', lambda: 's-uuid')
    monkeypatch.setattr(mf, 'get_computer_name', lambda: 'c-name')

    fingerprint = mf.get_machine_fingerprint()

    assert fingerprint == {
        ActivationRequestKey.MACHINE_UUID: 'm-uuid',
        ActivationRequestKey.MAC_ADDRESS: 'm-mac',
        ActivationRequestKey.SYSTEM_UUID: 's-uuid',
        ActivationRequestKey.COMPUTER_NAME: 'c-name',
    }


def test_get_machine_fingerprint_keys_match_wire_strings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fingerprint dict's string keys are exactly the OpenCelium camelCase machine fields"""
    monkeypatch.setattr(mf, 'get_machine_uuid', lambda: FINGERPRINT_FALLBACK)
    monkeypatch.setattr(mf, 'get_mac_address', lambda: FINGERPRINT_FALLBACK)
    monkeypatch.setattr(mf, 'get_system_uuid', lambda: FINGERPRINT_FALLBACK)
    monkeypatch.setattr(mf, 'get_computer_name', lambda: FINGERPRINT_FALLBACK)

    assert set(mf.get_machine_fingerprint()) == {'machineUuid', 'macAddress', 'systemUUID', 'computerName'}
