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
Integration tests for what the object list's ``?search=`` finds, run against a real MongoDB

The stages are built by ``build_object_search_stages`` - its first query runs for real - and executed by the real
ObjectsManager over documents written straight into the collection, with the caller's ACL applied to the listed
objects the way the listing applies it. What is pinned is the MATCH:

- an object is found by its own public_id, timestamps or field values, or through a REFERENCE row pointing at an
  object whose field values match - never through a number that happens to equal an object's id, never through a
  legacy row without a ``type``, never through an object the caller may not read
- every value is matched as a string, on both sides: a number value is found as text, its own or a referenced one
- the term is a literal, case-insensitive
- the hits come back exactly as stored, and the database-side join a broad term falls back to finds the same
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.framework.search import search_reference_match
from cmdb.framework.search.object_list_search import build_object_search_stages
from cmdb.security.acl.builder import build_acl_pipeline
from cmdb.security.acl.permission import AccessControlPermission
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

OPEN_TYPE_ID: int = 89101
HIDDEN_TYPE_ID: int = 89102

TARGET_ID: int = 89111            # 'Switch-Q' - what the other objects point at
NUMBER_ID: int = 89112            # a number field whose value equals TARGET_ID, and no reference
REFERRER_ID: int = 89113          # a ref row to TARGET_ID
LOCATION_REFERRER_ID: int = 89114
SECTION_REFERRER_ID: int = 89115
UNTYPED_REFERRER_ID: int = 89116  # a legacy row carrying TARGET_ID without a 'type'
EDITED_ID: int = 89117            # edited, with a multi-data section: must come back whole
HIDDEN_ID: int = 89118            # of a type the user group may not read
HIDDEN_REFERRER_ID: int = 89119   # readable, pointing at HIDDEN_ID
COUNTED_ID: int = 89120           # holds the number PORT_COUNT
COUNTED_REFERRER_ID: int = 89121  # references COUNTED_ID

ALL_OBJECT_IDS: list[int] = [
    TARGET_ID, NUMBER_ID, REFERRER_ID, LOCATION_REFERRER_ID, SECTION_REFERRER_ID, UNTYPED_REFERRER_ID,
    EDITED_ID, HIDDEN_ID, HIDDEN_REFERRER_ID, COUNTED_ID, COUNTED_REFERRER_ID,
]

