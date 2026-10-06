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
recursive_delete_filter (parent/child collection, and that it does not re-fetch each node's root
document). The shared request-parsing helpers (get_file_in_request / get_element_from_data_request)
live in routes_helper and are not covered here.

Also the steps the upload / update routes are made of: resolving a stored file (404 for a
missing one), reading the required ``attachment`` parameter, reading the upload form (which refuses
metadata carrying an undeclared key), and building the metadata / merged document each write persists.
"""
import json
from io import BytesIO
from types import SimpleNamespace
from typing import Any

from unittest.mock import MagicMock

import pytest
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from cmdb.framework.media_library import MediaFileMetadataKey
from cmdb.errors.manager.media_files_manager import MediaFileManagerGetError

from cmdb.interface.rest_api.routes.media_library_routes.media_file_route_utils import (
    abort_if_filename_unusable,
    abort_unless_usable_parent,
    build_updated_file_data,
    build_upload_metadata,
    generate_metadata_filter,
    generate_collection_parameters,
    create_attachment_name,
    get_reference_attachment_or_abort,
    get_stored_file_or_abort,
    get_upload_from_request,
    metadata_field,
    recursive_delete_filter,
    validate_upload_metadata,
    validate_update_body,
    stream_grid_file,
    unique_name_filter,
)
from cmdb.interface.rest_api.routes.media_library_routes.media_file_constants import (
    FOLDER_FLAG_IMMUTABLE_MSG,
    PARENT_CYCLE_MSG,
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
        """The regex options must not carry the 'x' flag: it makes the engine strip unescaped
        whitespace from the pattern - so searching a file called 'my file.png' for 'my file' would
        silently match nothing."""
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

    def test_a_failed_existence_check_becomes_a_get_error(self) -> None:
        """
        The uniqueness check is a database read, and a failure there must not look like "unique"

        Letting it escape untyped would reach the upload route's generic handler as a 500; as this
        manager's get error the route reports it the way it reports every other read failure.
        """
        manager = MagicMock()
        manager.file_exists.side_effect = RuntimeError('read failed')

        with pytest.raises(MediaFileManagerGetError):
            create_attachment_name('file.txt', 0, {}, manager)


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
        """Every query filters by metadata.parent - there is no per-node root lookup."""
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

    def get_file(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """Returns the configured document, ignoring the filter"""
        del metadata

        return self.stored


class TestGetStoredFileOrAbort:
    """get_stored_file_or_abort turns the manager's None into a 404."""

    def test_returns_the_stored_file(self) -> None:
        """A present file is handed back unchanged."""
        stored = {'public_id': PUBLIC_ID, 'filename': UPLOAD_NAME}

        assert get_stored_file_or_abort(_StoredFileStub(stored), PUBLIC_ID) is stored

    def test_missing_file_aborts_404(self) -> None:
        """
        Without the abort the None would reach the next subscript and end the request as a 500

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
        """A missing parameter is a 400, not a TypeError from json.loads(None) surfacing as a 500."""
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
        """An entry written before the keys existed carries neither, and is read without a KeyError."""
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

    def test_the_metadata_is_stored_whole_like_an_uploads(self) -> None:
        """Every declared key is present; a key the payload leaves out is None (the payload is the full object)."""
        stored = {'public_id': PUBLIC_ID, 'filename': 'a.png', 'metadata': {'reference': [9], 'parent': 3}}
        payload = {'public_id': PUBLIC_ID, 'filename': 'a.png', 'metadata': {'folder': False}}

        metadata = build_updated_file_data(stored, payload, AUTHOR_ID)['metadata']

        assert set(metadata) == {key.value for key in MediaFileMetadataKey}
        assert metadata['reference'] is None
        assert metadata['parent'] is None

    def test_the_mime_type_stays_the_stored_one(self) -> None:
        """An update changes no content, so the client's mime type is ignored."""
        stored = {'public_id': PUBLIC_ID, 'filename': 'a.png', 'metadata': {'mime_type': 'image/png'}}
        payload = {'public_id': PUBLIC_ID, 'filename': 'a.png', 'metadata': {'mime_type': 'evil/x'}}

        assert build_updated_file_data(stored, payload, AUTHOR_ID)['metadata']['mime_type'] == 'image/png'

    def test_the_author_is_stamped_over_the_payloads(self) -> None:
        """The last modifier is whoever sent the update."""
        stored = {'public_id': PUBLIC_ID, 'filename': 'a.png', 'metadata': {}}
        payload = {'public_id': PUBLIC_ID, 'filename': 'a.png', 'metadata': {'author_id': 999}}

        assert build_updated_file_data(stored, payload, AUTHOR_ID)['metadata']['author_id'] == AUTHOR_ID

    @pytest.mark.parametrize(('stored_folder', 'sent_folder'), [(True, False), (False, True), (None, True)])
    def test_the_folder_flag_can_not_change(self, stored_folder, sent_folder: bool) -> None:
        """A folder holding files can not become a file, nor a file with content a folder."""
        stored_metadata = {} if stored_folder is None else {'folder': stored_folder}
        stored = {'public_id': PUBLIC_ID, 'filename': 'a', 'metadata': stored_metadata}
        payload = {'public_id': PUBLIC_ID, 'filename': 'a', 'metadata': {'folder': sent_folder}}

        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                build_updated_file_data(stored, payload, AUTHOR_ID)

        assert exc_info.value.code == 400
        assert exc_info.value.description == FOLDER_FLAG_IMMUTABLE_MSG

    def test_a_folder_stays_a_folder(self) -> None:
        """Sending the stored flag back is the normal case."""
        stored = {'public_id': PUBLIC_ID, 'filename': 'dir', 'metadata': {'folder': True}}
        payload = {'public_id': PUBLIC_ID, 'filename': 'renamed', 'metadata': {'folder': True}}

        assert build_updated_file_data(stored, payload, AUTHOR_ID)['metadata']['folder'] is True


