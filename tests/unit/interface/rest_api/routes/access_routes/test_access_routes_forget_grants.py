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
Unit tests: the access routes' write helpers drop the request's access grants after the write

Inside a request, grants kept under ``GRANTS_CACHE_KEY`` are gone once ``create_response``, ``update_response`` or
``delete_response`` wrote - past MagicMock managers
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask

from cmdb.framework.access_engine import GRANTS_CACHE_KEY
from cmdb.models.access_model import CmdbFieldClass, HistoryKind
from cmdb.interface.rest_api.routes.access_routes.access_history_helper import ChangeContext
from cmdb.utils import request_cache
from cmdb.interface.rest_api.routes.access_routes import access_routes_helper
from cmdb.interface.rest_api.routes.access_routes.access_routes_helper import (
    create_response,
    delete_response,
    update_response,
)
# -------------------------------------------------------------------------------------------------------------------- #

KEPT_KEY: tuple[None, tuple[int, ...]] = (None, (21,))
STORED: dict[str, Any] = {'public_id': 7, 'name': 'compliance', 'label': 'Compliance', 'description': ''}


def _manager() -> MagicMock:
    """A field class manager answering the stored document"""
    manager = MagicMock()
    manager.insert_item.return_value = STORED['public_id']
    manager.exceptions = {'insert': KeyError, 'update': KeyError}

    return manager


@pytest.mark.parametrize('write', ['create', 'update', 'delete'])
def test_a_write_drops_the_kept_grants(write: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Kept before, gone after"""
    monkeypatch.setattr(access_routes_helper, 'update_item_from_payload', lambda *_args: dict(STORED))
    # No history read or written - only the dropped grants are under test
    monkeypatch.setattr(access_routes_helper, 'concerned_groups', lambda *_args: set())
    monkeypatch.setattr(access_routes_helper, 'record_change', lambda *_args: None)
    change: ChangeContext = ChangeContext(MagicMock(), HistoryKind.FIELD_CLASS)

    with Flask(__name__).test_request_context('/'):
        request_cache(GRANTS_CACHE_KEY)[KEPT_KEY] = object()

        if write == 'create':
            create_response(_manager(), CmdbFieldClass, {k: v for k, v in STORED.items() if k != 'public_id'}, 'x',
                            change)
        elif write == 'update':
            update_response(_manager(), CmdbFieldClass, STORED['public_id'], dict(STORED), 'x', change, dict(STORED))
        else:
            delete_response(_manager(), dict(STORED), change)

        assert not request_cache(GRANTS_CACHE_KEY)
