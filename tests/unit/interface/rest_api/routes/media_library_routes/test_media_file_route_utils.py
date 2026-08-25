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
Unit tests for the MediaFile route utilities

Filter-building / naming helpers exercised inside a minimal Flask request context and against
lightweight stub managers: generate_metadata_filter (reference -> $in, plain keys, missing -> 400),
generate_collection_parameters (the search-term filter), create_attachment_name (copy-suffixing) and
recursive_delete_filter (parent/child collection, and that it no longer re-fetches each node's root
document). The shared request-parsing helpers (get_file_in_request / get_element_from_data_request)
moved to routes_helper and are tested there.

Also the steps the upload / update routes were decomposed into: resolving a stored file (404 for a
missing one), reading the required ``attachment`` parameter, and building the metadata / merged document
each write persists.
"""
from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import (
    build_updated_file_data,
    build_upload_metadata,
    generate_metadata_filter,
    generate_collection_parameters,
    create_attachment_name,
    get_reference_attachment_or_abort,
    get_stored_file_or_abort,
    recursive_delete_filter,
)
# -------------------------------------------------------------------------------------------------------------------- #

app = Flask(__name__)


class TestGenerateMetadataFilter:
    """generate_metadata_filter maps metadata into a MongoDB filter, prefixing keys with 'metadata.'."""

    def test_plain_keys_are_prefixed(self) -> None:
        """Non-reference keys become metadata.<key> equality filters."""
        result = generate_metadata_filter('metadata', params={'parent': 5, 'folder': True})

        assert result == {'metadata.parent': 5, 'metadata.folder': True}

    def test_reference_scalar_becomes_in(self) -> None:
        """A scalar reference is wrapped in an $in filter."""
        result = generate_metadata_filter('metadata', params={'reference': 7})

        assert result == {'metadata.reference': {'$in': [7]}}

    def test_reference_list_becomes_in(self) -> None:
        """A list reference is passed through as an $in filter."""
        result = generate_metadata_filter('metadata', params={'reference': [1, 2]})

        assert result == {'metadata.reference': {'$in': [1, 2]}}

    def test_missing_metadata_aborts_400(self) -> None:
        """No metadata at all aborts with 400."""
        with app.test_request_context('/', method='GET'):
            with pytest.raises(HTTPException) as exc:
                generate_metadata_filter('metadata', _request=request)

            assert exc.value.code == 400


class TestGenerateCollectionParameters:
    """The search-term branch builds an $or over the three searchable file fields."""

    @staticmethod
    def _params(search_term: str | None = None) -> SimpleNamespace:
        """Minimal CollectionParameters stand-in carrying the optional filters the helper reads."""
        optional: dict[str, Any] = {'metadata': '{}'}

        if search_term is not None:
            optional['searchTerm'] = search_term

        return SimpleNamespace(optional=optional)

    @staticmethod
    def _searched_fields(result: dict) -> set[str]:
        """The field names carrying a $regex in the built filter."""
        or_clauses = result['$and'][1]['$or']

        return {field for clause in or_clauses for field, value in clause.items() if '$regex' in value}

    def test_searches_the_three_file_fields(self) -> None:
        """filename, reference_type and mime_type are all matched against the term."""
        result = generate_collection_parameters(self._params('report'))

        assert self._searched_fields(result) == {'filename', 'metadata.reference_type', 'metadata.mime_type'}

    def test_folders_are_excluded_from_a_search(self) -> None:
        """A search returns files, never the folders containing them."""
        result = generate_collection_parameters(self._params('report'))

        assert result['$and'][0] == {'metadata.folder': False}

    def test_a_multi_word_term_can_match(self) -> None:
        """Regression: the regex options defaulted to 'imsx', and the 'x' flag made the engine strip
        unescaped whitespace from the pattern - so searching a file called 'my file.png' for
        'my file' silently matched nothing."""
        result = generate_collection_parameters(self._params('my file'))
        options = {clause[field]['$options']
                   for clause in result['$and'][1]['$or']
                   for field in clause if '$regex' in clause[field]}

        assert options == {'ims'}

    def test_the_term_reaches_the_pattern_verbatim(self) -> None:
        """The search box value is used as the pattern, whitespace included."""
        result = generate_collection_parameters(self._params('my file'))

        assert result['$and'][1]['$or'][0]['filename']['$regex'] == 'my file'

    def test_a_numeric_term_also_matches_ids(self) -> None:
        """A digits-only term additionally matches public_id / reference / parent."""
        result = generate_collection_parameters(self._params('7'))
        or_clauses = result['$and'][1]['$or']

        assert {'public_id': 7} in or_clauses
        assert {'metadata.parent': 7} in or_clauses

    def test_without_a_search_term_it_falls_back_to_the_metadata_filter(self) -> None:
        """No search term means the metadata filter path, not an $and/$or search."""
        result = generate_collection_parameters(self._params())

        assert '$and' not in result


class _ExistsStub:
    """Stub manager whose file_exists returns the queued booleans in order."""

    def __init__(self, exists_sequence: list[bool]) -> None:
        self._exists = list(exists_sequence)

    def file_exists(self, _metadata: dict) -> bool:
        """Pops the next queued existence result (False once exhausted)."""
        return self._exists.pop(0) if self._exists else False


class TestCreateAttachmentName:
    """create_attachment_name appends a copy_(n)_ prefix until the name is unique."""

    def test_unique_name_unchanged(self) -> None:
        """A name that does not collide is returned unchanged."""
        assert create_attachment_name('file.txt', 0, {}, _ExistsStub([False])) == 'file.txt'

    def test_collision_gets_copy_prefix(self) -> None:
        """A colliding name gets a copy_(1)_ prefix once a free slot is found."""
        # exists once (original), then free
        assert create_attachment_name('file.txt', 0, {}, _ExistsStub([True, False])) == 'copy_(1)_file.txt'


class _DeleteStub:
    """Stub manager returning children per parent id and recording the queries it received."""

    def __init__(self, children_by_parent: dict[int, list[dict[str, Any]]]) -> None:
        self._children = children_by_parent
        self.queries: list[dict[str, Any]] = []

    def get_many_media_files(self, metadata: dict) -> SimpleNamespace:
        """Records the query and returns the children of the requested parent id."""
        self.queries.append(metadata)
        parent = metadata.get('metadata.parent')
        result = self._children.get(parent, [])
        return SimpleNamespace(result=result, total=len(result))


class TestRecursiveDeleteFilter:
    """recursive_delete_filter collects a node and all its descendants, one query per node."""

    def test_collects_node_and_descendants(self) -> None:
        """The root plus its (nested) children ids are returned in traversal order."""
        stub = _DeleteStub({1: [{'public_id': 2}, {'public_id': 3}], 2: [{'public_id': 4}], 3: [], 4: []})

        assert recursive_delete_filter(1, stub) == [1, 2, 4, 3]

    def test_only_queries_children_no_root_refetch(self) -> None:
        """Every query filters by metadata.parent - the redundant per-node root lookup is gone."""
        stub = _DeleteStub({1: [{'public_id': 2}], 2: []})

        recursive_delete_filter(1, stub)

        assert all('metadata.parent' in query for query in stub.queries)
        assert all('public_id' not in query for query in stub.queries)


PUBLIC_ID: int = 4242
AUTHOR_ID: int = 7
UPLOAD_NAME: str = 'picture.png'


class _StoredFileStub:
    """A MediaFilesManager answering get_file with a fixed document"""

    def __init__(self, stored: dict[str, Any] | None) -> None:
        self.stored = stored

    def get_file(self, metadata: dict[str, Any], blob: bool = False) -> dict[str, Any] | None:
        """Returns the configured document, ignoring the filter"""
        del metadata, blob

        return self.stored


class TestGetStoredFileOrAbort:
    """get_stored_file_or_abort turns the manager's None into a 404."""

    def test_returns_the_stored_file(self) -> None:
        """A present file is handed back unchanged."""
        stored = {'public_id': PUBLIC_ID, 'filename': UPLOAD_NAME}

        assert get_stored_file_or_abort(_StoredFileStub(stored), PUBLIC_ID) is stored

    def test_missing_file_aborts_404(self) -> None:
        """
        Without this the None reached the next subscript and the request ended as a 500

        The manager swallows GridFS's NoFile, so None is how "not there" arrives.
        """
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                get_stored_file_or_abort(_StoredFileStub(None), PUBLIC_ID)

        assert exc_info.value.code == 404


