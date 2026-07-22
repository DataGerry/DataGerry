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
Unit tests for the LicenseActivationRequest model and its Cerberus schema

Pins the from_data/to_json round-trip and the camelCase wire keys, that to_json survives the P5
Base64+JSON transport (so the embedded ActivationRequestKey enum keys serialize to their wire
strings), the from_data defaults, and that the SCHEMA accepts a well-formed document while
rejecting each malformed shape. Pure tests
"""
import pytest
from cerberus import Validator

from cmdb.security.license.activation_request import LicenseActivationRequest
from cmdb.security.license.license_constants import ActivationRequestKey, ActivationRequestStatus
from cmdb.security.license.transport import decode_json, encode_json
# -------------------------------------------------------------------------------------------------------------------- #

TTL_SECONDS: int = 3600

# A well-formed activation-request document keyed by the wire keys
VALID_REQUEST: dict = {
    ActivationRequestKey.ID: 'eff042a1-b9db-43b3-855d-b62d712ce4c9',
    ActivationRequestKey.HMAC: 'C6VD+atCNUYDIeWdMbJRGkzDbcFp5n87tcAbnxcZJeU=',
    ActivationRequestKey.TTL: TTL_SECONDS,
    ActivationRequestKey.STATUS: ActivationRequestStatus.PENDING.value,
    ActivationRequestKey.MACHINE_UUID: 'machine-1',
    ActivationRequestKey.MAC_ADDRESS: '00:11:22:33:44:55',
    ActivationRequestKey.SYSTEM_UUID: 'system-1',
    ActivationRequestKey.COMPUTER_NAME: 'host-1',
}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          model serialization                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_from_data_to_json_round_trip() -> None:
    """A wire dict survives from_data -> to_json unchanged"""
    request = LicenseActivationRequest.from_data(VALID_REQUEST)

    assert LicenseActivationRequest.to_json(request) == VALID_REQUEST


def test_to_json_uses_camelcase_wire_keys() -> None:
    """to_json emits exactly the eight camelCase activation-request keys"""
    request = LicenseActivationRequest.from_data(VALID_REQUEST)

    assert set(LicenseActivationRequest.to_json(request)) == set(ActivationRequestKey)


def test_to_blob_dict_excludes_lifecycle_fields() -> None:
    """to_blob_dict emits only the six request-file fields, omitting ttl and status"""
    request = LicenseActivationRequest.from_data(VALID_REQUEST)

    blob = LicenseActivationRequest.to_blob_dict(request)

    assert set(blob) == {
        ActivationRequestKey.ID,
        ActivationRequestKey.HMAC,
        ActivationRequestKey.MACHINE_UUID,
        ActivationRequestKey.MAC_ADDRESS,
        ActivationRequestKey.SYSTEM_UUID,
        ActivationRequestKey.COMPUTER_NAME,
    }
    assert ActivationRequestKey.TTL not in blob
    assert ActivationRequestKey.STATUS not in blob
    assert blob[ActivationRequestKey.ID] == VALID_REQUEST[ActivationRequestKey.ID]


def test_to_json_survives_base64_json_transport() -> None:
    """The enum-keyed to_json dict serializes through P5 transport to plain camelCase string keys"""
    request = LicenseActivationRequest.from_data(VALID_REQUEST)

    decoded = decode_json(encode_json(LicenseActivationRequest.to_json(request)))

    assert decoded['machineUuid'] == 'machine-1'
    assert decoded['status'] == ActivationRequestStatus.PENDING.value
    assert set(decoded) == {key.value for key in ActivationRequestKey}


def test_init_from_fingerprint_dict() -> None:
    """Constructing from a fingerprint dict (P3 output shape) populates the four machine fields"""
    fingerprint = {
        ActivationRequestKey.MACHINE_UUID: 'm-uuid',
        ActivationRequestKey.MAC_ADDRESS: 'm-mac',
        ActivationRequestKey.SYSTEM_UUID: 's-uuid',
        ActivationRequestKey.COMPUTER_NAME: 'c-name',
    }

    request = LicenseActivationRequest('id-1', 'hmac-1', TTL_SECONDS, fingerprint)

    assert request.machine_uuid == 'm-uuid'
    assert request.computer_name == 'c-name'
    assert request.status == ActivationRequestStatus.PENDING.value


def test_from_data_applies_defaults() -> None:
    """Missing status defaults to PENDING and missing machine fields default to empty strings"""
    request = LicenseActivationRequest.from_data({
        ActivationRequestKey.ID: 'id-1',
        ActivationRequestKey.HMAC: 'hmac-1',
        ActivationRequestKey.TTL: TTL_SECONDS,
    })

    assert request.status == ActivationRequestStatus.PENDING.value
    assert request.machine_uuid == ''
    assert request.computer_name == ''


# -------------------------------------------------------------------------------------------------------------------- #
#                                            schema validation                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_schema_accepts_valid_document() -> None:
    """The SCHEMA accepts a well-formed activation-request document"""
    validator = Validator(LicenseActivationRequest.SCHEMA)

    assert validator.validate(VALID_REQUEST) is True


@pytest.mark.parametrize('mutation,reason', [
    ({ActivationRequestKey.HMAC: None}, 'missing required hmac'),
    ({ActivationRequestKey.STATUS: 'UNKNOWN'}, 'status not in allowed set'),
    ({ActivationRequestKey.TTL: 0}, 'ttl below minimum'),
    ({ActivationRequestKey.TTL: 'soon'}, 'ttl wrong type'),
    ({ActivationRequestKey.MACHINE_UUID: ''}, 'empty machine field'),
])
def test_schema_rejects_malformed_document(mutation: dict, reason: str) -> None:
    """The SCHEMA rejects each malformed activation-request shape"""
    document = dict(VALID_REQUEST)
    for key, value in mutation.items():
        if value is None:
            del document[key]
        else:
            document[key] = value

    validator = Validator(LicenseActivationRequest.SCHEMA)

    assert validator.validate(document) is False


def test_schema_rejects_unknown_field() -> None:
    """The SCHEMA rejects an unexpected extra field (Cerberus default-deny on unknowns)"""
    document = dict(VALID_REQUEST)
    document['unexpected'] = 'x'

    validator = Validator(LicenseActivationRequest.SCHEMA)

    assert validator.validate(document) is False
