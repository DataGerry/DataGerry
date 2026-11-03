# DataGerry - OpenSource Enterprise CMDB
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
Unit tests for the compare-and-swap write of the subnet 'unassign IPs' flow, its type cache and its IP limit

Driven against a MagicMock ObjectsManager: each owner write carries what the plan was made from (its sections and
version) and the owner's type id; a miss re-reads the owner and plans again from it; an owner whose rows a concurrent
edit already unassigned, or that is gone, ends without a write; a miss on every attempt stops the request with a 400
naming the owner. The owner's type is read once per type for the whole request, and a request naming more IPs than
``IpamUnassignLimits.MAX_IPS`` is refused before anything is read.
"""
import copy
from http import HTTPStatus
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.object_model import CmdbObjectKey, CmdbObjectFieldKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.special_type_model.ipam_constants import (
    InterfaceField,
    IpamSection,
    IpamUnassignLimits,
    IpamUnassignMode,
)
from cmdb.framework.ipam.subnet_unassign import (
    abort_if_too_many_ips,
    apply_unassign_to_owners,
    clear_subnet_ref_in_owner,
    owner_write_guard,
    resolve_owner_type,
    unassign_ips_from_subnet,
    write_owner_unassign,
)
from cmdb.framework.ipam.subnet_unassign_constants import (
    IPS_TOO_MANY_MSG,
    MAX_OWNER_WRITE_ATTEMPTS,
    OWNER_KEPT_CHANGING_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

PATH: str = 'cmdb.framework.ipam.subnet_unassign'
SUBNET_ID: int = 200
OWNER_ID: int = 700
OTHER_OWNER_ID: int = 701
OWNER_TYPE_ID: int = 50
OTHER_TYPE_ID: int = 51
TARGET_IP: str = '10.0.0.1'
CONCURRENT_IP: str = '10.0.0.9'
READ_VERSION: str = '1.0.0'
CONCURRENT_VERSION: str = '1.0.4'
EDIT_STAMP: dict[str, Any] = {'last_edit_time': None, 'editor_id': 5}


def _row(ip: str, subnet_ref: int | None = SUBNET_ID) -> dict[str, Any]:
    """One interface row"""
    return {CmdbObjectMdsRowKey.DATA.value: [
        {CmdbObjectFieldKey.NAME.value: InterfaceField.SUBNET.value, CmdbObjectFieldKey.VALUE.value: subnet_ref},
        {CmdbObjectFieldKey.NAME.value: InterfaceField.IP.value, CmdbObjectFieldKey.VALUE.value: ip},
    ]}


def _owner(rows: list[dict[str, Any]], version: str = READ_VERSION, public_id: int = OWNER_ID,
           type_id: int = OWNER_TYPE_ID) -> dict[str, Any]:
    """An owner document with one interface section"""
    return {
        CmdbObjectKey.PUBLIC_ID.value: public_id,
        CmdbObjectKey.TYPE_ID.value: type_id,
        CmdbObjectKey.VERSION.value: version,
        CmdbObjectKey.AUTHOR_ID.value: 1,
        CmdbObjectKey.ACTIVE.value: True,
        CmdbObjectKey.FIELDS.value: [
            {CmdbObjectFieldKey.NAME.value: 'hostname', CmdbObjectFieldKey.VALUE.value: 'srv'},
        ],
        CmdbObjectKey.MULTI_DATA_SECTIONS.value: [{
            CmdbObjectMdsKey.SECTION_ID.value: IpamSection.INTERFACE.value,
            CmdbObjectMdsKey.VALUES.value: rows,
        }],
    }


def _write(objects_manager: MagicMock, owner: dict[str, Any]) -> tuple[Any, set[str]]:
    """write_owner_unassign in REFERENCE mode for the target IP, with a fresh type cache"""
    return write_owner_unassign(
        objects_manager, owner, clear_subnet_ref_in_owner, SUBNET_ID, {TARGET_IP}, MagicMock(), EDIT_STAMP, {},
    )


class TestTheWriteGuard:
    """owner_write_guard"""

    def test_requires_the_sections_and_version_as_read(self) -> None:
        """What the plan was made from"""
        owner: dict[str, Any] = _owner([_row(TARGET_IP)])

        assert owner_write_guard(owner) == {
            CmdbObjectKey.MULTI_DATA_SECTIONS.value: owner[CmdbObjectKey.MULTI_DATA_SECTIONS.value],
            CmdbObjectKey.VERSION.value: READ_VERSION,
        }

    def test_an_owner_without_them_requires_their_absence(self) -> None:
        """A None in the filter matches a missing key - the owner is still written while nothing changed"""
        assert owner_write_guard({CmdbObjectKey.PUBLIC_ID.value: OWNER_ID}) == {
            CmdbObjectKey.MULTI_DATA_SECTIONS.value: None, CmdbObjectKey.VERSION.value: None,
        }


class TestTheCompareAndSwap:
    """write_owner_unassign"""

    def test_a_landed_write_carries_the_guard_and_the_type(self) -> None:
        """One attempt: the guard of the read, the owner's type id, the cached type"""
        objects_manager = MagicMock()
        objects_manager.update_object.return_value = True
        owner: dict[str, Any] = _owner([_row(TARGET_IP)])

        plan, affected = _write(objects_manager, owner)

        assert affected == {TARGET_IP}
        assert plan is not None
        kwargs: dict[str, Any] = objects_manager.update_object.call_args.kwargs
        assert kwargs['expected'] == owner_write_guard(owner)
        assert kwargs['stored_type_id'] == OWNER_TYPE_ID
        assert kwargs['object_type'] is objects_manager.get_object_type.return_value
        objects_manager.get_one.assert_not_called()

    def test_a_miss_plans_again_from_what_is_stored_now(self) -> None:
        """A concurrent edit added a row: the second write keeps it and carries the new guard"""
        objects_manager = MagicMock()
        fresh: dict[str, Any] = _owner([_row(TARGET_IP), _row(CONCURRENT_IP)], version=CONCURRENT_VERSION)
        objects_manager.update_object.side_effect = [False, True]
        objects_manager.get_one.return_value = copy.deepcopy(fresh)

        plan, affected = _write(objects_manager, _owner([_row(TARGET_IP)]))

        assert affected == {TARGET_IP}
        objects_manager.get_one.assert_called_once_with(OWNER_ID)
        second = objects_manager.update_object.call_args
        assert second.kwargs['expected'] == owner_write_guard(fresh)
        rows = second.args[1][CmdbObjectKey.MULTI_DATA_SECTIONS.value][0][CmdbObjectMdsKey.VALUES.value]
        assert [row[CmdbObjectMdsRowKey.DATA.value][1][CmdbObjectFieldKey.VALUE.value] for row in rows] == [
            TARGET_IP, CONCURRENT_IP,
        ]
        assert plan.before.version == CONCURRENT_VERSION

    def test_rows_another_edit_already_unassigned_end_without_a_write(self) -> None:
        """Nothing left to do after the re-read"""
        objects_manager = MagicMock()
        objects_manager.update_object.return_value = False
        objects_manager.get_one.return_value = _owner([_row(TARGET_IP, subnet_ref=None)])

        assert _write(objects_manager, _owner([_row(TARGET_IP)])) == (None, set())
        assert objects_manager.update_object.call_count == 1

    def test_an_owner_deleted_meanwhile_ends_without_a_write(self) -> None:
        """The re-read finds nothing"""
        objects_manager = MagicMock()
        objects_manager.update_object.return_value = False
        objects_manager.get_one.return_value = None

        assert _write(objects_manager, _owner([_row(TARGET_IP)])) == (None, set())

    def test_a_miss_on_every_attempt_is_a_400_naming_the_owner(self) -> None:
        """The owner kept changing"""
        objects_manager = MagicMock()
        objects_manager.update_object.return_value = False
        objects_manager.get_one.side_effect = lambda _id: _owner([_row(TARGET_IP)])

        with pytest.raises(HTTPException) as exc_info:
            _write(objects_manager, _owner([_row(TARGET_IP)]))

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        assert exc_info.value.description == OWNER_KEPT_CHANGING_MSG.format(
            owner_id=OWNER_ID, attempts=MAX_OWNER_WRITE_ATTEMPTS,
        )
        assert objects_manager.update_object.call_count == MAX_OWNER_WRITE_ATTEMPTS

    def test_an_owner_without_the_target_is_not_written(self) -> None:
        """The mutator finds nothing to change on the first read"""
        objects_manager = MagicMock()

        assert _write(objects_manager, _owner([_row(CONCURRENT_IP)])) == (None, set())
        objects_manager.update_object.assert_not_called()