class TestGetReferenceAttachmentOrAbort:
    """The update route's 'attachment' query parameter is required and must be an object."""

    def test_parses_the_parameter(self) -> None:
        """A JSON object is returned as a dict."""
        with app.test_request_context('/?attachment={"reference": true}'):
            assert get_reference_attachment_or_abort() == {'reference': True}

    def test_missing_parameter_aborts_400(self) -> None:
        """It used to be a TypeError from json.loads(None) on the way to a 500."""
        with app.test_request_context('/'):
            with pytest.raises(HTTPException) as exc_info:
                get_reference_attachment_or_abort()

        assert exc_info.value.code == 400

    def test_malformed_parameter_aborts_400(self) -> None:
        """A value that is not JSON is a client error."""
        with app.test_request_context('/?attachment=not-json'):
            with pytest.raises(HTTPException) as exc_info:
                get_reference_attachment_or_abort()

        assert exc_info.value.code == 400

    def test_non_object_parameter_aborts_400(self) -> None:
        """A bare JSON value carries no 'reference' key to read."""
        with app.test_request_context('/?attachment=[1]'):
            with pytest.raises(HTTPException) as exc_info:
                get_reference_attachment_or_abort()

        assert exc_info.value.code == 400


class TestBuildUploadMetadata:
    """build_upload_metadata completes what an upload is stored with."""

    def test_stamps_the_author_and_mime_type(self) -> None:
        """Both are server-owned, whatever the request said."""
        upload = SimpleNamespace(mimetype='image/png', filename=UPLOAD_NAME)

        result = build_upload_metadata({'author_id': 999}, upload, AUTHOR_ID, None)

        assert result['author_id'] == AUTHOR_ID
        assert result['mime_type'] == 'image/png'

    def test_carries_the_replaced_references(self) -> None:
        """A replacement is the same library entry with new content, so what points at it survives."""
        upload = SimpleNamespace(mimetype='image/png', filename=UPLOAD_NAME)
        replaced = {'metadata': {'reference': 11, 'reference_type': 'object'}}

        result = build_upload_metadata({}, upload, AUTHOR_ID, replaced)

        assert result['reference'] == 11
        assert result['reference_type'] == 'object'

    def test_a_replaced_file_without_reference_keys_is_tolerated(self) -> None:
        """An entry written before the keys existed carries neither - a KeyError -> 500 before."""
        upload = SimpleNamespace(mimetype='image/png', filename=UPLOAD_NAME)

        result = build_upload_metadata({}, upload, AUTHOR_ID, {'metadata': {}})

        assert result['reference'] is None
        assert result['reference_type'] is None

    def test_a_replaced_file_without_metadata_is_tolerated(self) -> None:
        """Nor is the metadata sub-document guaranteed to be there."""
        upload = SimpleNamespace(mimetype='image/png', filename=UPLOAD_NAME)

        result = build_upload_metadata({}, upload, AUTHOR_ID, {'public_id': PUBLIC_ID})

        assert result['reference'] is None
        assert result['reference_type'] is None


class TestBuildUpdatedFileData:
    """build_updated_file_data merges the payload onto the stored document."""

    def test_merges_name_metadata_and_author(self) -> None:
        """The stored identity stays, the payload supplies name and metadata."""
        stored = {'public_id': PUBLIC_ID, 'filename': 'old.png', 'metadata': {'author_id': 1}}
        payload = {'public_id': 999, 'filename': 'new.png', 'metadata': {'parent': 3}}

        result = build_updated_file_data(stored, payload, AUTHOR_ID)

        assert result['public_id'] == PUBLIC_ID
        assert result['filename'] == 'new.png'
        assert result['metadata']['parent'] == 3
        assert result['metadata']['author_id'] == AUTHOR_ID

    @pytest.mark.parametrize('payload', [
        {'metadata': {}},
        {'filename': 'new.png'},
    ], ids=['no-filename', 'no-metadata'])
    def test_incomplete_payload_aborts_400(self, payload: dict[str, Any]) -> None:
        """A missing key used to be a KeyError -> 500."""
        stored = {'public_id': PUBLIC_ID, 'filename': 'old.png', 'metadata': {}}

        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                build_updated_file_data(stored, payload, AUTHOR_ID)

        assert exc_info.value.code == 400