def _valid_body(**overrides: Any) -> dict[str, Any]:
    """An update body as the file explorer sends it - the whole FileElement."""
    body: dict[str, Any] = {
        'public_id': PUBLIC_ID, 'filename': 'a.png', 'size': 3, 'children': [], 'hasSubFolders': False,
        'metadata': {key.value: None for key in MediaFileMetadataKey} | {'folder': False},
    }
    body.update(overrides)

    return body


class TestValidateUpdateBody:
    """validate_update_body holds the update body to MEDIA_FILE_UPDATE_SCHEMA."""

    def test_the_frontends_body_passes(self) -> None:
        """The explorer's extra keys are tolerated."""
        body = _valid_body()

        with app.test_request_context():
            assert validate_update_body(body) is body

    @pytest.mark.parametrize('body', [None, [1], 'text', 5])
    def test_a_body_that_is_not_an_object_aborts_400(self, body: Any) -> None:
        """It used to fail on the way to a 500 (null) or on the first lookup."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_update_body(body)

        assert exc_info.value.code == 400

    @pytest.mark.parametrize('missing', ['public_id', 'filename', 'metadata'])
    def test_a_missing_key_aborts_400_naming_it(self, missing: str) -> None:
        """The three keys an update is made of are required."""
        body = _valid_body()
        del body[missing]

        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_update_body(body)

        assert exc_info.value.code == 400
        assert missing in exc_info.value.description

    @pytest.mark.parametrize(('key', 'value'), [
        ('public_id', '4242'), ('public_id', True), ('filename', 7), ('filename', ''), ('filename', '   '),
        ('filename', 'a/b'), ('filename', 'x' * 256), ('metadata', [1]), ('metadata', None),
    ])
    def test_an_unusable_value_aborts_400_naming_the_key(self, key: str, value: Any) -> None:
        """An id is an integer, a name follows the naming rule, the metadata is an object."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_update_body(_valid_body(**{key: value}))

        assert exc_info.value.code == 400
        assert key in exc_info.value.description

    def test_a_name_at_the_limit_passes(self) -> None:
        """255 characters is the last usable length."""
        with app.test_request_context():
            validate_update_body(_valid_body(filename='x' * 255))

    def test_an_undeclared_metadata_key_aborts_400_naming_it(self) -> None:
        """The same refusal the upload answers."""
        body = _valid_body()
        body['metadata']['evil'] = 1

        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_update_body(body)

        assert exc_info.value.code == 400
        assert 'evil' in exc_info.value.description

    def test_a_metadata_value_of_the_wrong_type_aborts_400(self) -> None:
        """The metadata runs the upload's schema."""
        body = _valid_body()
        body['metadata']['parent'] = 'abc'

        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_update_body(body)

        assert 'parent' in exc_info.value.description


