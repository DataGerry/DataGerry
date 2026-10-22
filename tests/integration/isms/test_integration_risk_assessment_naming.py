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
Integration tests for the RiskAssessment list's steps, run against a real MongoDB

The object-scope expansion is run by the real managers and its result queried against the stored assessments, so
what is pinned is what the widened filter MATCHES: the object's own assessments and those of its static and dynamic
groups, narrowed by every other clause the filter carried. The projected name reads resolve each reference from its
own collection, with interviewed and responsible persons from one read, and the objects as the caller
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_constants import MONGO_AND_OPERATOR
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment
from cmdb.models.object_group_model.cmdb_object_group import CmdbObjectGroup
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.object_model import CmdbObject
from cmdb.models.person_group_model.cmdb_person_group import CmdbPersonGroup
from cmdb.models.person_model.cmdb_person import CmdbPerson
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.isms_routes.risk_assessment_naming_helper import (
    RiskAssessmentNamingIds,
    expand_object_scope_filter,
    fetch_naming_lookups,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

# Every test here reaches the database through ManagerProvider, which reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

OPEN_TYPE_ID: int = 88931
HIDDEN_TYPE_ID: int = 88932
OBJECT_ID: int = 88941
HIDDEN_OBJECT_ID: int = 88942
STATIC_GROUP_ID: int = 88951
DYNAMIC_GROUP_ID: int = 88952
FOREIGN_GROUP_ID: int = 88953
RISK_ID: int = 88961
PERSON_ID: int = 88971
RESPONSIBLE_PERSON_ID: int = 88972
PERSON_GROUP_ID: int = 88981

RA_DIRECT_ID: int = 88991
RA_STATIC_ID: int = 88992
RA_DYNAMIC_ID: int = 88993
RA_FOREIGN_ID: int = 88994
RA_OTHER_OBJECT_ID: int = 88995
ALL_RA_IDS: list[int] = [RA_DIRECT_ID, RA_STATIC_ID, RA_DYNAMIC_ID, RA_FOREIGN_ID, RA_OTHER_OBJECT_ID]

RISK_NAME: str = 'Flooding'
STATIC_GROUP_NAME: str = 'Server room'
PERSON_NAME: str = 'Alice'
RESPONSIBLE_PERSON_NAME: str = 'Carol'
PERSON_GROUP_NAME: str = 'Ops Team'

OBJECT_SCOPE: list[dict[str, Any]] = [
    {'object_id_ref_type': ObjectReferenceType.OBJECT.value}, {'object_id': OBJECT_ID},
]

SEEDED: dict[str, tuple[str, list[int]]] = {
    'types': (CmdbType.COLLECTION, [OPEN_TYPE_ID, HIDDEN_TYPE_ID]),
    'objects': (CmdbObject.COLLECTION, [OBJECT_ID, HIDDEN_OBJECT_ID]),
    'groups': (CmdbObjectGroup.COLLECTION, [STATIC_GROUP_ID, DYNAMIC_GROUP_ID, FOREIGN_GROUP_ID]),
    'risks': (IsmsRisk.COLLECTION, [RISK_ID]),
    'persons': (CmdbPerson.COLLECTION, [PERSON_ID, RESPONSIBLE_PERSON_ID]),
    'person_groups': (CmdbPersonGroup.COLLECTION, [PERSON_GROUP_ID]),
    'assessments': (IsmsRiskAssessment.COLLECTION, ALL_RA_IDS),
}


def _assessment(public_id: int, ref_type: ObjectReferenceType, object_id: int) -> dict[str, Any]:
    """The keys the scope matches on - the query reads the collection directly"""
    return {'public_id': public_id, 'object_id_ref_type': ref_type.value, 'object_id': object_id}


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """An open and a hidden Type, an object of each, its groups, the named documents and the assessments"""
    def _purge() -> None:
        for collection, public_ids in SEEDED.values():
            database_manager.get_collection(collection, database_name).delete_many(
                {'public_id': {'$in': public_ids}},
            )

    def _insert(collection: str, documents: list[dict[str, Any]]) -> None:
        database_manager.get_collection(collection, database_name).insert_many(documents)

    _purge()
    hidden_type: dict[str, Any] = make_type_doc(HIDDEN_TYPE_ID, 'ra-naming-hidden')
    hidden_type['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}
    _insert(CmdbType.COLLECTION, [make_type_doc(OPEN_TYPE_ID, 'ra-naming-open'), hidden_type])
    _insert(CmdbObject.COLLECTION, [
        {'public_id': object_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
         'fields': [{'name': 'dg-name', 'value': f'host-{object_id}', 'type': 'text'}]}
        for object_id, type_id in ((OBJECT_ID, OPEN_TYPE_ID), (HIDDEN_OBJECT_ID, HIDDEN_TYPE_ID))
    ])
    _insert(CmdbObjectGroup.COLLECTION, [
        {'public_id': STATIC_GROUP_ID, 'name': STATIC_GROUP_NAME, 'group_type': 'STATIC',
         'assigned_ids': [OBJECT_ID]},
        {'public_id': DYNAMIC_GROUP_ID, 'name': 'All open', 'group_type': 'DYNAMIC', 'assigned_ids': [OPEN_TYPE_ID]},
        {'public_id': FOREIGN_GROUP_ID, 'name': 'Elsewhere', 'group_type': 'STATIC',
         'assigned_ids': [HIDDEN_OBJECT_ID]},
    ])
    _insert(IsmsRisk.COLLECTION, [{'public_id': RISK_ID, 'name': RISK_NAME}])
    _insert(CmdbPerson.COLLECTION, [
        {'public_id': PERSON_ID, 'display_name': PERSON_NAME},
        {'public_id': RESPONSIBLE_PERSON_ID, 'display_name': RESPONSIBLE_PERSON_NAME},
    ])
    _insert(CmdbPersonGroup.COLLECTION, [{'public_id': PERSON_GROUP_ID, 'name': PERSON_GROUP_NAME}])
    _insert(IsmsRiskAssessment.COLLECTION, [
        _assessment(RA_DIRECT_ID, ObjectReferenceType.OBJECT, OBJECT_ID),
        _assessment(RA_STATIC_ID, ObjectReferenceType.OBJECT_GROUP, STATIC_GROUP_ID),
        _assessment(RA_DYNAMIC_ID, ObjectReferenceType.OBJECT_GROUP, DYNAMIC_GROUP_ID),
        _assessment(RA_FOREIGN_ID, ObjectReferenceType.OBJECT_GROUP, FOREIGN_GROUP_ID),
        _assessment(RA_OTHER_OBJECT_ID, ObjectReferenceType.OBJECT, HIDDEN_OBJECT_ID),
    ])
    yield
    _purge()


def _user(group_id: int) -> CmdbUser:
    """A request user of the given group"""
    return CmdbUser(public_id=1, user_name='ra-naming', active=True, group_id=group_id)


def _matched(database_manager: MongoDatabaseManager, database_name: str, query_filter: dict[str, Any]) -> list[int]:
    """The seeded assessments the filter matches"""
    documents = database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name).find(
        {MONGO_AND_OPERATOR: [query_filter, {'public_id': {'$in': ALL_RA_IDS}}]},
    )

    return sorted(document['public_id'] for document in documents)


class TestExpandedScopeMatches:
    """What the widened filter finds among the stored assessments"""

    def test_the_object_and_both_kinds_of_its_groups(self, database_manager, database_name) -> None:
        """Its own, its static group's and its type's dynamic group's - not another object's group"""
        expanded = expand_object_scope_filter({MONGO_AND_OPERATOR: OBJECT_SCOPE}, _user(ADMIN_GROUP_ID))

        assert _matched(database_manager, database_name, expanded) == [RA_DIRECT_ID, RA_STATIC_ID, RA_DYNAMIC_ID]

    def test_another_clause_narrows_the_widened_scope(self, database_manager, database_name) -> None:
        """The search's clause stays and applies to the group assessments too"""
        expanded = expand_object_scope_filter(
            {MONGO_AND_OPERATOR: [*OBJECT_SCOPE, {'public_id': RA_STATIC_ID}]}, _user(ADMIN_GROUP_ID),
        )

        assert _matched(database_manager, database_name, expanded) == [RA_STATIC_ID]

    def test_a_missing_object_matches_as_sent(self, database_manager, database_name) -> None:
        """No object, nothing to widen to: only assessments naming that id directly - none here"""
        query_filter = {MONGO_AND_OPERATOR: [OBJECT_SCOPE[0], {'object_id': RA_DIRECT_ID}]}

        assert expand_object_scope_filter(query_filter, _user(ADMIN_GROUP_ID)) is query_filter
        assert not _matched(database_manager, database_name, query_filter)


class TestNamingLookups:
    """Each reference resolved from its own collection"""

    def test_every_name_is_read_from_its_collection(self) -> None:
        """Risk, group, both persons in one read, the person group"""
        lookups = fetch_naming_lookups(RiskAssessmentNamingIds(
            risk_ids={RISK_ID}, object_group_ids={STATIC_GROUP_ID}, person_ids={PERSON_ID},
            responsible_person_ids={RESPONSIBLE_PERSON_ID}, responsible_person_group_ids={PERSON_GROUP_ID},
        ), _user(ADMIN_GROUP_ID))

        assert lookups.risks == {RISK_ID: RISK_NAME}
        assert lookups.object_groups == {STATIC_GROUP_ID: STATIC_GROUP_NAME}
        assert lookups.persons == {PERSON_ID: PERSON_NAME, RESPONSIBLE_PERSON_ID: RESPONSIBLE_PERSON_NAME}
        assert lookups.person_groups == {PERSON_GROUP_ID: PERSON_GROUP_NAME}

    def test_an_id_naming_nothing_stays_unnamed(self) -> None:
        """A person id is not looked up among the person groups"""
        lookups = fetch_naming_lookups(
            RiskAssessmentNamingIds(responsible_person_group_ids={PERSON_ID}), _user(ADMIN_GROUP_ID),
        )

        assert not lookups.person_groups

    def test_an_object_of_a_hidden_type_gets_no_summary_line(self) -> None:
        """Read as the caller: the user group may not READ the hidden Type"""
        lookups = fetch_naming_lookups(
            RiskAssessmentNamingIds(object_ids={OBJECT_ID, HIDDEN_OBJECT_ID}), _user(USER_GROUP_ID),
        )

        assert OBJECT_ID in lookups.object_summaries
        assert HIDDEN_OBJECT_ID not in lookups.object_summaries
