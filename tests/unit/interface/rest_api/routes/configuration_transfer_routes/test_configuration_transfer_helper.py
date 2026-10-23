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
Unit tests for configuration_transfer_routes.configuration_transfer_helper

Pure tests: no Mongo, no Flask app beyond a request context for abort. What is pinned here: every registered
component is built on its own manager type for the requesting user, in registry order; and the export
response is an indented JSON attachment named by the database version, a datetime written as `{'$date': millis}`
"""
import json
import re
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest

from cmdb.models.user_model import CmdbUser
from cmdb.framework.configuration_transfer import TRANSFER_COMPONENTS
from cmdb.manager.rights_manager import RightsManager
from cmdb.models.right_model.system_rights import SystemRight
from cmdb.utils import CONTENT_DISPOSITION_HEADER
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_helper import (
    build_configuration_export_response,
    build_transfer_components,
    read_uploaded_transfer_file,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_EXPORT_JSON_INDENT,
    CONFIGURATION_EXPORT_RIGHT,
    IMPORT_UPLOAD_FIELD,
    NO_IMPORT_FILE_MESSAGE,
    CONFIGURATION_EXPORT_MIMETYPE,
)
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_MODULE: str = 'cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_helper'
DB_VERSION: int = 20261014
STAMP: datetime = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
STAMP_MILLIS: int = int(STAMP.timestamp() * 1000)


def _user(public_id: int) -> MagicMock:
    """A user with the given public_id"""
    user: MagicMock = MagicMock(spec=CmdbUser)
    user.public_id = public_id

    return user


def test_build_transfer_components_builds_each_on_its_manager_in_order() -> None:
    """One component per registry entry, each on the manager of its own type for the requesting user"""
    user: MagicMock = _user(CmdbUser.ADMIN_PUBLIC_ID)
    managers: dict[Any, MagicMock] = {component.MANAGER_TYPE: MagicMock() for component in TRANSFER_COMPONENTS}

    with patch(f'{HELPER_MODULE}.ManagerProvider.get_manager',
               side_effect=lambda manager_type, request_user: managers[manager_type]) as get_manager:
        components = build_transfer_components(user)

    assert [type(component) for component in components] == list(TRANSFER_COMPONENTS)
    assert [component.manager for component in components] == [managers[c.MANAGER_TYPE] for c in TRANSFER_COMPONENTS]
    assert all(entry.args[1] is user for entry in get_manager.call_args_list)


def test_the_export_response_is_an_indented_json_attachment_named_by_the_version() -> None:
    """No chosen name -> JSON mimetype, `..._configuration_db-<version>.json` attachment, indented, $date datetimes"""
    response = build_configuration_export_response({'stamp': STAMP, 'n': 1}, DB_VERSION, None)
    body: str = response.get_data(as_text=True)

    assert response.mimetype == CONFIGURATION_EXPORT_MIMETYPE
    assert re.search(f'attachment; filename="[^"]*_configuration_db-{DB_VERSION}\\.json"',
                     response.headers[CONTENT_DISPOSITION_HEADER])
    assert json.loads(body) == {'stamp': {'$date': STAMP_MILLIS}, 'n': 1}
    assert body == json.dumps({'stamp': {'$date': STAMP_MILLIS}, 'n': 1}, indent=CONFIGURATION_EXPORT_JSON_INDENT)


def test_a_chosen_filename_names_the_attachment_cleaned() -> None:
    """The user's name, separators and leading dots removed, `.json` added; the exact spelling in filename*"""
    response = build_configuration_export_response({}, DB_VERSION, '../Kunden Übersicht')

    assert response.headers[CONTENT_DISPOSITION_HEADER] == (
        'attachment; filename="Kunden Ubersicht.json"; filename*=UTF-8\'\'Kunden%20%C3%9Cbersicht.json'
    )


@pytest.mark.parametrize('requested', ['', '  ', '.json'], ids=['empty', 'blank', 'extension-only'])
def test_a_chosen_filename_with_nothing_usable_falls_back_to_the_generated_one(requested: str) -> None:
    """The version-named default"""
    response = build_configuration_export_response({}, DB_VERSION, requested)

    assert re.search(f'filename="[^"]*_configuration_db-{DB_VERSION}\\.json"',
                     response.headers[CONTENT_DISPOSITION_HEADER])


def test_the_export_right_is_a_system_right_in_the_catalogue() -> None:
    """The route asks for a right the catalogue knows - one the admin group holds through base.*"""
    assert isinstance(RightsManager().get_right(CONFIGURATION_EXPORT_RIGHT), SystemRight)


def _upload(content: bytes | None) -> MagicMock:
    """A request carrying the content as the transfer file - or no file"""
    request: MagicMock = MagicMock()
    request.files = {} if content is None else {IMPORT_UPLOAD_FIELD: FileStorage(BytesIO(content), 'file.json')}

    return request


def test_read_uploaded_transfer_file_decodes_dates_back_to_datetimes() -> None:
    """JSON decoded with the codec's hook: the export's {'$date': millis} is a datetime again"""
    content: bytes = json.dumps({'stamp': {'$date': STAMP_MILLIS}, 'n': 1}).encode('utf-8')

    assert read_uploaded_transfer_file(_upload(content)) == {'stamp': STAMP, 'n': 1}


def test_read_uploaded_transfer_file_without_a_file_is_a_400() -> None:
    """No multipart field -> 400 naming the field"""
    with pytest.raises(BadRequest) as exc_info:
        read_uploaded_transfer_file(_upload(None))

    assert exc_info.value.description == NO_IMPORT_FILE_MESSAGE


@pytest.mark.parametrize('content', [b'{not json', b'\xff\xfe\x00'])
def test_read_uploaded_transfer_file_that_is_no_utf8_json_is_a_400(content: bytes) -> None:
    """Broken JSON and bytes that are no UTF-8 are both the caller's error"""
    with pytest.raises(BadRequest):
        read_uploaded_transfer_file(_upload(content))