class TestAbortIfFilenameUnusable:
    """abort_if_filename_unusable holds an uploaded file's name to the naming rule."""

    @pytest.mark.parametrize('name', ['', '   ', 'a/b', 'x' * 256, None])
    def test_an_unusable_name_aborts_400(self, name: Any) -> None:
        """Blank, a path separator, too long, or no name at all."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                abort_if_filename_unusable(name)

        assert exc_info.value.code == 400

    def test_a_usable_name_passes(self) -> None:
        """Spaces, dots and non-ASCII characters are fine."""
        with app.test_request_context():
            abort_if_filename_unusable('Bericht März 2026.pdf')


class _TreeStub:
    """A MediaFilesManager answering get_file out of a {public_id: document} tree, counting the reads."""

    def __init__(self, entries: dict[int, dict[str, Any]]) -> None:
        self.entries = entries
        self.reads: list[int] = []

    def get_file(self, metadata: dict[str, Any]) -> dict[str, Any] | None:
        """The entry the filter's public_id names."""
        self.reads.append(metadata['public_id'])

        return self.entries.get(metadata['public_id'])


def _entry(public_id: int, parent: int | None, folder: bool = True) -> dict[str, Any]:
    """A stored library entry."""
    return {'public_id': public_id, 'filename': f'entry-{public_id}', 'metadata': {'folder': folder, 'parent': parent}}


# root folder 1 > folder 2 > folder 3; folder 4 at the root; file 5 in folder 1
TREE: dict[int, dict[str, Any]] = {
    1: _entry(1, None), 2: _entry(2, 1), 3: _entry(3, 2), 4: _entry(4, None), 5: _entry(5, 1, folder=False),
}


class TestAbortUnlessUsableParent:
    """abort_unless_usable_parent: an existing folder, and not inside the moved entry."""

    def test_the_root_is_always_usable(self) -> None:
        """None is the library root and reads nothing."""
        manager = _TreeStub(TREE)

        with app.test_request_context():
            abort_unless_usable_parent(manager, None, moved_id=1)

        assert not manager.reads

    @pytest.mark.parametrize(('parent', 'reason'), [(99, 'not found'), (5, 'is a file')])
    def test_a_missing_or_file_parent_aborts_400(self, parent: int, reason: str) -> None:
        """Nothing may sit inside a file or a folder that does not exist."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                abort_unless_usable_parent(_TreeStub(TREE), parent)

        assert exc_info.value.code == 400
        assert reason in exc_info.value.description

    @pytest.mark.parametrize('target', [1, 2, 3])
    def test_a_folder_can_not_move_into_itself_or_its_subtree(self, target: int) -> None:
        """Folder 1 into 1, 2 or 3: each would drop it out of the tree."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                abort_unless_usable_parent(_TreeStub(TREE), target, moved_id=1)

        assert exc_info.value.description == PARENT_CYCLE_MSG

    @pytest.mark.parametrize(('moved_id', 'target'), [(3, 4), (2, 4), (4, 3), (3, 1)])
    def test_a_move_outside_the_own_subtree_passes(self, moved_id: int, target: int) -> None:
        """Sideways, up or down into another branch."""
        with app.test_request_context():
            abort_unless_usable_parent(_TreeStub(TREE), target, moved_id=moved_id)

    def test_the_walk_stops_at_a_loop_already_stored_above(self) -> None:
        """Two folders naming each other: the walk ends instead of spinning, and the move is judged."""
        looped = {7: _entry(7, 8), 8: _entry(8, 7)}

        with app.test_request_context():
            abort_unless_usable_parent(_TreeStub(looped), 7, moved_id=1)

    def test_an_upload_reads_only_the_parent(self) -> None:
        """No moved entry, no walk: one read."""
        manager = _TreeStub(TREE)

        with app.test_request_context():
            abort_unless_usable_parent(manager, 3)

        assert manager.reads == [3]

    def test_the_walk_reads_each_ancestor_once(self) -> None:
        """Up from folder 3: 3, 2, 1, then the root."""
        manager = _TreeStub(TREE)

        with app.test_request_context():
            abort_unless_usable_parent(manager, 3, moved_id=4)

        assert manager.reads == [3, 2, 1]


