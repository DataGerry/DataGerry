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
Registers a real REST blueprint on a test app the way the app factory does

The blueprints are module-level singletons every app in the process registers. A blueprint of a licensed group gets
its licence gate - a ``before_request`` hook - from ``create_rest_api``, and Flask refuses a new hook on a blueprint
that is already registered. So a test that registers a licensed blueprint UNGATED on its own app leaves it ungatable:
every later ``create_rest_api`` in the process fails. ``register_as_the_factory_does`` gates first, with the feature
the factory uses (``licensed_blueprint_groups``), so the singleton stays in a state the factory accepts. A blueprint
outside every licensed group is registered as it is.
"""
from flask import Blueprint, Flask

from cmdb.interface.rest_api.init_rest_api import licensed_blueprint_groups
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import gate_blueprint
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = ['licensed_feature_of', 'register_as_the_factory_does']


def licensed_feature_of(blueprint: Blueprint) -> LicenseFeature | None:
    """
    The licence feature the app factory gates a blueprint behind

    Args:
        blueprint (Blueprint): The blueprint to look up

    Returns:
        LicenseFeature | None: Its group's feature, None when it belongs to no licensed group
    """
    for feature, mounts in licensed_blueprint_groups().items():
        if any(mounted is blueprint for mounted, _url_prefix in mounts):
            return feature

    return None


def register_as_the_factory_does(app: Flask, blueprint: Blueprint, url_prefix: str | None = None) -> None:
    """
    Registers a blueprint on a test app, gated first when the factory gates it

    Args:
        app (Flask): The test app
        blueprint (Blueprint): The real REST blueprint to register
        url_prefix (str | None): The prefix to mount it at, None for the blueprint's own. Defaults to None
    """
    feature: LicenseFeature | None = licensed_feature_of(blueprint)

    if feature is not None:
        gate_blueprint(blueprint, feature)

    app.register_blueprint(blueprint, url_prefix=url_prefix)
