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
Unit tests for cmdb.framework.media_library.media_file_schema

`filename_problem` (the naming rule) and the two Cerberus schemas: every metadata key optional and of its
declared type, an id never a boolean, no undeclared metadata key, and the update body's three required keys
with the rest tolerated
"""
from typing import Any

import pytest
from cerberus import Validator  # type: ignore

from cmdb.framework.media_library import (
    MEDIA_FILE_METADATA_SCHEMA,
    MEDIA_FILE_UPDATE_SCHEMA,
    MediaFileMetadataKey,
    filename_problem,
)
from cmdb.framework.media_library.media_library_constants import (
    BOOLEAN_IS_NO_ID_MSG,
    FILENAME_BLANK_MSG,
    FILENAME_NOT_A_STRING_MSG,
    FILENAME_SEPARATOR_MSG,
    FILENAME_TOO_LONG_MSG,
    MEDIA_FILE_NAME_MAX_LENGTH,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 31


def _metadata_errors(metadata: dict[str, Any]) -> dict[str, Any]:
    """The errors MEDIA_FILE_METADATA_SCHEMA reports for a metadata sub-document."""
    validator = Validator(MEDIA_FILE_METADATA_SCHEMA)
    validator.validate(metadata)

    return validator.errors


def _body_errors(body: dict[str, Any]) -> dict[str, Any]:
    """The errors MEDIA_FILE_UPDATE_SCHEMA reports for an update body (extra keys tolerated)."""
    validator = Validator(MEDIA_FILE_UPDATE_SCHEMA, allow_unknown=True)
    validator.validate(body)

    return validator.errors


class TestFilenameProblem:
    """filename_problem names what makes a name unusable."""

    @pytest.mark.parametrize(('name', 'problem'), [
        (7, FILENAME_NOT_A_STRING_MSG), (None, FILENAME_NOT_A_STRING_MSG), ('', FILENAME_BLANK_MSG),
        (' \t ', FILENAME_BLANK_MSG), ('a/b', FILENAME_SEPARATOR_MSG),
        ('x' * (MEDIA_FILE_NAME_MAX_LENGTH + 1), FILENAME_TOO_LONG_MSG),
    ])
    def test_an_unusable_name_is_named(self, name: Any, problem: str) -> None:
        """Each rule answers its own reason."""
        assert filename_problem(name) == problem

    @pytest.mark.parametrize('name', ['a', 'x' * MEDIA_FILE_NAME_MAX_LENGTH, 'copy_(1)_a b.c', 'März\\Plan.pdf'])
    def test_a_usable_name_has_no_problem(self, name: str) -> None:
        """Up to the limit, any character but the separator."""
        assert filename_problem(name) is None


class TestMetadataSchema:
    """MEDIA_FILE_METADATA_SCHEMA: optional keys, declared types, nothing undeclared."""

    def test_every_key_is_optional(self) -> None:
        """An empty sub-document is valid - the builder fills it in."""
        assert not _metadata_errors({})

    def test_the_schema_declares_exactly_the_metadata_keys(self) -> None:
        """The schema and the allowlist enum can not drift apart."""
        assert set(MEDIA_FILE_METADATA_SCHEMA) == {key.value for key in MediaFileMetadataKey}

    @pytest.mark.parametrize('key', ['reference', 'parent', 'author_id'])
    def test_an_id_is_never_a_boolean(self, key: str) -> None:
        """JSON true would otherwise pass as the id 1."""
        assert _metadata_errors({key: True}) == {key: [BOOLEAN_IS_NO_ID_MSG]}

    def test_a_reference_list_holds_ids_only(self) -> None:
        """A boolean inside the list is refused as well."""
        assert _metadata_errors({'reference': [1, False]}) == {'reference': [BOOLEAN_IS_NO_ID_MSG]}

    @pytest.mark.parametrize('metadata', [
        {'reference': 1}, {'reference': [1, 2]}, {'reference': None}, {'parent': None}, {'folder': True},
        {'permission': [1, 'x']}, {'reference_type': 'object', 'mime_type': 'text/plain', 'author_id': 3},
    ])
    def test_declared_values_pass(self, metadata: dict[str, Any]) -> None:
        """What the upload and the update legitimately carry."""
        assert not _metadata_errors(metadata)

    def test_an_undeclared_key_is_refused(self) -> None:
        """Nothing beyond the seven keys."""
        assert 'public_id' in _metadata_errors({'public_id': 1})


class TestUpdateSchema:
    """MEDIA_FILE_UPDATE_SCHEMA: the three keys an update is made of."""

    def test_a_whole_file_element_passes(self) -> None:
        """Extra keys of the frontend's FileElement are tolerated."""
        body = {'public_id': PUBLIC_ID, 'filename': 'a', 'metadata': {}, 'size': 1, 'inProcess': False}

        assert not _body_errors(body)

    @pytest.mark.parametrize('missing', ['public_id', 'filename', 'metadata'])
    def test_each_key_is_required(self, missing: str) -> None:
        """A partial body is refused, naming what is missing."""
        body = {'public_id': PUBLIC_ID, 'filename': 'a', 'metadata': {}}
        del body[missing]

        assert missing in _body_errors(body)

    def test_the_metadata_runs_the_metadata_schema_with_no_unknown_key(self) -> None:
        """The tolerance for extra keys stops at the metadata."""
        errors = _body_errors({'public_id': PUBLIC_ID, 'filename': 'a', 'metadata': {'evil': 1, 'parent': 'x'}})

        assert set(errors['metadata'][0]) == {'evil', 'parent'}

    def test_the_filename_runs_the_naming_rule(self) -> None:
        """The update and the upload share the rule."""
        assert _body_errors({'public_id': PUBLIC_ID, 'filename': 'a/b', 'metadata': {}}) == {
            'filename': [FILENAME_SEPARATOR_MSG],
        }
