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
Integration tests: the IPAM delete guard's description of hidden references, against a real MongoDB

A subnet referenced by interface rows on objects of a readable and of a hidden Type: ``enforce_delete_guards`` still
refuses it, naming the readable carriers and counting the hidden ones - the second read leaves the hidden Types out in
the query itself. With nothing hidden, every id is named as before
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager, TypesManager
from cmdb.models.object_model import CmdbObject, CmdbObjectKey, CmdbObjectMdsKey, CmdbObjectMdsRowKey
from cmdb.models.special_type_model.ipam_constants import InterfaceField, IpamSection
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.type_model import CmdbType
from cmdb.utils import ValidationErrorKey
from cmdb.framework.ipam.enforcement import enforce_delete_guards
from cmdb.framework.ipam.references_constants import SUBNET_REFERENCED_BY_INTERFACES_MSG
from tests.utils.ipam_doc_builders import make_field, make_object_doc, make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

SUBNET_TYPE_ID: int = 943701
OPEN_TYPE_ID: int = 943702
HIDDEN_TYPE_ID: int = 943703
SUBNET_ID: int = 943711
OPEN_CARRIER_IDS: list[int] = [943721, 943722]
HIDDEN_CARRIER_IDS: list[int] = [943731, 943732]
TYPE_IDS: list[int] = [SUBNET_TYPE_ID, OPEN_TYPE_ID, HIDDEN_TYPE_ID]
OBJECT_IDS: list[int] = [SUBNET_ID, *OPEN_CARRIER_IDS, *HIDDEN_CARRIER_IDS]


def _carrier(public_id: int, type_id: int) -> dict[str, Any]:
    """An object with one interface row on the subnet"""
    return make_object_doc(public_id, type_id, [], mds=[{
        CmdbObjectMdsKey.SECTION_ID.value: IpamSection.INTERFACE.value,
        CmdbObjectMdsKey.VALUES.value: [{CmdbObjectMdsRowKey.DATA.value: [make_field(InterfaceField.SUBNET, SUBNET_ID)]}],
    }])


@pytest.fixture(name='managers')
def fixture_managers(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The subnet, two readable and two hidden carriers; removed again"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': TYPE_IDS}})
        objects.delete_many({CmdbObjectKey.PUBLIC_ID.value: {'$in': OBJECT_IDS}})

    _purge()
    types.insert_many([make_type_doc(SUBNET_TYPE_ID, 'int-hidden-subnet', SpecialType.SUBNET),
                       make_type_doc(OPEN_TYPE_ID, 'int-open-carrier'), make_type_doc(HIDDEN_TYPE_ID, 'int-hidden')])
    objects.insert_many([make_object_doc(SUBNET_ID, SUBNET_TYPE_ID, []),
                         *(_carrier(carrier_id, OPEN_TYPE_ID) for carrier_id in OPEN_CARRIER_IDS),
                         *(_carrier(carrier_id, HIDDEN_TYPE_ID) for carrier_id in HIDDEN_CARRIER_IDS)])
    yield ObjectsManager(database_manager), TypesManager(database_manager), objects.find_one(
        {CmdbObjectKey.PUBLIC_ID.value: SUBNET_ID}, {'_id': 0})
    _purge()


def _messages(errors: list[dict[str, Any]]) -> list[str]:
    """The guard's messages"""
    return [error[ValidationErrorKey.MESSAGE] for error in errors]


def test_the_hidden_carriers_block_but_are_only_counted(managers: Any) -> None:
    """The readable ids named, the hidden ones counted"""
    objects_manager, types_manager, subnet = managers

    errors = enforce_delete_guards(objects_manager, types_manager, subnet,
                                   hidden_types=lambda: frozenset({HIDDEN_TYPE_ID}))

    assert _messages(errors) == [SUBNET_REFERENCED_BY_INTERFACES_MSG.format(
        ids=f'{OPEN_CARRIER_IDS[0]}, {OPEN_CARRIER_IDS[1]}, plus 2 object(s) you cannot see',
    )]


def test_with_nothing_hidden_every_id_is_named(managers: Any) -> None:
    """As before"""
    objects_manager, types_manager, subnet = managers

    errors = enforce_delete_guards(objects_manager, types_manager, subnet)

    assert _messages(errors) == [SUBNET_REFERENCED_BY_INTERFACES_MSG.format(
        ids=', '.join(str(carrier_id) for carrier_id in sorted(OPEN_CARRIER_IDS + HIDDEN_CARRIER_IDS)),
    )]
