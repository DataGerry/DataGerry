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
Unit tests for cmdb.security.license.hmac_binding

The headline test is a byte-for-byte parity check against the real OpenCelium sample: the same
secret, machine placeholders and id must reproduce the exact Base64 digest observed in the wild.
The rest pin the contract that makes that work - id goes LAST, the fields are concatenated with no
separators, the digest is deterministic, and constant_time_equals behaves like equality. Pure tests
"""
from cmdb.security.license.hmac_binding import (
    compute_hmac,
    constant_time_equals,
    machine_binding_hmac,
)
from cmdb.security.license.license_constants import ActivationRequestKey
# -------------------------------------------------------------------------------------------------------------------- #

# The reverse-engineered OpenCelium secret (parity reference only; DataGerry ships its own secret)
OPENCELIUM_SECRET: str = 'my-secret-key'

# The placeholder machine fingerprint used by OpenCelium's FREE/default activation request
PLACEHOLDER_FINGERPRINT: dict[str, str] = {
    ActivationRequestKey.MACHINE_UUID: 'MACHINE_UUID',
    ActivationRequestKey.MAC_ADDRESS: 'MAC_ADDRESS',
    ActivationRequestKey.SYSTEM_UUID: 'SYSTEM_UUID',
    ActivationRequestKey.COMPUTER_NAME: 'COMPUTER_NAME',
}

# The id and resulting HMAC observed in the real OpenCelium free-license sample
SAMPLE_REQUEST_ID: str = 'eff042a1-b9db-43b3-855d-b62d712ce4c9'
SAMPLE_EXPECTED_HMAC: str = 'I1I3lY7IQ4jC6j073BHzsp92G58Imds4YwM1/tGbLq8='


# -------------------------------------------------------------------------------------------------------------------- #
#                                        OpenCelium parity vector                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_machine_binding_hmac_reproduces_opencelium_sample() -> None:
    """The binding HMAC matches the real OpenCelium sample byte-for-byte (verified wire format)"""
    result = machine_binding_hmac(PLACEHOLDER_FINGERPRINT, SAMPLE_REQUEST_ID, secret=OPENCELIUM_SECRET)

    assert result == SAMPLE_EXPECTED_HMAC


def test_compute_hmac_matches_manual_message_for_sample() -> None:
    """machine_binding_hmac equals compute_hmac over fields-then-id (the message assembly contract)"""
    message = 'MACHINE_UUID' + 'MAC_ADDRESS' + 'SYSTEM_UUID' + 'COMPUTER_NAME' + SAMPLE_REQUEST_ID

    assert compute_hmac(message, secret=OPENCELIUM_SECRET) == SAMPLE_EXPECTED_HMAC


# -------------------------------------------------------------------------------------------------------------------- #
#                                          message-order contract                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_request_id_goes_last() -> None:
    """Putting the id first (instead of last) yields a different digest - id LAST is load-bearing"""
    id_last = machine_binding_hmac(PLACEHOLDER_FINGERPRINT, SAMPLE_REQUEST_ID, secret=OPENCELIUM_SECRET)
    id_first_message = SAMPLE_REQUEST_ID + 'MACHINE_UUIDMAC_ADDRESSSYSTEM_UUIDCOMPUTER_NAME'
    id_first = compute_hmac(id_first_message, secret=OPENCELIUM_SECRET)

    assert id_last != id_first


def test_different_fingerprint_changes_hmac() -> None:
    """A change in any machine field changes the binding HMAC"""
    other = dict(PLACEHOLDER_FINGERPRINT)
    other[ActivationRequestKey.MACHINE_UUID] = 'OTHER_MACHINE'

    baseline = machine_binding_hmac(PLACEHOLDER_FINGERPRINT, SAMPLE_REQUEST_ID, secret=OPENCELIUM_SECRET)
    changed = machine_binding_hmac(other, SAMPLE_REQUEST_ID, secret=OPENCELIUM_SECRET)

    assert baseline != changed


# -------------------------------------------------------------------------------------------------------------------- #
#                                       determinism & default secret                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_compute_hmac_is_deterministic() -> None:
    """The same message and secret always produce the same digest"""
    assert compute_hmac('payload') == compute_hmac('payload')


def test_compute_hmac_uses_shipped_secret_by_default() -> None:
    """Omitting the secret uses the shipped LICENSE_HMAC_SECRET, differing from the parity secret"""
    assert compute_hmac('payload') != compute_hmac('payload', secret=OPENCELIUM_SECRET)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          constant_time_equals                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
def test_constant_time_equals_true_for_equal() -> None:
    """constant_time_equals returns True for identical strings"""
    assert constant_time_equals(SAMPLE_EXPECTED_HMAC, SAMPLE_EXPECTED_HMAC) is True


def test_constant_time_equals_false_for_different() -> None:
    """constant_time_equals returns False for differing strings"""
    assert constant_time_equals(SAMPLE_EXPECTED_HMAC, 'not-the-same') is False
