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
Unit tests for risk_assessment_naming_helper - the steps of the RiskAssessment list around its one query

The object-scope expansion (which filters it widens, what it keeps), the id collection, the projected name reads and
the naming block. ManagerProvider is patched at the helper's path, so no database is reached
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.database.database_constants import MONGO_AND_OPERATOR, MONGO_ID_FIELD, PUBLIC_ID_FIELD
from cmdb.manager.manager_provider_model import ManagerType
from cmdb.models.isms_model.isms_risk_assessment_constants import RiskAssessmentKey
from cmdb.models.isms_model.isms_risk_constants import RiskKey
from cmdb.models.object_group_model.object_group_constants import ObjectGroupKey
from cmdb.models.object_group_model.object_reference_type_enum import ObjectReferenceType
from cmdb.models.object_model import CmdbObjectKey
from cmdb.models.person_group_model.person_group_constants import PersonGroupKey
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.models.person_model.person_constants import PersonKey
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.utils import Builder

from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    RISK_ASSESSMENT_NAMING_KEY,
    RiskAssessmentNamingKey,
)
from cmdb.interface.rest_api.routes.isms_routes.risk_assessment_naming_helper import (
    RiskAssessmentNamingIds,
    RiskAssessmentNamingLookups,
    build_ra_naming,
    collect_naming_ids,
    expand_object_scope_filter,
    fetch_naming_lookups,
    is_object_scope_clause,
    name_lookup,
    named_risk_assessment,
    object_or_group_scope,
    responsible_name,
    scoped_object_id,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.isms_routes.risk_assessment_naming_helper'

OBJECT_ID_KEY: str = RiskAssessmentKey.OBJECT_ID.value
REF_TYPE_KEY: str = RiskAssessmentKey.OBJECT_ID_REF_TYPE.value

OBJECT_ID: int = 30
OTHER_OBJECT_ID: int = 31
TYPE_ID: int = 5
GROUP_IDS: list[int] = [20, 21]
RISK_ID: int = 1
OBJECT_GROUP_ID: int = 20
INTERVIEWED_IDS: list[int] = [40, 41]
UNKNOWN_PERSON_ID: int = 999
RESPONSIBLE_PERSON_ID: int = 50
RESPONSIBLE_GROUP_ID: int = 60
PAGE_SIZE: int = 10

RISK_NAME: str = 'MyRisk'
OBJECT_GROUP_NAME: str = 'MyObjectGroup'
OBJECT_SUMMARY: str = 'Obj summary'
INTERVIEWED_NAMES: list[str] = ['Alice', 'Bob']
RESPONSIBLE_PERSON_NAME: str = 'Carol'
RESPONSIBLE_GROUP_NAME: str = 'Ops Team'
UNKNOWN_REF_TYPE: str = 'NOBODY'

OBJECT_SCOPE: list[dict[str, Any]] = [{REF_TYPE_KEY: ObjectReferenceType.OBJECT.value}, {OBJECT_ID_KEY: OBJECT_ID}]
SEARCH_TEXT: str = 'risk'
SEARCH_CLAUSE: dict[str, Any] = Builder.or_([
    Builder.regex_(f'{RISK_ASSESSMENT_NAMING_KEY}.{RiskAssessmentNamingKey.RISK_ID_NAME.value}', SEARCH_TEXT),
])
PAGING_KEY: str = 'risk_id'

LOOKUPS: RiskAssessmentNamingLookups = RiskAssessmentNamingLookups(
    risks={RISK_ID: RISK_NAME},
    object_groups={OBJECT_GROUP_ID: OBJECT_GROUP_NAME},
    object_summaries={OBJECT_ID: OBJECT_SUMMARY},
    persons={
        INTERVIEWED_IDS[0]: INTERVIEWED_NAMES[0],
        INTERVIEWED_IDS[1]: INTERVIEWED_NAMES[1],
        RESPONSIBLE_PERSON_ID: RESPONSIBLE_PERSON_NAME,
    },
    person_groups={RESPONSIBLE_GROUP_ID: RESPONSIBLE_GROUP_NAME},
)


def _ra(**fields: Any) -> SimpleNamespace:
    """An IsmsRiskAssessment-like stub with neutral defaults"""
    defaults: dict[str, Any] = {
        'risk_id': RISK_ID,
        'object_id_ref_type': ObjectReferenceType.OBJECT,
        'object_id': OBJECT_ID,
        'interviewed_persons': [],
        'responsible_persons_id': None,
        'responsible_persons_id_ref_type': PersonReferenceType.PERSON,
    }
    defaults.update(fields)

    return SimpleNamespace(**defaults)


@pytest.fixture(name='managers')
def fixture_managers() -> Any:
    """One MagicMock per ManagerType the helper asks for, handed out by a patched ManagerProvider"""
    by_type: dict[ManagerType, MagicMock] = {}

    def _get_manager(manager_type: ManagerType, _request_user: Any) -> MagicMock:
        return by_type.setdefault(manager_type, MagicMock(name=manager_type.name))

    with patch(f'{HELPER_PATH}.ManagerProvider.get_manager', side_effect=_get_manager):
        yield by_type


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 object scope                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIsObjectScopeClause:
    """A clause is one half of the scope only when it carries nothing but the scope keys"""

    @pytest.mark.parametrize('clause', [
        {OBJECT_ID_KEY: OBJECT_ID},
        {REF_TYPE_KEY: ObjectReferenceType.OBJECT.value},
        {OBJECT_ID_KEY: OBJECT_ID, REF_TYPE_KEY: ObjectReferenceType.OBJECT.value},
    ])
    def test_a_scope_clause(self, clause: dict[str, Any]) -> None:
        """Either key, or both"""
        assert is_object_scope_clause(clause)

    @pytest.mark.parametrize('clause', [
        {},
        {OBJECT_ID_KEY: OBJECT_ID, PAGING_KEY: RISK_ID},
        SEARCH_CLAUSE,
        [OBJECT_ID_KEY],
        OBJECT_ID_KEY,
        None,
    ])
    def test_not_a_scope_clause(self, clause: Any) -> None:
        """Empty, mixed with another key, another clause, or no dict at all"""
        assert not is_object_scope_clause(clause)


class TestScopedObjectId:
    """The id the scope names, only for an OBJECT scope with an integer id"""

    def test_an_object_scope_names_its_id(self) -> None:
        """The frontend's shape"""
        assert scoped_object_id(OBJECT_SCOPE) == OBJECT_ID

    def test_both_keys_in_one_clause(self) -> None:
        """The clauses are read together"""
        assert scoped_object_id([{REF_TYPE_KEY: ObjectReferenceType.OBJECT.value, OBJECT_ID_KEY: OBJECT_ID}]) \
            == OBJECT_ID

    @pytest.mark.parametrize('scope', [
        [{REF_TYPE_KEY: ObjectReferenceType.OBJECT_GROUP.value}, {OBJECT_ID_KEY: OBJECT_ID}],
        [{OBJECT_ID_KEY: OBJECT_ID}],
        [{REF_TYPE_KEY: ObjectReferenceType.OBJECT.value}],
        [{REF_TYPE_KEY: ObjectReferenceType.OBJECT.value}, Builder.in_(OBJECT_ID_KEY, [OBJECT_ID])],
        [{REF_TYPE_KEY: ObjectReferenceType.OBJECT.value}, {OBJECT_ID_KEY: str(OBJECT_ID)}],
        [{REF_TYPE_KEY: ObjectReferenceType.OBJECT.value}, {OBJECT_ID_KEY: True}],
        [],
    ])
    def test_no_object_id(self, scope: list[dict[str, Any]]) -> None:
        """A group scope, a half scope, an operator, a string or a boolean id"""
        assert scoped_object_id(scope) is None


def test_the_expanded_scope_matches_the_object_and_its_groups() -> None:
    """The object's own scope OR the groups' scope - each paired with its ref_type"""
    assert object_or_group_scope(OBJECT_ID, GROUP_IDS) == {'$or': [
        {'$and': [{REF_TYPE_KEY: ObjectReferenceType.OBJECT}, {OBJECT_ID_KEY: OBJECT_ID}]},
        {'$and': [{REF_TYPE_KEY: ObjectReferenceType.OBJECT_GROUP}, {OBJECT_ID_KEY: {'$in': GROUP_IDS}}]},
    ]}


class TestExpandObjectScopeFilter:
    """The scope is widened to the object's groups; everything else of the filter is kept"""

    @staticmethod
    def _object_found(managers: dict[ManagerType, MagicMock]) -> None:
        """The scoped object exists and belongs to GROUP_IDS"""
        managers.setdefault(ManagerType.OBJECTS, MagicMock()).get_object.return_value = {
            CmdbObjectKey.PUBLIC_ID.value: OBJECT_ID, CmdbObjectKey.TYPE_ID.value: TYPE_ID,
        }
        managers.setdefault(ManagerType.OBJECT_GROUP, MagicMock()).find_group_ids_containing.return_value = GROUP_IDS

    def test_the_other_clauses_stay_beside_the_expansion(self, managers: dict[ManagerType, MagicMock]) -> None:
        """The list's search narrows the expanded scope instead of being dropped"""
        self._object_found(managers)

        expanded = expand_object_scope_filter({MONGO_AND_OPERATOR: [*OBJECT_SCOPE, SEARCH_CLAUSE]}, MagicMock())

        assert expanded == {MONGO_AND_OPERATOR: [object_or_group_scope(OBJECT_ID, GROUP_IDS), SEARCH_CLAUSE]}

    def test_the_other_top_level_keys_stay(self, managers: dict[ManagerType, MagicMock]) -> None:
        """A key beside the $and is kept as it is"""
        self._object_found(managers)

        expanded = expand_object_scope_filter({MONGO_AND_OPERATOR: OBJECT_SCOPE, PAGING_KEY: RISK_ID}, MagicMock())

        assert expanded == {
            PAGING_KEY: RISK_ID, MONGO_AND_OPERATOR: [object_or_group_scope(OBJECT_ID, GROUP_IDS)],
        }

    def test_the_groups_are_looked_up_by_the_object_and_its_type(
        self, managers: dict[ManagerType, MagicMock],
    ) -> None:
        """Static groups list the object, dynamic ones its type"""
        self._object_found(managers)

        expand_object_scope_filter({MONGO_AND_OPERATOR: OBJECT_SCOPE}, MagicMock())

        managers[ManagerType.OBJECTS].get_object.assert_called_once_with(OBJECT_ID)
        managers[ManagerType.OBJECT_GROUP].find_group_ids_containing.assert_called_once_with(OBJECT_ID, TYPE_ID)

    @pytest.mark.parametrize('query_filter', [
        None,
        [Builder.match_({OBJECT_ID_KEY: OBJECT_ID})],
        {OBJECT_ID_KEY: OBJECT_ID},
        {MONGO_AND_OPERATOR: {OBJECT_ID_KEY: OBJECT_ID}},
        {MONGO_AND_OPERATOR: [Builder.in_(OBJECT_ID_KEY, [OBJECT_ID]), OBJECT_SCOPE[0]]},
        {MONGO_AND_OPERATOR: [{REF_TYPE_KEY: ObjectReferenceType.OBJECT_GROUP.value}, OBJECT_SCOPE[1]]},
        {MONGO_AND_OPERATOR: [OBJECT_SCOPE[0], {OBJECT_ID_KEY: OBJECT_ID, PAGING_KEY: RISK_ID}]},
    ])
    def test_any_other_filter_is_left_alone_without_a_read(
        self, managers: dict[ManagerType, MagicMock], query_filter: Any,
    ) -> None:
        """No filter, a pipeline, no $and, an operator id, a group scope, a scope mixed into another clause"""
        assert expand_object_scope_filter(query_filter, MagicMock()) is query_filter
        assert not managers

    def test_a_missing_object_leaves_the_filter_alone(self, managers: dict[ManagerType, MagicMock]) -> None:
        """Nothing to widen to, and no group read"""
        managers[ManagerType.OBJECTS] = MagicMock()
        managers[ManagerType.OBJECTS].get_object.return_value = None
        query_filter: dict[str, Any] = {MONGO_AND_OPERATOR: [*OBJECT_SCOPE, SEARCH_CLAUSE]}

        assert expand_object_scope_filter(query_filter, MagicMock()) is query_filter
        assert ManagerType.OBJECT_GROUP not in managers

    def test_the_other_object_is_read(self, managers: dict[ManagerType, MagicMock]) -> None:
        """The id comes from the scope, not from anywhere else"""
        self._object_found(managers)

        expand_object_scope_filter(
            {MONGO_AND_OPERATOR: [OBJECT_SCOPE[0], {OBJECT_ID_KEY: OTHER_OBJECT_ID}]}, MagicMock(),
        )

        managers[ManagerType.OBJECTS].get_object.assert_called_once_with(OTHER_OBJECT_ID)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    naming ids                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCollectNamingIds:
    """Every id lands in the set of the collection that names it"""

    def test_each_reference_lands_in_its_own_set(self) -> None:
        """Distinct ids per set, so a swapped set shows"""
        ids = collect_naming_ids([
            _ra(object_id=OBJECT_ID, interviewed_persons=INTERVIEWED_IDS,
                responsible_persons_id=RESPONSIBLE_PERSON_ID),
            _ra(risk_id=None, object_id_ref_type=ObjectReferenceType.OBJECT_GROUP, object_id=OBJECT_GROUP_ID,
                responsible_persons_id=RESPONSIBLE_GROUP_ID,
                responsible_persons_id_ref_type=PersonReferenceType.PERSON_GROUP),
        ])

        assert ids == RiskAssessmentNamingIds(
            risk_ids={RISK_ID},
            object_group_ids={OBJECT_GROUP_ID},
            object_ids={OBJECT_ID},
            person_ids=set(INTERVIEWED_IDS),
            responsible_person_ids={RESPONSIBLE_PERSON_ID},
            responsible_person_group_ids={RESPONSIBLE_GROUP_ID},
        )

    def test_what_names_nothing_adds_nothing(self) -> None:
        """No risk, interviewed persons that are no list, an unknown responsible ref_type"""
        ids = collect_naming_ids([
            _ra(risk_id=None, object_id_ref_type=None, interviewed_persons=None,
                responsible_persons_id=RESPONSIBLE_PERSON_ID, responsible_persons_id_ref_type=UNKNOWN_REF_TYPE),
        ])

        assert ids == RiskAssessmentNamingIds()

    def test_an_empty_page(self) -> None:
        """Nothing referenced"""
        assert collect_naming_ids([]) == RiskAssessmentNamingIds()


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    name reads                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestNameLookup:
    """One projected read per collection"""

    def test_no_ids_read_nothing(self) -> None:
        """An empty set costs no query"""
        manager = MagicMock()

        assert name_lookup(manager, set(), RiskKey.NAME.value) == {}
        manager.find_all.assert_not_called()

    def test_the_read_is_projected_to_the_id_and_the_name(self) -> None:
        """Sorted ids, no _id, only the name key"""
        manager = MagicMock()
        manager.find_all.return_value = [{PUBLIC_ID_FIELD: RISK_ID, RiskKey.NAME.value: RISK_NAME}]

        assert name_lookup(manager, {RISK_ID}, RiskKey.NAME.value) == {RISK_ID: RISK_NAME}
        manager.find_all.assert_called_once_with(
            criteria=Builder.in_(PUBLIC_ID_FIELD, [RISK_ID]),
            projection={MONGO_ID_FIELD: 0, PUBLIC_ID_FIELD: 1, RiskKey.NAME.value: 1},
        )

    def test_a_document_without_its_name_is_unnamed(self) -> None:
        """The key is optional on a stored document"""
        manager = MagicMock()
        manager.find_all.return_value = [{PUBLIC_ID_FIELD: RISK_ID}]

        assert name_lookup(manager, {RISK_ID}, RiskKey.NAME.value) == {RISK_ID: None}


class TestFetchNamingLookups:
    """The names of a page, one read per collection it references"""

    def test_each_collection_is_read_for_its_own_ids(self, managers: dict[ManagerType, MagicMock]) -> None:
        """Interviewed and responsible persons in ONE read; the objects as the caller"""
        user = MagicMock()
        ids = RiskAssessmentNamingIds(
            risk_ids={RISK_ID}, object_group_ids={OBJECT_GROUP_ID}, object_ids={OBJECT_ID},
            person_ids=set(INTERVIEWED_IDS), responsible_person_ids={RESPONSIBLE_PERSON_ID},
            responsible_person_group_ids={RESPONSIBLE_GROUP_ID},
        )

        with patch(f'{HELPER_PATH}.name_lookup', side_effect=lambda _m, public_ids, key: (key, public_ids)):
            lookups = fetch_naming_lookups(ids, user)

        assert lookups.risks == (RiskKey.NAME.value, {RISK_ID})
        assert lookups.object_groups == (ObjectGroupKey.NAME.value, {OBJECT_GROUP_ID})
        assert lookups.persons == (PersonKey.DISPLAY_NAME.value, {*INTERVIEWED_IDS, RESPONSIBLE_PERSON_ID})
        assert lookups.person_groups == (PersonGroupKey.NAME.value, {RESPONSIBLE_GROUP_ID})
        assert lookups.object_summaries is managers[ManagerType.OBJECTS].get_summary_lines_lookup.return_value
        managers[ManagerType.OBJECTS].get_summary_lines_lookup.assert_called_once_with(
            [OBJECT_ID], user=user, permission=AccessControlPermission.READ,
        )

    def test_the_managers_match_their_collections(self, managers: dict[ManagerType, MagicMock]) -> None:
        """Each read goes to the manager of its collection"""
        for manager_type in (ManagerType.RISK, ManagerType.OBJECT_GROUP, ManagerType.PERSON, ManagerType.PERSON_GROUP):
            managers[manager_type] = MagicMock()
            managers[manager_type].find_all.return_value = [
                {PUBLIC_ID_FIELD: RISK_ID, RiskKey.NAME.value: manager_type.name,
                 PersonKey.DISPLAY_NAME.value: manager_type.name},
            ]

        lookups = fetch_naming_lookups(RiskAssessmentNamingIds(
            risk_ids={RISK_ID}, object_group_ids={RISK_ID}, person_ids={RISK_ID},
            responsible_person_group_ids={RISK_ID},
        ), MagicMock())

        assert lookups.risks == {RISK_ID: ManagerType.RISK.name}
        assert lookups.object_groups == {RISK_ID: ManagerType.OBJECT_GROUP.name}
        assert lookups.persons == {RISK_ID: ManagerType.PERSON.name}
        assert lookups.person_groups == {RISK_ID: ManagerType.PERSON_GROUP.name}

    def test_no_objects_read_no_summary_lines(self, managers: dict[ManagerType, MagicMock]) -> None:
        """A page referencing no object costs no summary read"""
        lookups = fetch_naming_lookups(RiskAssessmentNamingIds(), MagicMock())

        assert lookups == RiskAssessmentNamingLookups()
        assert ManagerType.OBJECTS not in managers


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   naming block                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildRaNaming:
    """The naming block, from the lookups alone"""

    def test_an_object_assessment(self) -> None:
        """The risk name and the object's summary line, no group name"""
        assert build_ra_naming(_ra(), LOOKUPS) == {
            RiskAssessmentNamingKey.RISK_ID_NAME.value: RISK_NAME,
            RiskAssessmentNamingKey.OBJECT_GROUP_ID_NAME.value: None,
            RiskAssessmentNamingKey.OBJECT_ID_NAME.value: OBJECT_SUMMARY,
            RiskAssessmentNamingKey.INTERVIEWED_PERSONS_NAMES.value: None,
            RiskAssessmentNamingKey.RESPONSIBLE_PERSONS_ID_NAME.value: None,
        }

    def test_an_object_group_assessment(self) -> None:
        """The group's name, no summary line"""
        naming = build_ra_naming(
            _ra(object_id_ref_type=ObjectReferenceType.OBJECT_GROUP, object_id=OBJECT_GROUP_ID), LOOKUPS,
        )

        assert naming[RiskAssessmentNamingKey.OBJECT_GROUP_ID_NAME.value] == OBJECT_GROUP_NAME
        assert naming[RiskAssessmentNamingKey.OBJECT_ID_NAME.value] is None

    def test_interviewed_persons_resolve_in_order_and_unknown_ones_drop(self) -> None:
        """Unknown ids leave no gap"""
        naming = build_ra_naming(_ra(interviewed_persons=[*INTERVIEWED_IDS, UNKNOWN_PERSON_ID]), LOOKUPS)

        assert naming[RiskAssessmentNamingKey.INTERVIEWED_PERSONS_NAMES.value] == INTERVIEWED_NAMES

    def test_only_unknown_interviewed_persons_name_nobody(self) -> None:
        """An empty name list reads as None"""
        naming = build_ra_naming(_ra(interviewed_persons=[UNKNOWN_PERSON_ID]), LOOKUPS)

        assert naming[RiskAssessmentNamingKey.INTERVIEWED_PERSONS_NAMES.value] is None


class TestResponsibleName:
    """The responsible party is looked up where its ref_type says"""

    def test_a_person(self) -> None:
        """The persons lookup"""
        assert responsible_name(_ra(responsible_persons_id=RESPONSIBLE_PERSON_ID), LOOKUPS) == RESPONSIBLE_PERSON_NAME

    def test_a_person_group(self) -> None:
        """The person groups lookup"""
        assert responsible_name(_ra(
            responsible_persons_id=RESPONSIBLE_GROUP_ID,
            responsible_persons_id_ref_type=PersonReferenceType.PERSON_GROUP,
        ), LOOKUPS) == RESPONSIBLE_GROUP_NAME

    def test_a_person_id_is_not_looked_up_among_the_groups(self) -> None:
        """The same id names different documents in the two collections"""
        assert responsible_name(_ra(
            responsible_persons_id=RESPONSIBLE_PERSON_ID,
            responsible_persons_id_ref_type=PersonReferenceType.PERSON_GROUP,
        ), LOOKUPS) is None

    @pytest.mark.parametrize('fields', [
        {'responsible_persons_id': None},
        {'responsible_persons_id': RESPONSIBLE_PERSON_ID, 'responsible_persons_id_ref_type': UNKNOWN_REF_TYPE},
    ])
    def test_nobody(self, fields: dict[str, Any]) -> None:
        """No id, or a ref_type naming neither collection"""
        assert responsible_name(_ra(**fields), LOOKUPS) is None


def test_a_listed_assessment_is_its_document_with_naming() -> None:
    """The JSON document, the naming block under its key"""
    risk_assessment = _ra()

    with patch(f'{HELPER_PATH}.IsmsRiskAssessment.to_json', return_value={PUBLIC_ID_FIELD: PAGE_SIZE}) as to_json:
        document = named_risk_assessment(risk_assessment, LOOKUPS)

    to_json.assert_called_once_with(risk_assessment)
    assert document == {
        PUBLIC_ID_FIELD: PAGE_SIZE, RISK_ASSESSMENT_NAMING_KEY: build_ra_naming(risk_assessment, LOOKUPS),
    }