class TestUniqueNameFilter:
    """unique_name_filter asks for ANOTHER entry of the same name in the same folder."""

    def test_the_entry_itself_is_excluded(self) -> None:
        """A kept name must not find its own entry."""
        data = {'public_id': PUBLIC_ID, 'filename': 'a.png', 'metadata': {'parent': 3}}

        assert unique_name_filter(data) == {
            'filename': 'a.png', 'metadata.parent': 3, 'public_id': {'$ne': PUBLIC_ID},
        }


class TestMetadataField:
    """metadata_field builds the dotted path of a key inside the metadata sub-document."""

    def test_a_declared_key_becomes_its_path(self) -> None:
        """An enum member is resolved to its value."""
        assert metadata_field(MediaFileMetadataKey.PARENT) == 'metadata.parent'

    def test_a_raw_key_is_prefixed_as_is(self) -> None:
        """A key coming from a request filter is not required to be declared."""
        assert metadata_field('whatever') == 'metadata.whatever'


class TestValidateUploadMetadata:
    """The upload metadata is client-supplied, so only the declared keys may appear in it."""

    def test_declared_keys_pass(self) -> None:
        """Everything MediaFileMetadataKey names is accepted, including the server-owned keys."""
        metadata = {key.value: None for key in MediaFileMetadataKey}
        metadata[MediaFileMetadataKey.FOLDER.value] = False

        with app.test_request_context():
            validate_upload_metadata(metadata)

    def test_no_metadata_at_all_passes(self) -> None:
        """An empty object carries no undeclared key - the builder fills the defaults in."""
        with app.test_request_context():
            validate_upload_metadata({})

    def test_an_undeclared_key_aborts_400(self) -> None:
        """It must not reach the manager and fail the write with a database-flavoured message."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_upload_metadata({'public_id': 5})

        assert exc_info.value.code == 400

    def test_the_offending_key_is_named(self) -> None:
        """The client has to be told WHICH key it may not send."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_upload_metadata({MediaFileMetadataKey.PARENT.value: 1, 'bogus': 2})

        assert 'bogus' in exc_info.value.description

    def test_every_offending_key_is_named(self) -> None:
        """Two undeclared keys are reported together, so the client does not fix them one per request."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_upload_metadata({'alpha': 1, 'beta': 2})

        assert 'alpha' in exc_info.value.description
        assert 'beta' in exc_info.value.description

    def test_metadata_that_is_not_an_object_aborts_400(self) -> None:
        """A JSON list or scalar is a client error, not a TypeError on the way to a 500."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_upload_metadata(['not', 'an', 'object'])

        assert exc_info.value.code == 400

    @pytest.mark.parametrize(('key', 'value'), [
        ('folder', 'yes'), ('folder', None), ('parent', 'abc'), ('parent', True), ('reference', 'x'),
        ('reference', [1, 'two']), ('reference', [1, True]), ('author_id', 1.5), ('reference_type', 3),
        ('mime_type', ['text/plain']),
    ])
    def test_a_value_of_the_wrong_type_aborts_400_naming_the_key(self, key: str, value: Any) -> None:
        """Each declared key holds its declared type - the refusal says which key failed."""
        with app.test_request_context():
            with pytest.raises(HTTPException) as exc_info:
                validate_upload_metadata({key: value})

        assert exc_info.value.code == 400
        assert key in exc_info.value.description

    @pytest.mark.parametrize('metadata', [
        {'reference': 5, 'reference_type': 'object'}, {'reference': [1, 2]}, {'folder': True, 'parent': None},
        {'permission': {'anything': 'goes'}},
    ])
    def test_values_the_frontend_sends_pass(self, metadata: dict[str, Any]) -> None:
        """One reference or a list of them, a folder flag, a reserved permission of any shape."""
        with app.test_request_context():
            validate_upload_metadata(metadata)


