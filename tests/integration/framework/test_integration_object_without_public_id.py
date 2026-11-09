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
Integration tests for a stored object without a public_id, run against a real MongoDB

Every write path sets a public_id, but the unique index admits ONE document without it (missing and null both index
as null), so a damaged database can hold one. Three things are pinned, each for both forms of the damage:

- **a search does not fail on it and finds nothing through it.** The objects a term matches are collected by their
  public_id to find the objects referencing them: a missing id failed the search, and a null one made every object
  with an empty reference field a match - in the id-list path and in the database-side join a broad term takes
- **a listing that reaches it is refused, naming it** - the document's _id, so it can be found among thousands
- **the boot reports it** - one null query on the unique public_id index
"""
from datetime import datetime, timezone
from typing import Any, Iterator

import pytest
from bson import ObjectId
from pymongo.collection import Collection

from cmdb.database import MongoDatabaseManager
from cmdb.database.database_services.collection_validator import CollectionValidator
from cmdb.manager import ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager.query_builder import BuilderParameters, QuickSearchPipelineBuilder, SearchPipelineBuilder
from cmdb.models.object_model import CmdbObject
from cmdb.models.object_model.object_constants import OBJECT_WITHOUT_PUBLIC_ID_MSG
from cmdb.models.type_model import CmdbType
from cmdb.framework.search import search_reference_match
from cmdb.framework.search.search_constants import SearchFormType
from cmdb.framework.search.search_param import SearchParam
from cmdb.errors.manager.objects_manager import ObjectsManagerIterationError
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

# Every test here reaches the database through ManagerProvider, which reads the REST app's context
pytestmark = pytest.mark.usefixtures('rest_api_app_context')

TYPE_ID: int = 88950
TARGET_ID: int = 88951           # its own value matches TARGET_TERM
REFERRER_ID: int = 88952         # a reference row to TARGET_ID
UNSET_REFERENCE_ID: int = 88953  # a reference row whose value is null - what a null id would match
MISSING_VALUE_ID: int = 88954    # a reference row without a 'value' key at all
ALL_OBJECT_IDS: list[int] = [TARGET_ID, REFERRER_ID, UNSET_REFERENCE_ID, MISSING_VALUE_ID]

TARGET_TERM: str = 'Gateway-445'
STRAY_TERM: str = 'stray-445'    # only the damaged document carries it
# The damaged document's value: its own term, and TARGET_TERM too - a term that also matches a sound object is what
# sends a search down the join, where the damaged document is then a joinable object
STRAY_VALUE: str = f'{STRAY_TERM} {TARGET_TERM}'
STRAY_DOCUMENT_ID: str = '65f0c0ffee00000000000445'

# The two forms of the damage: the key left out, and stored as null
STRAY_FORMS: list[str] = ['missing', 'null']
# The id-list path, and the database-side join a term too broad for an id list takes
MATCH_PATHS: list[str] = ['id-list', 'join']


def _object(public_id: int, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """A stored CmdbObject document of the module's type."""
    return {
        'public_id': public_id, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc), 'fields': rows,
    }


def _stray(form: str) -> dict[str, Any]:
    """The damaged document: the module's type, STRAY_VALUE as its value, no usable public_id."""
    document: dict[str, Any] = _object(0, [{'name': 'hostname', 'value': STRAY_VALUE, 'type': 'text'}])
    document['_id'] = ObjectId(STRAY_DOCUMENT_ID)

    if form == 'missing':
        del document['public_id']
    else:
        document['public_id'] = None

    return document


@pytest.fixture(name='objects')
def _objects(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Collection]:
    """Seeds the type and the sound objects; removes them, and any damaged document of the type, after."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': TYPE_ID})
        objects.delete_many({'type_id': TYPE_ID})

    _purge()
    types.insert_one(make_type_doc(TYPE_ID, 'without-public-id'))
    objects.insert_many([
        _object(TARGET_ID, [{'name': 'hostname', 'value': TARGET_TERM, 'type': 'text'}]),
        _object(REFERRER_ID, [{'name': 'hostname', 'value': 'beta', 'type': 'text'},
                              {'name': 'uplink', 'value': TARGET_ID, 'type': 'ref'}]),
        _object(UNSET_REFERENCE_ID, [{'name': 'hostname', 'value': 'gamma', 'type': 'text'},
                                     {'name': 'uplink', 'value': None, 'type': 'ref'}]),
        _object(MISSING_VALUE_ID, [{'name': 'hostname', 'value': 'delta', 'type': 'text'},
                                   {'name': 'uplink', 'type': 'ref'}]),
    ])
    yield objects
    _purge()


def _force(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sends the search down the join when asked to - an id list allowing no id at all"""
    if path == 'join':
        monkeypatch.setattr(search_reference_match, 'MAX_REFERENCED_MATCH_IDS', 0)


