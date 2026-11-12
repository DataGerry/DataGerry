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
The import / export layout, read off the assembled URL map

What is exported sits under ``/export/<what>``, what is imported under ``/import/<what>``: object, type and
configuration on both sides, the ISMS importer under ``/import/isms``. The configuration reset - neither - stays at
``/configuration_transfer/reset``. Every route of the layout is pinned with its methods, and every URL it replaced
is pinned as gone: the backend keeps no aliases, so a moved route answers at its new path only.
"""
from http import HTTPStatus

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

GET: str = 'GET'
POST: str = 'POST'

#: Every import / export route, with the method it answers
LAYOUT: dict[str, str] = {
    '/export/object/': GET,
    '/export/object/extensions': GET,
    '/export/object/template/<int:type_id>': GET,
    '/export/type/': POST,
    '/export/type/<string:public_ids>': POST,
    '/export/configuration': POST,
    '/import/object/formats/': GET,
    '/import/object/formats/<string:importer_type>/config': GET,
    '/import/object/parser/default/<string:parser_type>/': GET,
    '/import/object/parse/': POST,
    '/import/object/': POST,
    '/import/type/create/': POST,
    '/import/type/update/': POST,
    '/import/isms/<string:target>': POST,
    '/import/configuration': POST,
    '/import/configuration/preview': POST,
    '/configuration_transfer/reset': POST,
}

#: The URLs the layout replaced (the method each answered), none of which answers any more
REPLACED: list[tuple[str, str]] = [
    (GET, '/exporter/'),
    (GET, '/exporter/extensions'),
    (GET, '/exporter/template/1'),
    (POST, '/configuration_transfer/export'),
    (GET, '/import/object/importer/'),
    (GET, '/import/object/importer/config/csv/'),
    (POST, '/isms/importer/threat'),
    (POST, '/configuration_transfer/import'),
    (POST, '/configuration_transfer/import/preview'),
]

#: The prefixes the layout lives under
IMPORT_EXPORT_PREFIXES: tuple[str, ...] = ('/export/', '/import/', '/configuration_transfer/')


def _rules(rest_api) -> dict[str, set[str]]:
    """Every rule of the assembled URL map, with its methods"""
    return {rule.rule: set(rule.methods) for rule in rest_api.application.url_map.iter_rules()}


@pytest.mark.parametrize('path, method', list(LAYOUT.items()))
def test_each_route_of_the_layout_is_mounted(rest_api, path: str, method: str) -> None:
    """At its path, with its method"""
    rules = _rules(rest_api)

    assert path in rules
    assert method in rules[path]


def test_nothing_else_is_mounted_under_the_layout(rest_api) -> None:
    """A new import or export route has to be added here - where the layout is decided"""
    mounted = {path for path in _rules(rest_api) if path.startswith(IMPORT_EXPORT_PREFIXES)}

    assert mounted == set(LAYOUT)


@pytest.mark.parametrize('method, path', REPLACED)
def test_a_replaced_url_answers_404(rest_api, method: str, path: str) -> None:
    """No alias: the old path is not a route any more"""
    assert rest_api.open(path, method=method).status_code == HTTPStatus.NOT_FOUND
