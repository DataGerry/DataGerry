# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for cmdb.utils.request_scoped_cache.request_cache - one dict per key and request, none outside a request
"""
from flask import Flask

from cmdb.utils import request_cache
# -------------------------------------------------------------------------------------------------------------------- #

REQUEST_CACHE_KEY: str = 'dg_test_cache'
OTHER_REQUEST_CACHE_KEY: str = 'dg_test_other_cache'
CACHED_KEY: str = 'answer'
CACHED_VALUE: int = 1


class TestRequestCache:
    """The token parse, the request groups, the webhook reads and the access grants keep their answers in it"""

    def test_outside_a_request_there_is_no_cache(self) -> None:
        """A CLI path or a direct call caches nothing"""
        assert request_cache(REQUEST_CACHE_KEY) is None

    def test_the_same_key_answers_the_same_dict_within_a_request(self) -> None:
        """Created on first use, then kept; another key has its own"""
        with Flask(__name__).test_request_context('/'):
            first = request_cache(REQUEST_CACHE_KEY)
            first[CACHED_KEY] = CACHED_VALUE

            assert request_cache(REQUEST_CACHE_KEY) is first
            assert request_cache(OTHER_REQUEST_CACHE_KEY) == {}

    def test_a_new_request_starts_empty(self) -> None:
        """Nothing outlives its request"""
        app = Flask(__name__)

        with app.test_request_context('/'):
            request_cache(REQUEST_CACHE_KEY)[CACHED_KEY] = CACHED_VALUE

        with app.test_request_context('/'):
            assert request_cache(REQUEST_CACHE_KEY) == {}