class TestTheTypeCache:
    """resolve_owner_type and its use across owners"""

    def test_a_type_is_read_once(self) -> None:
        """The second ask is answered from the cache"""
        objects_manager = MagicMock()
        cache: dict[int, Any] = {}

        first = resolve_owner_type(objects_manager, cache, OWNER_TYPE_ID)
        second = resolve_owner_type(objects_manager, cache, OWNER_TYPE_ID)

        assert first is second
        objects_manager.get_object_type.assert_called_once_with(OWNER_TYPE_ID)

    def test_a_missing_type_is_cached_too(self) -> None:
        """None is remembered; the guard refuses the write"""
        objects_manager = MagicMock()
        objects_manager.get_object_type.return_value = None
        cache: dict[int, Any] = {}

        assert resolve_owner_type(objects_manager, cache, OWNER_TYPE_ID) is None
        assert resolve_owner_type(objects_manager, cache, OWNER_TYPE_ID) is None
        objects_manager.get_object_type.assert_called_once_with(OWNER_TYPE_ID)

    def test_one_request_reads_each_type_once(self) -> None:
        """Two owners of one type and one of another: two type reads"""
        objects_manager = MagicMock()
        objects_manager.update_object.return_value = True
        owners: list[dict[str, Any]] = [
            _owner([_row(TARGET_IP)], public_id=OWNER_ID),
            _owner([_row(TARGET_IP)], public_id=OTHER_OWNER_ID),
            _owner([_row(TARGET_IP)], public_id=OTHER_OWNER_ID + 1, type_id=OTHER_TYPE_ID),
        ]

        apply_unassign_to_owners(objects_manager, owners, SUBNET_ID, {TARGET_IP}, MagicMock(),
                                 IpamUnassignMode.REFERENCE)

        assert [call.args[0] for call in objects_manager.get_object_type.call_args_list] == [
            OWNER_TYPE_ID, OTHER_TYPE_ID,
        ]


