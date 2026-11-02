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
Unit tests for the request-context tripwire of the test session (``tests.fixtures.fixture_rest_api``)

After every test, a request context still pushed fails that test: request-scoped state would otherwise leak into
every later test. These pin the check itself - nothing left is no verdict, a pushed request is named with its path
"""
from flask import Flask

from tests.fixtures.fixture_rest_api import REQUEST_CONTEXT_LEFT_MESSAGE, leftover_request_context_message
# -------------------------------------------------------------------------------------------------------------------- #

TEST_NAME: str = 'tests/unit/test_example.py::test_leaks'
LEAKED_PATH: str = '/auth/login'


def test_no_request_context_is_no_verdict() -> None:
    """The normal case after a test"""
    assert leftover_request_context_message(TEST_NAME) is None


def test_a_pushed_request_names_the_test_and_its_path() -> None:
    """The report says which test leaked which request"""
    with Flask(__name__).test_request_context(LEAKED_PATH):
        message = leftover_request_context_message(TEST_NAME)

    assert message == REQUEST_CONTEXT_LEFT_MESSAGE.format(test=TEST_NAME, path=LEAKED_PATH)


def test_a_popped_request_is_no_verdict() -> None:
    """A test that pushes and pops its own request is fine"""
    with Flask(__name__).test_request_context(LEAKED_PATH):
        pass

    assert leftover_request_context_message(TEST_NAME) is None
