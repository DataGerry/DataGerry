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
Unit tests for cmdb.framework.ipam.vlan_validator

Covers the three branches of validate_vlan: subnet type missing, subnet not found, happy path.
ObjectsManager / TypesManager are MagicMock stand-ins and resolve_special_type_id is patched at
the vlan_validator module path so the validator's decision logic is exercised in isolation.
"""
from typing import Any
from unittest.mock import MagicMock, patch

from cmdb.utils import ValidationErrorKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.ipam_constants import IpamValidationDetailKey
from cmdb.models.object_model import CmdbObjectKey
from cmdb.framework.ipam.vlan_validator import VlanErrorCode, validate_vlan
# -------------------------------------------------------------------------------------------------------------------- #


SUBNET_TYPE_ID: int = 11
SUBNET_OBJECT_ID: int = 42

RESOLVE_PATH: str = 'cmdb.framework.ipam.vlan_validator.resolve_special_type_id'


# -------------------------------------------------------------------------------------------------------------------- #
#                                          subnet_type_missing branch                                                  #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_vlan_reports_subnet_type_missing_when_no_subnet_type_defined() -> None:
    """When no CmdbType is marked SUBNET, validate_vlan emits a single SUBNET_TYPE_MISSING error"""
    objects_manager = MagicMock()
    types_manager = MagicMock()

    with patch(RESOLVE_PATH, return_value=None) as resolve_mock:
        errors = validate_vlan(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == VlanErrorCode.SUBNET_TYPE_MISSING
    assert errors[0][ValidationErrorKey.DETAILS] == {}
    resolve_mock.assert_called_once_with(types_manager, SpecialType.SUBNET)
    objects_manager.find_objects.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                           subnet_not_found branch                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_vlan_reports_subnet_not_found_when_no_object_matches() -> None:
    """A defined SUBNET type but no matching CmdbObject id yields a single SUBNET_NOT_FOUND error"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()

    with patch(RESOLVE_PATH, return_value=SUBNET_TYPE_ID):
        errors = validate_vlan(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert len(errors) == 1
    assert errors[0][ValidationErrorKey.CODE] == VlanErrorCode.SUBNET_NOT_FOUND
    details = errors[0][ValidationErrorKey.DETAILS]
    assert details[IpamValidationDetailKey.SUBNET_OBJECT_ID] == SUBNET_OBJECT_ID


def test_validate_vlan_queries_objects_manager_with_public_id_and_type_id_filter() -> None:
    """The subnet lookup constrains by both PUBLIC_ID and the resolved SUBNET type_id, as_dict=True"""
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = []
    types_manager = MagicMock()

    with patch(RESOLVE_PATH, return_value=SUBNET_TYPE_ID):
        validate_vlan(objects_manager, types_manager, SUBNET_OBJECT_ID)

    objects_manager.find_objects.assert_called_once_with(
        {CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID, CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID},
        as_dict=True,
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                happy path                                                            #
# -------------------------------------------------------------------------------------------------------------------- #
def test_validate_vlan_returns_no_errors_when_subnet_object_exists() -> None:
    """A matching SUBNET CmdbObject yields no errors"""
    matching_subnet: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: SUBNET_OBJECT_ID,
        CmdbObjectKey.TYPE_ID: SUBNET_TYPE_ID,
    }
    objects_manager = MagicMock()
    objects_manager.find_objects.return_value = [matching_subnet]
    types_manager = MagicMock()

    with patch(RESOLVE_PATH, return_value=SUBNET_TYPE_ID):
        errors = validate_vlan(objects_manager, types_manager, SUBNET_OBJECT_ID)

    assert errors == []
