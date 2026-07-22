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

Pure request-parsing / filter-building helpers exercised inside a minimal Flask request context and
against lightweight stub managers: get_file_in_request (returns the file, aborts 400 when absent - the
fixed guard), get_element_from_data_request, generate_metadata_filter (reference -> $in, plain keys,
missing -> 400), create_attachment_name (copy-suffixing) and recursive_delete_filter (parent/child
collection, and that it no longer re-fetches each node's root document).
"""
import json
from io import BytesIO
from types import SimpleNamespace
from typing import Any

import pytest
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import (
    get_file_in_request,
    get_element_from_data_request,
    generate_metadata_filter,
    create_attachment_name,
    recursive_delete_filter,
)
# -------------------------------------------------------------------------------------------------------------------- #

app = Flask(__name__)


class TestGetFileInRequest:
    """get_file_in_request returns the uploaded file or aborts 400 when it is missing."""

    def test_returns_file_when_present(self) -> None:
        """The uploaded file is returned when present."""
        with app.test_request_context(
            '/', method='POST',
            data={'file': (BytesIO(b'x'), 'pic.png')},
            content_type='multipart/form-data',
        ):
            assert get_file_in_request('file').filename == 'pic.png'

    def test_missing_file_aborts_400(self) -> None:
        """A missing file aborts with 400 (the guard now works - request.files.get returns None)."""
        with app.test_request_context('/', method='POST', data={}, content_type='multipart/form-data'):
            with pytest.raises(HTTPException) as exc:
                get_file_in_request('file')

            assert exc.value.code == 400


class TestGetElementFromDataRequest:
    """get_element_from_data_request parses a JSON form field, or returns None on miss / bad JSON."""

    def test_parses_json_field(self) -> None:
        """A valid JSON form field is parsed."""
        with app.test_request_context(
            '/', method='POST', data={'metadata': json.dumps({'a': 1})}, content_type='multipart/form-data'
        ):
            assert get_element_from_data_request('metadata', request) == {'a': 1}

    def test_missing_field_returns_none(self) -> None:
        """A missing field returns None."""
        with app.test_request_context('/', method='POST', data={}, content_type='multipart/form-data'):
            assert get_element_from_data_request('metadata', request) is None


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
