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
Unit tests for cmdb.interface.rest_api.routes.exporter_routes.exporter_type_routes

Guards the blueprint contract established when the type-export routes were promoted from a
RootBlueprint carrying its own url_prefix to an APIBlueprint mounted by init_rest_api: the module must
stay importable in a bare interpreter, and mounting it at '/export/type' must still yield exactly the
two URLs the frontend posts to.
"""
import subprocess
import sys

from flask import Flask

from cmdb.interface.rest_api.routes.exporter_routes.exporter_type_routes import exporter_type_blueprint
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.interface.rest_api.routes.exporter_routes.exporter_type_routes'
URL_PREFIX: str = '/export/type'

EXPECTED_RULES: set[str] = {'/export/type/', '/export/type/<string:public_ids>'}


def _mounted_app() -> Flask:
    """Builds a bare Flask app with the export blueprint mounted at its production prefix."""
    app = Flask(__name__)
    app.register_blueprint(exporter_type_blueprint, url_prefix=URL_PREFIX)

    return app


class TestModuleIsSelfContained:
    """The routes module carries no import-time application context dependency."""

    def test_imports_in_a_bare_interpreter(self) -> None:
        """A fresh interpreter can import the module with no Flask application context pushed."""
        result = subprocess.run(
            [sys.executable, '-c', f'import {MODULE_PATH}'],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr


class TestBlueprintUrls:
    """Mounting the blueprint reproduces the frontend-facing URLs exactly."""

    def test_registers_the_expected_rules(self) -> None:
        """The blueprint exposes only the export-all and export-by-ids URLs."""
        rules = {
            str(rule) for rule in _mounted_app().url_map.iter_rules() if str(rule).startswith(URL_PREFIX)
        }

        assert rules == EXPECTED_RULES

    def test_rules_accept_post_only(self) -> None:
        """Both export URLs are POST-only."""
        for rule in _mounted_app().url_map.iter_rules():
            if str(rule) in EXPECTED_RULES:
                assert rule.methods & {'GET', 'PUT', 'DELETE'} == set()
                assert 'POST' in rule.methods