def _search_ids(term: str) -> list[int]:
    """The public_ids a full search for the TEXT term finds among the module's sound objects."""
    pipeline: list[dict] = SearchPipelineBuilder().build([SearchParam(term, SearchFormType.TEXT.value)])
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, None)
    scope: dict[str, Any] = {'$match': {'public_id': {'$in': ALL_OBJECT_IDS}}}

    return [document['public_id'] for document in objects_manager.aggregate_objects(pipeline=[scope, *pipeline])]


def _quick_count(term: str) -> int:
    """The search bar's total for the term among the module's sound objects."""
    pipeline: list[dict] = QuickSearchPipelineBuilder().build(search_term=term)
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, None)
    scope: dict[str, Any] = {'$match': {'public_id': {'$in': ALL_OBJECT_IDS}}}
    counts: list[dict[str, Any]] = list(objects_manager.aggregate_objects(pipeline=[scope, *pipeline]))

    return counts[0]['total'] if counts else 0


@pytest.mark.parametrize('path', MATCH_PATHS)
@pytest.mark.parametrize('form', STRAY_FORMS)
class TestASearchIgnoresIt:
    """No failure, and nothing found through the damaged document"""

    def test_a_term_it_matches_finds_no_sound_object(
            self, objects: Collection, form: str, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """A null id matched every empty reference field; a missing one failed the search"""
        objects.insert_one(_stray(form))
        _force(path, monkeypatch)

        assert not _search_ids(STRAY_TERM)
        assert _quick_count(STRAY_TERM) == 0

    def test_a_sound_term_is_answered_as_without_it(
            self, objects: Collection, form: str, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """The target and its referrer - not the objects with an empty reference field"""
        objects.insert_one(_stray(form))
        _force(path, monkeypatch)

        assert _search_ids(TARGET_TERM) == [TARGET_ID, REFERRER_ID]
        assert _quick_count(TARGET_TERM) == len([TARGET_ID, REFERRER_ID])


@pytest.mark.parametrize('path', MATCH_PATHS)
def test_without_it_an_empty_reference_field_is_never_a_match(
        objects: Collection, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline: an unset reference row points at nothing, on either path"""
    _force(path, monkeypatch)

    assert _search_ids(TARGET_TERM) == [TARGET_ID, REFERRER_ID]
    assert objects.count_documents({'type_id': TYPE_ID}) == len(ALL_OBJECT_IDS)


@pytest.mark.parametrize('form', STRAY_FORMS)
def test_a_listing_that_reaches_it_is_refused_naming_it(objects: Collection, form: str) -> None:
    """Refused rather than skipped - but the refusal names the document's _id"""
    objects.insert_one(_stray(form))
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, None)

    with pytest.raises(ObjectsManagerIterationError) as refusal:
        objects_manager.iterate(BuilderParameters(criteria={'type_id': TYPE_ID}))

    assert OBJECT_WITHOUT_PUBLIC_ID_MSG.format(document_id=STRAY_DOCUMENT_ID) in str(refusal.value)


@pytest.mark.parametrize('form', STRAY_FORMS)
def test_the_boot_reports_it(
        objects: Collection, form: str, database_manager: MongoDatabaseManager, database_name: str) -> None:
    """One, for either form - and none once it is gone"""
    validator = CollectionValidator(database_name, database_manager)
    objects.insert_one(_stray(form))

    assert validator.report_objects_without_public_id() == 1

    objects.delete_one({'_id': _stray(form)['_id']})

    assert validator.report_objects_without_public_id() == 0
