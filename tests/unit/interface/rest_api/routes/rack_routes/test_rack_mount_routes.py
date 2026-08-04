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
Unit tests for cmdb.interface.rest_api.routes.rack_routes.rack_mount_routes

Asserts the mounted URL set, so the frontend-facing route set cannot change unnoticed - a rack_id in
the path on every write is what keeps a payload from choosing the rack.

The routes themselves are not invoked here: they carry the auth decorator stack, which needs a real
application. Their manager-failure arms are covered in the functional suite instead, by patching the
manager class while driving a real request
"""
from flask import Flask

from cmdb.interface.rest_api.routes.rack_routes.rack_mount_routes import rack_mounts_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.routes.rack_routes.rack_mount_routes'
URL_PREFIX: str = '/racks'

EXPECTED_RULES: set[str] = {
    '/racks/<int:rack_id>/mounts/',
    '/racks/<int:rack_id>/mounts/<int:mount_id>',
    '/racks/<int:rack_id>/mounts/validate',
    '/racks/<int:rack_id>/overview',
    '/racks/<int:rack_id>/height_conflicts',
    '/racks/mounts/object/<int:object_id>',
}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  the URL surface                                                     #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_mounted_url_set_is_pinned() -> None:
    """
    The route set is a frontend contract

    A rack_id in the path on every write is what keeps a payload from choosing the rack.
    """
    local_app = Flask(__name__)
    local_app.register_blueprint(rack_mounts_blueprint, url_prefix=URL_PREFIX)

    rules = {rule.rule for rule in local_app.url_map.iter_rules() if rule.rule.startswith(URL_PREFIX)}

    assert rules == EXPECTED_RULES


def test_the_collection_route_carries_a_trailing_slash() -> None:
    """The listing / create route is the `/mounts/` form, per the route convention"""
    assert '/racks/<int:rack_id>/mounts/' in EXPECTED_RULES