class TestGetUploadFromRequest:
    """The upload form is read as file + filter + metadata, and its metadata is validated."""

    @staticmethod
    def _form(metadata: dict[str, Any]) -> dict[str, Any]:
        """Builds the multipart form an upload arrives as."""
        return {
            'file': (BytesIO(b'payload'), 'upload.txt'),
            'metadata': json.dumps(metadata),
        }

    def test_reads_the_file_filter_and_metadata(self) -> None:
        """The filter identifies an already stored file of that name in that folder."""
        form = self._form({MediaFileMetadataKey.PARENT.value: 3})

        with app.test_request_context('/', method='POST', data=form,
                                      content_type='multipart/form-data'):
            upload, existing_filter, metadata = get_upload_from_request(request)

        assert upload.filename == 'upload.txt'
        assert existing_filter == {'metadata.parent': 3, 'filename': 'upload.txt'}
        assert metadata == {MediaFileMetadataKey.PARENT.value: 3}

    def test_a_wrongly_typed_metadata_value_is_named(self) -> None:
        """A reference that is no id used to answer "Metadata was not provided!"."""
        form = self._form({MediaFileMetadataKey.REFERENCE.value: 'x'})

        with app.test_request_context('/', method='POST', data=form,
                                      content_type='multipart/form-data'):
            with pytest.raises(HTTPException) as exc_info:
                get_upload_from_request(request)

        assert exc_info.value.code == 400
        assert 'reference' in exc_info.value.description

    def test_an_unusable_file_name_aborts_400(self) -> None:
        """The uploaded part's name follows the naming rule too."""
        form = {'file': (BytesIO(b'payload'), '   '), 'metadata': json.dumps({})}

        with app.test_request_context('/', method='POST', data=form,
                                      content_type='multipart/form-data'):
            with pytest.raises(HTTPException) as exc_info:
                get_upload_from_request(request)

        assert exc_info.value.code == 400

    def test_an_undeclared_metadata_key_aborts_400(self) -> None:
        """The refusal happens before anything is streamed into GridFS."""
        form = self._form({MediaFileMetadataKey.PARENT.value: 3, 'permissions': 'rw'})

        with app.test_request_context('/', method='POST', data=form,
                                      content_type='multipart/form-data'):
            with pytest.raises(HTTPException) as exc_info:
                get_upload_from_request(request)

        assert exc_info.value.code == 400
        assert 'permissions' in exc_info.value.description


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  stream_grid_file                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStreamGridFile:
    """The download body: one GridFS chunk at a time, and the file closed however the stream ends."""

    @staticmethod
    def _grid_out(*chunks: bytes) -> MagicMock:
        """A GridOut stand-in whose readchunk yields the given chunks, then b''."""
        grid_out = MagicMock()
        grid_out.readchunk.side_effect = [*chunks, b'']

        return grid_out

    def test_yields_every_chunk_in_order(self) -> None:
        """Nothing is concatenated in memory - the chunks go out as they are read"""
        assert list(stream_grid_file(self._grid_out(b'ab', b'cd', b'e'))) == [b'ab', b'cd', b'e']

    def test_an_empty_file_yields_nothing(self) -> None:
        """A zero-length download is an empty body, not an error"""
        grid_out = self._grid_out()

        assert not list(stream_grid_file(grid_out))
        grid_out.close.assert_called_once()

    def test_the_file_is_closed_after_the_last_chunk(self) -> None:
        """A finished download releases the file"""
        grid_out = self._grid_out(b'x')

        list(stream_grid_file(grid_out))

        grid_out.close.assert_called_once()

    def test_the_file_is_closed_when_the_client_goes_away(self) -> None:
        """A download abandoned half-way closes the generator, and the file with it"""
        grid_out = self._grid_out(b'first', b'never-sent')
        stream = stream_grid_file(grid_out)

        assert next(stream) == b'first'
        stream.close()

        grid_out.close.assert_called_once()
