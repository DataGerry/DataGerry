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
Integration tests for what a search term finds, run against a real MongoDB

The full-search and quick-search pipelines are built by their real builders and run by the real
ObjectsManager over documents written straight into the collection, so what is pinned is the MATCH,
not the pipeline's shape: an object is found by its own values or through a REFERENCE row pointing at
an object whose own values match - never through a number that happens to equal an object's id, never
through an object the caller may not read - and a hit comes back exactly as stored. The database-side
join a very broad term falls back to must find exactly the same objects
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import QuickSearchPipelineBuilder, SearchPipelineBuilder
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.search import search_reference_match
from cmdb.framework.search.search_constants import SearchFormType
from cmdb.framework.search.search_param import SearchParam
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

OPEN_TYPE_ID: int = 88901
HIDDEN_TYPE_ID: int = 88902

TARGET_ID: int = 88911          # 'Router-X' - what the other objects point at
NUMBER_ID: int = 88912          # a number field whose value equals TARGET_ID, and no reference
REFERRER_ID: int = 88913        # a reference row to TARGET_ID
LOCATION_REFERRER_ID: int = 88914
SECTION_REFERRER_ID: int = 88915
UNTYPED_REFERRER_ID: int = 88916  # a legacy row carrying TARGET_ID without a 'type'
EDITED_ID: int = 88917          # edited, with a multi-data section: must come back whole
HIDDEN_ID: int = 88918          # of a type the user group may not read
HIDDEN_REFERRER_ID: int = 88919  # readable, pointing at HIDDEN_ID

ALL_OBJECT_IDS: list[int] = [
    TARGET_ID, NUMBER_ID, REFERRER_ID, LOCATION_REFERRER_ID, SECTION_REFERRER_ID, UNTYPED_REFERRER_ID,
    EDITED_ID, HIDDEN_ID, HIDDEN_REFERRER_ID,
]

TARGET_TERM: str = 'Router'
REFERRER_OWN_TERM: str = 'beta-host'
EDITED_TERM: str = 'edited-host'
HIDDEN_TERM: str = 'secret-token'
SHARED_FIELD: str = 'owner'   # stored by the target only - must not appear on a referrer's hit
EDITOR_ID: int = 5
MDS: list[dict[str, Any]] = [{'section_id': 'mds', 'values': [{'multi_data_id': 1, 'data': []}]}]


@pytest.fixture(autouse=True)
def _app_context(rest_api):
    """Pushes the REST API app context so ManagerProvider (current_app.database_manager) resolves."""
    with rest_api.application.app_context():
        yield


def _row(name: str, value: Any, kind: str | None = 'text') -> dict[str, Any]:
    """One stored field row; `kind=None` stores a legacy row without a 'type'."""
    row: dict[str, Any] = {'name': name, 'value': value}

    if kind is not None:
        row['type'] = kind

    return row


