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
Machine fingerprint utility for license machine binding (license feature part P3)

Reproduces OpenCelium's MachineUtility: it collects four host identifiers - machineUuid,
macAddress, systemUUID and computerName - that bind a license to one machine. Each identifier is
read with a per-OS command (Linux / Windows / macOS); when a field cannot be resolved it degrades
to FINGERPRINT_FALLBACK ('0') rather than raising, matching OpenCelium's behaviour.

The fingerprint is deliberately fragile under container / orchestration churn (a rebuilt container
may report different values) - that fragility is inherited for parity, not a bug to fix here.

Each identifier has its own small, individually unit-testable resolver; get_machine_fingerprint()
assembles them into the camelCase-keyed dict (keyed by ActivationRequestKey) that drops straight
into an activation request
"""
import platform
import socket
import subprocess
import uuid
from pathlib import Path

from cmdb.security.license.license_constants import (
    ActivationRequestKey,
    FINGERPRINT_FALLBACK,
    PlatformName,
)
# -------------------------------------------------------------------------------------------------------------------- #

# Max seconds any single hardware-probe command may run before it is abandoned and the field falls back
COMMAND_TIMEOUT_SECONDS: int = 5

# Separator between the hex byte pairs of a formatted MAC address
MAC_ADDRESS_BYTE_SEPARATOR: str = ':'

# Bit position of the multicast flag in a 48-bit MAC; uuid.getnode() sets it when it had to invent a node
MAC_MULTICAST_BIT_SHIFT: int = 40

# Candidate files holding the persistent Linux machine id, in preference order
LINUX_MACHINE_ID_FILES: list[str] = ['/etc/machine-id', '/var/lib/dbus/machine-id']


def _run_command(command: list[str]) -> str | None:
    """
    Runs a hardware-probe command and returns its trimmed stdout

    The command never raises into the caller: a missing executable, a non-zero exit, a timeout or
    empty output all collapse to None so the calling resolver can fall back

    Args:
        command (list[str]): The command and its arguments

    Returns:
        str | None: The stripped stdout, or None if the command failed or produced no output
    """
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if completed.returncode != 0:
        return None

    output = completed.stdout.strip()

    return output or None


def _read_first_available_file(paths: list[str]) -> str | None:
    """
    Returns the trimmed contents of the first readable, non-empty file in the list

    Args:
        paths (list[str]): Candidate file paths in preference order

    Returns:
        str | None: The first non-empty file content, or None if none could be read
    """
    for path in paths:
        try:
            content = Path(path).read_text(encoding='utf-8').strip()
        except OSError:
            continue

        if content:
            return content

    return None


def _last_non_empty_line(text: str) -> str | None:
    """
    Returns the last non-empty, stripped line of a command's multi-line output

    Used for tabular tools (wmic, dmidecode) that print a header or blank padding around the value

    Args:
        text (str): The command output to scan

    Returns:
        str | None: The last non-empty line, or None if every line is blank
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    return lines[-1] if lines else None


def _token_after(text: str, marker: str) -> str | None:
    """
    Returns the whitespace-delimited token immediately following a marker token

    Used to parse `reg query` output where the value follows a type marker (e.g. 'REG_SZ')

    Args:
        text (str): The output to scan
        marker (str): The token whose successor is the wanted value

    Returns:
        str | None: The token after the marker, or None if the marker is absent or last
    """
    tokens = text.split()

    if marker in tokens:
        index = tokens.index(marker)
        if index + 1 < len(tokens):
            return tokens[index + 1]

    return None


def _value_for_label(text: str, label: str, separator: str) -> str | None:
    """
    Returns the value on the first line that contains a label, split on a separator

    Used to parse key/value tools (ioreg, system_profiler) whose lines look like
    `label <separator> value`; surrounding double quotes on the value are stripped

    Args:
        text (str): The output to scan
        label (str): The label identifying the line of interest
        separator (str): The character separating label from value

    Returns:
        str | None: The trimmed, unquoted value, or None if no matching non-empty value was found
    """
    for line in text.splitlines():
        if label in line and separator in line:
            value = line.split(separator, 1)[1].strip().strip('"')
            if value:
                return value

    return None


