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
Integration tests: ``handle_oc_errors`` against what the real ``requests`` library raises

No mock stands in for ``requests``: a malformed URL is refused by the library itself before any connection is opened,
so these run without a network. They pin that the errors the OpenCelium connector re-raises are the ones the
decorator's arms name - a URL stored without its scheme, or one that is no URL at all, answers the request-failure
message, not the generic one
"""
from http import HTTPStatus

import pytest
import requests
from werkzeug.exceptions import HTTPException

from cmdb.interface import route_utils
from cmdb.open_celium.oc_constants import OC_REQUEST_TIMEOUT
from tests.utils.cmdb_app_stub import stub_cmdb_app
# -------------------------------------------------------------------------------------------------------------------- #

GET_METHOD: str = 'GET'
CONTEXT: str = 'reading the OpenCelium invokers'


@pytest.mark.parametrize('url', ['oc.example.com/api/invoker/all', 'http://'], ids=['no-scheme', 'no-host'])
def test_a_malformed_opencelium_url_answers_the_request_failure(url: str) -> None:
    """What `requests` raises for the stored URL reaches the decorator's request arm"""
    @route_utils.handle_oc_errors(CONTEXT)
    def _route() -> None:
        requests.request(GET_METHOD, url, timeout=OC_REQUEST_TIMEOUT)

    with stub_cmdb_app().test_request_context():
        with pytest.raises(HTTPException) as exc_info:
            _route()

    assert (exc_info.value.code, exc_info.value.description) == (
        HTTPStatus.INTERNAL_SERVER_ERROR, route_utils.OC_REQUEST_FAILED_MESSAGE)
