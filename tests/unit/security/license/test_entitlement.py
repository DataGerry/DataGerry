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
Unit tests for the LicenseEntitlement model and its Cerberus schema

Pins the from_data/to_json round-trip and camelCase wire keys, that to_json survives the P5
transport, the from_data defaults, and that the SCHEMA accepts a well-formed entitlement while
rejecting each malformed shape. Also cross-checks that the P7 generator's build_entitlement output
conforms to this schema (generator and model agree on the wire contract). Pure tests
"""
import pytest
from cerberus import Validator

from cmdb.security.license.entitlement import LicenseEntitlement
from cmdb.security.license.license_constants import LicenseEntitlementKey, LicenseFeature, LicenseTier
from cmdb.security.license.transport import decode_json, encode_json
from cmdb.security.license.tooling.license_generator import build_entitlement
# -------------------------------------------------------------------------------------------------------------------- #

# A well-formed entitlement document keyed by the wire keys (mirrors the OpenCelium free sample)
VALID_ENTITLEMENT: dict = {
    LicenseEntitlementKey.HMAC: 'C6VD+atCNUYDIeWdMbJRGkzDbcFp5n87tcAbnxcZJeU=',
    LicenseEntitlementKey.START_DATE: 1640995200000,
    LicenseEntitlementKey.END_DATE: 0,
    LicenseEntitlementKey.SUB_ID: 'sub-1',
    LicenseEntitlementKey.LICENSE_ID: 'lic-1',
    LicenseEntitlementKey.OPERATION_USAGE: 25000,
    LicenseEntitlementKey.DURATION: 0,
    LicenseEntitlementKey.TYPE: LicenseTier.CORE.value,
    LicenseEntitlementKey.FEATURES: [LicenseFeature.REST_API.value, LicenseFeature.IPAM.value],
}


# -------------------------------------------------------------------------------------------------------------------- #
#                                          model serialization                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_from_data_to_json_round_trip() -> None:
    """A wire dict survives from_data -> to_json unchanged"""
    entitlement = LicenseEntitlement.from_data(VALID_ENTITLEMENT)

    assert LicenseEntitlement.to_json(entitlement) == VALID_ENTITLEMENT


def test_to_json_uses_camelcase_wire_keys() -> None:
    """to_json emits exactly the camelCase entitlement keys"""
    entitlement = LicenseEntitlement.from_data(VALID_ENTITLEMENT)

    assert set(LicenseEntitlement.to_json(entitlement)) == set(LicenseEntitlementKey)


def test_from_data_carries_features() -> None:
    """from_data preserves the features list (the sole gating source)"""
    entitlement = LicenseEntitlement.from_data(VALID_ENTITLEMENT)

    assert entitlement.features == [LicenseFeature.REST_API.value, LicenseFeature.IPAM.value]


def test_to_json_survives_base64_json_transport() -> None:
    """The enum-keyed to_json dict serializes through P5 transport to plain camelCase string keys"""
    entitlement = LicenseEntitlement.from_data(VALID_ENTITLEMENT)

    decoded = decode_json(encode_json(LicenseEntitlement.to_json(entitlement)))

    assert decoded['type'] == LicenseTier.CORE.value
    assert decoded['endDate'] == 0
    assert set(decoded) == {key.value for key in LicenseEntitlementKey}


def test_from_data_applies_defaults() -> None:
    """A minimal dict defaults to the free tier with zeroed dates/quota and empty ids"""
    entitlement = LicenseEntitlement.from_data({LicenseEntitlementKey.HMAC: 'bind'})

    assert entitlement.license_type == LicenseTier.FREE.value
    assert entitlement.start_date == 0
    assert entitlement.end_date == 0
    assert entitlement.sub_id == ''
    assert entitlement.features == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                            schema validation                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_schema_accepts_valid_document() -> None:
    """The SCHEMA accepts a well-formed entitlement document"""
    assert Validator(LicenseEntitlement.SCHEMA).validate(VALID_ENTITLEMENT) is True


def test_schema_accepts_empty_features() -> None:
    """An empty features list is accepted (the free tier unlocks nothing)"""
    document = dict(VALID_ENTITLEMENT)
    document[LicenseEntitlementKey.FEATURES] = []

    assert Validator(LicenseEntitlement.SCHEMA).validate(document) is True


@pytest.mark.parametrize('mutation,reason', [
    ({LicenseEntitlementKey.HMAC: None}, 'missing required hmac'),
    ({LicenseEntitlementKey.HMAC: ''}, 'empty hmac'),
    ({LicenseEntitlementKey.TYPE: 'enterprise'}, 'type not a known tier'),
    ({LicenseEntitlementKey.START_DATE: 'soon'}, 'startDate wrong type'),
    ({LicenseEntitlementKey.END_DATE: -1}, 'endDate below minimum'),
    ({LicenseEntitlementKey.OPERATION_USAGE: -5}, 'operationUsage below minimum'),
    ({LicenseEntitlementKey.FEATURES: None}, 'missing required features'),
    ({LicenseEntitlementKey.FEATURES: 'ipam'}, 'features not a list'),
    ({LicenseEntitlementKey.FEATURES: ['']}, 'features holds an empty string'),
])
def test_schema_rejects_malformed_document(mutation: dict, reason: str) -> None:
    """The SCHEMA rejects each malformed entitlement shape"""
    document = dict(VALID_ENTITLEMENT)
    for key, value in mutation.items():
        if value is None:
            del document[key]
        else:
            document[key] = value

    assert Validator(LicenseEntitlement.SCHEMA).validate(document) is False


def test_schema_rejects_unknown_field() -> None:
    """The SCHEMA rejects an unexpected extra field"""
    document = dict(VALID_ENTITLEMENT)
    document['unexpected'] = 'x'

    assert Validator(LicenseEntitlement.SCHEMA).validate(document) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                     cross-check with the P7 generator                                               #
# -------------------------------------------------------------------------------------------------------------------- #
def test_generator_entitlement_conforms_to_schema() -> None:
    """build_entitlement (P7) output validates against the entitlement SCHEMA and round-trips"""
    generated = build_entitlement(license_type=LicenseTier.BUSINESS.value, hmac_value='bind-x')

    assert Validator(LicenseEntitlement.SCHEMA).validate(generated) is True
    assert LicenseEntitlement.to_json(LicenseEntitlement.from_data(generated)) == generated