class TestTheIpLimit:
    """abort_if_too_many_ips"""

    def test_the_limit_itself_passes(self) -> None:
        """Inclusive"""
        abort_if_too_many_ips([TARGET_IP] * IpamUnassignLimits.MAX_IPS)

    def test_one_more_is_a_400_naming_both_counts(self) -> None:
        """Duplicates count - each is parsed"""
        count: int = IpamUnassignLimits.MAX_IPS + 1

        with pytest.raises(HTTPException) as exc_info:
            abort_if_too_many_ips([TARGET_IP] * count)

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        assert exc_info.value.description == IPS_TOO_MANY_MSG.format(max_ips=IpamUnassignLimits.MAX_IPS, count=count)

    @pytest.mark.parametrize('raw', [None, TARGET_IP, {'ip': TARGET_IP}], ids=['none', 'string', 'dict'])
    def test_a_value_that_is_no_list_is_left_to_the_shape_check(self, raw: Any) -> None:
        """normalize_ip_list refuses it with its own message"""
        abort_if_too_many_ips(raw)

    def test_the_orchestrator_refuses_before_anything_is_read(self) -> None:
        """Not even the subnet"""
        with patch(f'{PATH}.assert_subnet_exists') as subnet_read, pytest.raises(HTTPException) as exc_info:
            unassign_ips_from_subnet(MagicMock(), MagicMock(), SUBNET_ID,
                                     [TARGET_IP] * (IpamUnassignLimits.MAX_IPS + 1), MagicMock())

        assert exc_info.value.code == HTTPStatus.BAD_REQUEST
        subnet_read.assert_not_called()