def _object(public_id: int, rows: list[dict[str, Any]], type_id: int = OPEN_TYPE_ID, **extra: Any) -> dict[str, Any]:
    """A stored CmdbObject document."""
    return {
        'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': rows, **extra,
    }


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the two types and the objects; removes them after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [OPEN_TYPE_ID, HIDDEN_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': ALL_OBJECT_IDS}})

    _purge()
    hidden_type: dict[str, Any] = make_type_doc(HIDDEN_TYPE_ID, 'search-ref-hidden')
    hidden_type['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}
    types.insert_many([make_type_doc(OPEN_TYPE_ID, 'search-ref-open'), hidden_type])
    objects.insert_many([
        _object(TARGET_ID, [_row('hostname', 'Router-X'), _row(SHARED_FIELD, 'NetOps')]),
        _object(NUMBER_ID, [_row('hostname', 'alpha-host'), _row('rack_units', TARGET_ID, 'number')]),
        _object(REFERRER_ID, [_row('hostname', REFERRER_OWN_TERM), _row('uplink', TARGET_ID, 'ref')]),
        _object(LOCATION_REFERRER_ID, [_row('hostname', 'gamma-host'), _row('dg_location', TARGET_ID, 'location')]),
        _object(SECTION_REFERRER_ID, [_row('hostname', 'delta-host'),
                                      _row('sec-field', TARGET_ID, 'ref-section-field')]),
        _object(UNTYPED_REFERRER_ID, [_row('hostname', 'epsilon-host'), _row('legacy', TARGET_ID, None)]),
        _object(EDITED_ID, [_row('hostname', EDITED_TERM)], editor_id=EDITOR_ID, multi_data_sections=MDS),
        _object(HIDDEN_ID, [_row('hostname', HIDDEN_TERM)], type_id=HIDDEN_TYPE_ID),
        _object(HIDDEN_REFERRER_ID, [_row('hostname', 'zeta-host'), _row('uplink', HIDDEN_ID, 'ref')]),
    ])
    yield
    _purge()


def _user(group_id: int) -> CmdbUser:
    """A request user of the given group."""
    return CmdbUser(public_id=1, user_name='search-ref', active=True, group_id=group_id)


def _search(terms: list[str], user: CmdbUser | None = None) -> list[dict[str, Any]]:
    """Runs a full search for the TEXT terms (AND), restricted to this module's objects, as `user`."""
    params: list[SearchParam] = [SearchParam(term, SearchFormType.TEXT.value) for term in terms]
    pipeline: list[dict] = SearchPipelineBuilder().build(
        params, user=user, permission=AccessControlPermission.READ if user else None,
    )
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    scope: dict[str, Any] = {'$match': {'public_id': {'$in': ALL_OBJECT_IDS}}}

    return list(objects_manager.aggregate_objects(pipeline=[scope, *pipeline]))


def _ids(documents: list[dict[str, Any]]) -> list[int]:
    """The public_ids of the documents, in order."""
    return [document['public_id'] for document in documents]


class TestWhatATermFinds:
    """Own values, and reference rows pointing at a matching object."""

    def test_the_matching_object_itself(self) -> None:
        """The object whose own value matches"""
        assert TARGET_ID in _ids(_search([TARGET_TERM]))

    def test_a_reference_row_finds_its_referrer(self) -> None:
        """An object pointing at a match is found through it"""
        assert REFERRER_ID in _ids(_search([TARGET_TERM]))

    @pytest.mark.parametrize('referrer', [LOCATION_REFERRER_ID, SECTION_REFERRER_ID], ids=['location', 'ref-section'])
    def test_every_reference_kind_finds_its_referrer(self, referrer: int) -> None:
        """A location and a reference section's field point at an object as much as a plain reference"""
        assert referrer in _ids(_search([TARGET_TERM]))

    def test_a_number_equal_to_an_id_finds_nothing(self) -> None:
        """A number field whose value equals the match's id is a number, not a reference"""
        assert NUMBER_ID not in _ids(_search([TARGET_TERM]))

    def test_a_legacy_untyped_row_finds_nothing(self) -> None:
        """Without a 'type' the row cannot be told from a number, so it does not count"""
        assert UNTYPED_REFERRER_ID not in _ids(_search([TARGET_TERM]))

    def test_two_terms_are_and_each_satisfiable_by_a_reference(self) -> None:
        """One term by the object's own value, the other through its reference - both have to hold"""
        assert _ids(_search([REFERRER_OWN_TERM, TARGET_TERM])) == [REFERRER_ID]

    def test_the_hits_are_ordered_by_public_id(self) -> None:
        """The page the facet cuts is taken from this order"""
        found: list[int] = _ids(_search([TARGET_TERM]))

        assert found == sorted(found)


class TestAHitComesBackAsStored:
    """Nothing is projected away and nothing is folded in."""

    def test_the_editor_and_the_multi_data_sections_survive(self) -> None:
        """Neither is projected away from a hit"""
        hit: dict[str, Any] = _search([EDITED_TERM])[0]

        assert hit['editor_id'] == EDITOR_ID
        assert hit['multi_data_sections'] == MDS

    def test_a_referrers_fields_are_its_own(self) -> None:
        """The referenced object's rows are not appended - its 'owner' would read as the referrer's"""
        hit: dict[str, Any] = next(doc for doc in _search([TARGET_TERM]) if doc['public_id'] == REFERRER_ID)

        assert [row['name'] for row in hit['fields']] == ['hostname', 'uplink']
        assert SHARED_FIELD not in [row['name'] for row in hit['fields']]


class TestTheAclOfTheReferencedObject:
    """An object is not found through an object the caller may not read."""

    def test_a_caller_who_may_not_read_the_target_does_not_find_its_referrer(self) -> None:
        """The user group may not read the hidden type, so neither it nor what points at it is a hit"""
        found: list[int] = _ids(_search([HIDDEN_TERM], user=_user(USER_GROUP_ID)))

        assert HIDDEN_REFERRER_ID not in found
        assert HIDDEN_ID not in found

    def test_a_caller_who_may_read_it_does(self) -> None:
        """The admin group may, so the reference is followed"""
        assert HIDDEN_REFERRER_ID in _ids(_search([HIDDEN_TERM], user=_user(ADMIN_GROUP_ID)))


class TestTheJoinFallback:
    """A term too broad for an id list is joined in the database, with the same answer."""

    @pytest.mark.parametrize('terms', [[TARGET_TERM], [REFERRER_OWN_TERM, TARGET_TERM]], ids=['one', 'two'])
    def test_the_join_finds_exactly_the_same_objects(self, terms: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
        """Forcing the join for every term changes nothing about the hits"""
        with_ids: list[int] = _ids(_search(terms))

        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', 0)

        assert _ids(_search(terms)) == with_ids

    def test_the_join_respects_the_acl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The joined objects pass the same ACL stages"""
        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', 0)

        assert HIDDEN_REFERRER_ID not in _ids(_search([HIDDEN_TERM], user=_user(USER_GROUP_ID)))

    def test_the_join_leaves_no_working_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The hits leave the stages as they entered"""
        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', 0)

        assert all(key.startswith('__dg') is False for hit in _search([TARGET_TERM]) for key in hit)


class TestQuickSearchAgrees:
    """The count the search bar shows is the number of objects the search then lists."""

    @pytest.mark.parametrize('term', [TARGET_TERM, HIDDEN_TERM, EDITED_TERM])
    @pytest.mark.parametrize('group_id', [ADMIN_GROUP_ID, USER_GROUP_ID], ids=['admin', 'user'])
    def test_the_count_equals_the_hits(self, term: str, group_id: int) -> None:
        """Same term, same caller, same answer"""
        user: CmdbUser = _user(group_id)
        pipeline: list[dict] = QuickSearchPipelineBuilder().build(
            search_term=term, user=user, permission=AccessControlPermission.READ,
        )
        objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
        scope: dict[str, Any] = {'$match': {'public_id': {'$in': ALL_OBJECT_IDS}}}

        counts: list[dict[str, Any]] = list(objects_manager.aggregate_objects(pipeline=[scope, *pipeline]))

        assert (counts[0]['total'] if counts else 0) == len(_search([term], user=user))
