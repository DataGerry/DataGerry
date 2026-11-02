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
Unit tests for cmdb.utils.json_upload - an uploaded JSON text decoded with its failures and depth bounded

Pure: no Mongo, no Flask. Pinned: how deep a value is measured (and that measuring never recurses), every decoding
failure of both extended-JSON hooks the uploads use answered as `JsonUploadDecodeError` carrying the decoder's own
error, a text the decoder cannot descend and one past the limit answered as `JsonUploadTooDeepError`, and the limit
itself as a boundary
"""
import json
import re
from typing import Any

import pytest
from bson import json_util
from bson.errors import InvalidId

from cmdb.database.json_codec import object_hook
from cmdb.errors.utils import JsonUploadDecodeError, JsonUploadTooDeepError
from cmdb.utils import MAX_JSON_UPLOAD_DEPTH, load_json_upload, nesting_depth
from cmdb.utils.json_upload import JSON_UPLOAD_DECODE_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

# Far past what any decoder or walker could recurse through
EXTREME_DEPTH: int = 200_000
SMALL_LIMIT: int = 3
# MongoDB's documented nesting limit for a document - what the default bound is pinned to
MONGODB_DOCUMENTED_NESTING_LIMIT: int = 100


def _nested(depth: int) -> str:
    """A JSON text of `depth` nested lists"""
    return '[' * depth + ']' * depth


class TestNestingDepth:
    """How deeply a decoded value is nested"""

    @pytest.mark.parametrize('value, depth', [
        ('x', 0), (5, 0), (None, 0), ([], 1), ({}, 1), ([1, 2], 1), ({'a': [1]}, 2), ([{'a': {'b': []}}], 4),
        ({'flat': 1, 'deep': [[[]]]}, 4),
    ], ids=['string', 'number', 'null', 'empty-list', 'empty-dict', 'flat-list', 'dict-of-list', 'mixed',
            'deepest-branch-counts'])
    def test_the_deepest_branch_is_the_depth(self, value: Any, depth: int) -> None:
        """A scalar 0, every container one level"""
        assert nesting_depth(value, MAX_JSON_UPLOAD_DEPTH) == depth

    def test_exactly_the_limit_is_measured(self) -> None:
        """The limit itself is not past it"""
        assert nesting_depth(json.loads(_nested(SMALL_LIMIT)), SMALL_LIMIT) == SMALL_LIMIT

    def test_past_the_limit_answers_one_more(self) -> None:
        """Measured no further than one past the limit"""
        assert nesting_depth(json.loads(_nested(SMALL_LIMIT + 5)), SMALL_LIMIT) == SMALL_LIMIT + 1

    def test_measuring_never_recurses(self) -> None:
        """A value deeper than Python's recursion limit is measured without a RecursionError"""
        value: Any = []
        for _ in range(5_000):
            value = [value]

        assert nesting_depth(value, MAX_JSON_UPLOAD_DEPTH) == MAX_JSON_UPLOAD_DEPTH + 1


class TestLoadJsonUpload:
    """Decoding an upload"""

    def test_decodes_with_the_hook(self) -> None:
        """The hook's values come back - bytes are read as UTF-8"""
        assert load_json_upload(b'{"id": {"$oid": "5f1b7e2a9c1d4e3f2a1b0c9d"}}',
                                object_hook=object_hook)['id'].__class__.__name__ == 'ObjectId'

    def test_without_a_hook_plain_json(self) -> None:
        """No hook, no conversion"""
        assert load_json_upload('{"a": [1, 2]}') == {'a': [1, 2]}

    @pytest.mark.parametrize('text', ['{not json', b'\xff\xfe\x00'], ids=['broken-json', 'no-utf8'])
    def test_text_that_is_no_utf8_json(self, text: str | bytes) -> None:
        """The decoder's error is carried"""
        with pytest.raises(JsonUploadDecodeError) as raised:
            load_json_upload(text)

        assert isinstance(raised.value.args[0], ValueError)
        assert raised.value.__cause__ is raised.value.args[0]

    @pytest.mark.parametrize('hook, text, cause', [
        (object_hook, '[{"$oid": "zz"}]', InvalidId),
        (object_hook, '[{"$uuid": "zz"}]', ValueError),
        (object_hook, '[{"$regex": "("}]', re.error),
        (object_hook, '[{"$regex": 5}]', ValueError),
        (json_util.object_hook, '[{"$oid": "zz"}]', InvalidId),
        (json_util.object_hook, '[{"$date": "zz"}]', ValueError),
        (json_util.object_hook, '[{"$numberDecimal": "x"}]', ArithmeticError),
    ], ids=['codec-oid', 'codec-uuid', 'codec-regex', 'codec-regex-type', 'util-oid', 'util-date', 'util-decimal'])
    def test_an_unreadable_extended_json_value(self, hook: Any, text: str, cause: type[Exception]) -> None:
        """Every hook failure is one decode error, carrying the hook's own"""
        with pytest.raises(JsonUploadDecodeError) as raised:
            load_json_upload(text, object_hook=hook)

        assert isinstance(raised.value.args[0], cause)

    def test_every_decode_error_kind_is_listed(self) -> None:
        """The kinds the hooks raise, named once"""
        assert set(JSON_UPLOAD_DECODE_ERRORS) == {ValueError, TypeError, ArithmeticError, InvalidId, re.error}

    def test_a_text_the_decoder_cannot_descend(self) -> None:
        """The decoder's RecursionError is a nesting refusal, not a decode error"""
        with pytest.raises(JsonUploadTooDeepError) as raised:
            load_json_upload(_nested(EXTREME_DEPTH))

        assert isinstance(raised.value.__cause__, RecursionError)

    def test_the_default_limit_is_accepted(self) -> None:
        """MAX_JSON_UPLOAD_DEPTH levels pass"""
        assert nesting_depth(load_json_upload(_nested(MAX_JSON_UPLOAD_DEPTH)), MAX_JSON_UPLOAD_DEPTH + 1) \
            == MAX_JSON_UPLOAD_DEPTH

    def test_one_level_past_the_default_limit_is_refused(self) -> None:
        """Before anything walks it recursively"""
        with pytest.raises(JsonUploadTooDeepError):
            load_json_upload(_nested(MAX_JSON_UPLOAD_DEPTH + 1))

    def test_a_limit_of_its_own(self) -> None:
        """A caller may bound tighter"""
        assert load_json_upload(_nested(SMALL_LIMIT), max_depth=SMALL_LIMIT)

        with pytest.raises(JsonUploadTooDeepError):
            load_json_upload(_nested(SMALL_LIMIT + 1), max_depth=SMALL_LIMIT)

    def test_the_default_limit_is_mongodbs_documented_nesting_limit(self) -> None:
        """100 levels - a transfer file is 9"""
        assert MAX_JSON_UPLOAD_DEPTH == MONGODB_DOCUMENTED_NESTING_LIMIT