def get_machine_uuid() -> str:
    """
    Resolves the persistent machine id of the host

    Reads the per-OS machine identity: the machine-id file on Linux, the Cryptography MachineGuid
    on Windows and IOPlatformUUID on macOS

    Returns:
        str: The machine id, or FINGERPRINT_FALLBACK if it cannot be determined
    """
    system = platform.system()

    if system == PlatformName.LINUX:
        return _read_first_available_file(LINUX_MACHINE_ID_FILES) or FINGERPRINT_FALLBACK

    if system == PlatformName.WINDOWS:
        output = _run_command(['reg', 'query', r'HKLM\SOFTWARE\Microsoft\Cryptography', '/v', 'MachineGuid'])
        return (_token_after(output, 'REG_SZ') if output else None) or FINGERPRINT_FALLBACK

    if system == PlatformName.DARWIN:
        output = _run_command(['ioreg', '-rd1', '-c', 'IOPlatformExpertDevice'])
        return (_value_for_label(output, 'IOPlatformUUID', '=') if output else None) or FINGERPRINT_FALLBACK

    return FINGERPRINT_FALLBACK


def get_mac_address() -> str:
    """
    Resolves the primary network interface MAC address

    Uses uuid.getnode(); when that function had to invent a random node (it sets the multicast bit
    in that case) the address is not a real hardware id and the fallback is returned instead

    Returns:
        str: The colon-separated lowercase MAC, or FINGERPRINT_FALLBACK if none is available
    """
    node = uuid.getnode()

    if (node >> MAC_MULTICAST_BIT_SHIFT) & 0x01:
        return FINGERPRINT_FALLBACK

    mac_hex = f'{node:012x}'

    return MAC_ADDRESS_BYTE_SEPARATOR.join(mac_hex[index:index + 2] for index in range(0, 12, 2))


def get_system_uuid() -> str:
    """
    Resolves the hardware/system UUID of the host

    Reads the firmware system UUID via dmidecode on Linux (requires root), wmic on Windows and
    system_profiler on macOS

    Returns:
        str: The system UUID, or FINGERPRINT_FALLBACK if it cannot be determined
    """
    system = platform.system()

    if system == PlatformName.LINUX:
        output = _run_command(['dmidecode', '-s', 'system-uuid'])
        return (_last_non_empty_line(output) if output else None) or FINGERPRINT_FALLBACK

    if system == PlatformName.WINDOWS:
        output = _run_command(['wmic', 'csproduct', 'get', 'UUID'])
        return (_last_non_empty_line(output) if output else None) or FINGERPRINT_FALLBACK

    if system == PlatformName.DARWIN:
        output = _run_command(['system_profiler', 'SPHardwareDataType'])
        return (_value_for_label(output, 'Hardware UUID', ':') if output else None) or FINGERPRINT_FALLBACK

    return FINGERPRINT_FALLBACK


def get_computer_name() -> str:
    """
    Resolves the host's computer (network) name

    Returns:
        str: The hostname from platform.node(), falling back to socket.gethostname(), or
        FINGERPRINT_FALLBACK if neither yields a value
    """
    name = platform.node().strip() or socket.gethostname().strip()

    return name or FINGERPRINT_FALLBACK


def get_machine_fingerprint() -> dict[str, str]:
    """
    Assembles the four-field machine fingerprint used for license binding

    Returns:
        dict[str, str]: The fingerprint keyed by the activation-request machine fields
        (machineUuid, macAddress, systemUUID, computerName); unresolved fields hold
        FINGERPRINT_FALLBACK
    """
    return {
        ActivationRequestKey.MACHINE_UUID: get_machine_uuid(),
        ActivationRequestKey.MAC_ADDRESS: get_mac_address(),
        ActivationRequestKey.SYSTEM_UUID: get_system_uuid(),
        ActivationRequestKey.COMPUTER_NAME: get_computer_name(),
    }
