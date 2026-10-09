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
Census of the running app's URL map: every route under a licensed prefix is gated behind its feature

The licence-after-authentication census proves that every route on a GATED blueprint authenticates. This one
proves the converse the URL map needs: every route mounted under a licensed prefix sits on a blueprint gated
behind that prefix's feature, so a blueprint added to a licensed group cannot be served ungated. OpenCelium's
own licence routes are the one named exception under a licensed prefix. Read from the session app the REST
test client talks to - the real registration, not a recording of it
"""
from flask import Flask

from cmdb.interface.rest_api.routes.cmdb_license.license_guard import GATED_FEATURE_ATTR
from cmdb.interface.rest_api.routes.open_celium_routes import oc_licenses_blueprint
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

#: Where each licensed group is mounted, and the feature its routes require on premise
LICENSED_PREFIXES: dict[str, LicenseFeature] = {
    '/isms/': LicenseFeature.ISMS,
    '/object_groups': LicenseFeature.ISMS,
    '/persons': LicenseFeature.ISMS,
    '/person_groups': LicenseFeature.ISMS,
    '/ipam/': LicenseFeature.IPAM,
    '/racks': LicenseFeature.IPAM,
    '/ports': LicenseFeature.IPAM,
    '/port_connections': LicenseFeature.IPAM,
    '/open_celium': LicenseFeature.AUTOMATIONS,
}

#: Blueprints mounted under a licensed prefix but deliberately not gated as a whole
UNGATED_UNDER_A_LICENSED_PREFIX: frozenset[str] = frozenset({oc_licenses_blueprint.name})


def _gated_blueprints(app: Flask) -> dict[str, LicenseFeature]:
    """The app's gated blueprint names, with the feature each one's gate records."""
    return {
        name: getattr(hook, GATED_FEATURE_ATTR)
        for name, hooks in app.before_request_funcs.items() if name
        for hook in hooks if hasattr(hook, GATED_FEATURE_ATTR)
    }


def _licensed_feature(path: str) -> LicenseFeature | None:
    """The feature a URL path's prefix requires, or None outside every licensed prefix."""
    return next((feature for prefix, feature in LICENSED_PREFIXES.items() if path.startswith(prefix)), None)


def _blueprint_of(endpoint: str) -> str:
    """The blueprint part of an endpoint name ('' for an app-level endpoint)."""
    return endpoint.rpartition('.')[0]


def test_every_route_under_a_licensed_prefix_is_gated_behind_its_feature(rest_api) -> None:
    """A route under /isms, /ipam, /ports, ... answers only with that feature licensed"""
    app = rest_api.application
    gated = _gated_blueprints(app)

    wrong: list[str] = [
        f'{rule.rule} ({rule.endpoint}) -> {gated.get(_blueprint_of(rule.endpoint))}'
        for rule in app.url_map.iter_rules()
        if (feature := _licensed_feature(rule.rule)) is not None
        and _blueprint_of(rule.endpoint) not in UNGATED_UNDER_A_LICENSED_PREFIX
        and gated.get(_blueprint_of(rule.endpoint)) != feature
    ]

    assert not wrong


def test_every_gated_route_lives_under_a_prefix_of_its_feature(rest_api) -> None:
    """The converse: a gate never reaches a route outside its feature's prefixes"""
    app = rest_api.application
    gated = _gated_blueprints(app)

    stray: list[str] = [
        rule.rule for rule in app.url_map.iter_rules()
        if (feature := gated.get(_blueprint_of(rule.endpoint))) is not None
        and _licensed_feature(rule.rule) != feature
    ]

    assert not stray


def test_every_licensed_prefix_serves_routes(rest_api) -> None:
    """The census is not vacuous: every licensed prefix has routes in the URL map"""
    paths: list[str] = [rule.rule for rule in rest_api.application.url_map.iter_rules()]

    assert all(any(path.startswith(prefix) for path in paths) for prefix in LICENSED_PREFIXES)


def test_the_open_celium_licence_routes_are_the_named_exception(rest_api) -> None:
    """OpenCelium's own licence routes are under /open_celium and stay ungated"""
    app = rest_api.application
    licence_paths: list[str] = [
        rule.rule for rule in app.url_map.iter_rules() if _blueprint_of(rule.endpoint) == oc_licenses_blueprint.name
    ]

    assert licence_paths
    assert all(path.startswith('/open_celium') for path in licence_paths)
    assert oc_licenses_blueprint.name not in _gated_blueprints(app)