TARGET_TERM: str = 'switch-q'           # lower case: the match is case-insensitive
REFERRER_OWN_TERM: str = 'kappa-host'
EDITED_TERM: str = 'lambda-host'
HIDDEN_TERM: str = 'classified-blob'
PUNCTUATION_VALUE: str = 'C++ (EU)'
PORT_COUNT: int = 4877321                # unique enough not to appear in any id or timestamp
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
    hidden_type: dict[str, Any] = make_type_doc(HIDDEN_TYPE_ID, 'list-search-hidden')
    hidden_type['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}
    types.insert_many([make_type_doc(OPEN_TYPE_ID, 'list-search-open'), hidden_type])
    objects.insert_many([
        _object(TARGET_ID, [_row('hostname', 'Switch-Q')]),
        _object(NUMBER_ID, [_row('hostname', 'iota-host'), _row('rack_units', TARGET_ID, 'number')]),
        _object(REFERRER_ID, [_row('hostname', REFERRER_OWN_TERM), _row('uplink', TARGET_ID, 'ref')]),
        _object(LOCATION_REFERRER_ID, [_row('hostname', 'mu-host'), _row('dg_location', TARGET_ID, 'location')]),
        _object(SECTION_REFERRER_ID, [_row('hostname', 'nu-host'),
                                      _row('sec-field', TARGET_ID, 'ref-section-field')]),
        _object(UNTYPED_REFERRER_ID, [_row('hostname', 'xi-host'), _row('legacy', TARGET_ID, None)]),
        _object(EDITED_ID, [_row('hostname', EDITED_TERM), _row('note', PUNCTUATION_VALUE)],
                editor_id=EDITOR_ID, multi_data_sections=MDS),
        _object(HIDDEN_ID, [_row('hostname', HIDDEN_TERM)], type_id=HIDDEN_TYPE_ID),
        _object(HIDDEN_REFERRER_ID, [_row('hostname', 'omicron-host'), _row('uplink', HIDDEN_ID, 'ref')]),
        _object(COUNTED_ID, [_row('hostname', 'pi-host'), _row('ports', PORT_COUNT, 'number')]),
        _object(COUNTED_REFERRER_ID, [_row('hostname', 'rho-host'), _row('uplink', COUNTED_ID, 'ref')]),
    ])
    yield
    _purge()


def _user(group_id: int) -> CmdbUser:
    """A request user of the given group."""
    return CmdbUser(public_id=1, user_name='list-search', active=True, group_id=group_id)


def _search(term: str, user: CmdbUser | None = None) -> list[dict[str, Any]]:
    """Lists this module's objects searched by `term`, the caller's ACL on both the references and the listing."""
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    acl_stages: list[dict[str, Any]] = build_acl_pipeline(user, AccessControlPermission.READ) if user else []
    scope: dict[str, Any] = {'$match': {'public_id': {'$in': ALL_OBJECT_IDS}}}
    stages: list[dict[str, Any]] = build_object_search_stages(term, objects_manager, acl_stages)

    return list(objects_manager.aggregate_objects(
        pipeline=[scope, *stages, *acl_stages, {'$sort': {'public_id': 1}}],
    ))


def _ids(documents: list[dict[str, Any]]) -> list[int]:
    """The public_ids of the documents, in order."""
    return [document['public_id'] for document in documents]


class TestWhatATermFinds:
    """Own values, typed reference rows - and nothing else."""

    def test_the_matching_object_itself_case_insensitively(self) -> None:
        """'switch-q' finds 'Switch-Q'"""
        assert TARGET_ID in _ids(_search(TARGET_TERM))

    @pytest.mark.parametrize('referrer', [REFERRER_ID, LOCATION_REFERRER_ID, SECTION_REFERRER_ID],
                             ids=['ref', 'location', 'ref-section-field'])
    def test_every_reference_kind_finds_its_referrer(self, referrer: int) -> None:
        """A ref, a location and a ref-section row are each followed"""
        assert referrer in _ids(_search(TARGET_TERM))

    def test_a_number_equal_to_an_id_finds_nothing(self) -> None:
        """The defect: a number field holding the target's id is a number, not a reference"""
        assert NUMBER_ID not in _ids(_search(TARGET_TERM))

    def test_a_legacy_untyped_row_finds_nothing(self) -> None:
        """A row without a stored type is not followed"""
        assert UNTYPED_REFERRER_ID not in _ids(_search(TARGET_TERM))

    def test_the_exact_hit_set(self) -> None:
        """The target and its three typed referrers - and nothing else of this module"""
        assert _ids(_search(TARGET_TERM)) == [TARGET_ID, REFERRER_ID, LOCATION_REFERRER_ID, SECTION_REFERRER_ID]

    def test_a_referrers_own_value_still_finds_it(self) -> None:
        """Its own values are searched as before"""
        assert _ids(_search(REFERRER_OWN_TERM)) == [REFERRER_ID]


class TestEverythingIsAString:
    """Numbers and ids match as text, on both sides; the term is a literal."""

    def test_an_own_number_value_matches_as_text(self) -> None:
        """'4877321' finds the object holding the number"""
        assert COUNTED_ID in _ids(_search(str(PORT_COUNT)))

    def test_a_referenced_number_value_matches_as_text(self) -> None:
        """...and what references it - the referenced side is compared as strings too"""
        assert COUNTED_REFERRER_ID in _ids(_search(str(PORT_COUNT)))

    def test_the_public_id_is_searchable(self) -> None:
        """A listed object's own id, as text"""
        assert EDITED_ID in _ids(_search(str(EDITED_ID)))

    def test_a_stored_id_is_an_own_value(self) -> None:
        """Searching the target's id finds every object STORING that id, as text - its own value, any row kind"""
        assert _ids(_search(str(TARGET_ID))) == [
            TARGET_ID, NUMBER_ID, REFERRER_ID, LOCATION_REFERRER_ID, SECTION_REFERRER_ID, UNTYPED_REFERRER_ID,
        ]

    def test_punctuation_is_matched_as_itself(self) -> None:
        """'C++ (EU)' is a literal, not a pattern"""
        assert _ids(_search(PUNCTUATION_VALUE)) == [EDITED_ID]

    def test_a_wildcard_matches_nothing(self) -> None:
        """'.*' is two characters"""
        assert not _search('.*')


class TestTheHitsComeBackWhole:
    """Nothing is projected away and no working field is left."""

    def test_the_editor_and_the_multi_data_sections_survive(self) -> None:
        """The stored document, exactly"""
        hit: dict[str, Any] = _search(EDITED_TERM)[0]

        assert hit['editor_id'] == EDITOR_ID
        assert hit['multi_data_sections'] == MDS
        assert not [key for key in hit if key.startswith('__dg')]


class TestTheAclOfTheReferencedObject:
    """An object is not found through an object the caller may not read."""

    def test_a_caller_who_may_not_read_the_target_does_not_find_its_referrer(self) -> None:
        """The user group may not read the hidden type, so neither it nor what points at it is a hit"""
        found: list[int] = _ids(_search(HIDDEN_TERM, user=_user(USER_GROUP_ID)))

        assert HIDDEN_REFERRER_ID not in found
        assert HIDDEN_ID not in found

    def test_a_caller_who_may_read_it_does(self) -> None:
        """The admin group may, so the reference is followed"""
        assert _ids(_search(HIDDEN_TERM, user=_user(ADMIN_GROUP_ID))) == [HIDDEN_ID, HIDDEN_REFERRER_ID]


class TestTheJoinFallback:
    """A term too broad for an id list is joined in the database, with the same answer."""

    @pytest.mark.parametrize('term', [TARGET_TERM, str(PORT_COUNT), REFERRER_OWN_TERM, str(EDITED_ID)])
    def test_the_join_finds_exactly_the_same_objects(self, term: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """Forcing the join changes nothing about the hits - including the own-only public_id match"""
        with_ids: list[int] = _ids(_search(term))

        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', 0)

        assert _ids(_search(term)) == with_ids

    def test_the_join_respects_the_acl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The joined objects pass the same ACL stages"""
        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', 0)

        assert HIDDEN_REFERRER_ID not in _ids(_search(HIDDEN_TERM, user=_user(USER_GROUP_ID)))

    def test_the_join_leaves_no_working_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The hits leave the stages as they entered"""
        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', 0)

        assert not [key for hit in _search(TARGET_TERM) for key in hit if key.startswith('__dg')]
