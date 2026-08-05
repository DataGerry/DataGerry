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
Functional tests for the missing / empty Authorization header path

Pins the contract that any request reaching an ``@insert_request_user``-protected route
without an Authorization header (or with an empty value) is rejected with HTTP 401 and
the explicit "No Authorization header provided!" message, instead of falling through to
the previous generic catch-all that logged a KeyError traceback at DEBUG level. The
specific message is the marker that the early-exit branch in ``route_utils.get_request_user``
actually fired
"""
from http import HTTPStatus
# -------------------------------------------------------------------------------------------------------------------- #

PROTECTED_ROUTE: str = '/settings/system/'
NO_AUTH_MESSAGE_FRAGMENT: str = 'No Authorization header provided'


class TestMissingAuthHeaderReturnsCleanly:
    """``@insert_request_user`` aborts with 401 + clear message when the Authorization header is absent."""

    def test_returns_401_with_explicit_message(self, rest_api) -> None:
        """A request with no Authorization header returns 401 and the dedicated 'No Authorization' message."""
        response = rest_api.get(PROTECTED_ROUTE, unauthorized=True)

        assert response.status_code == HTTPStatus.UNAUTHORIZED
        body_text = response.get_data(as_text=True)
        assert NO_AUTH_MESSAGE_FRAGMENT in body_text
