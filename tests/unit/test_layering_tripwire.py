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
Tripwire: nothing below the transport layer imports ``cmdb.interface``

``cmdb/interface`` is the transport - the Flask apps, the REST routes, the response envelopes. Everything else (the
managers, the models, the database, the framework, security, utils, errors, process management) sits below it, and a
module there that imports from the routes or the responses ties the lower layer to the HTTP surface: it cannot be
imported without the Flask app's modules, and a change to a route can break a manager. A helper both layers need
lives in the framework; a page a manager returns is an ``IterationResult``. The scan holds the count at zero.

Only RUNTIME imports count. An import under ``if TYPE_CHECKING:`` feeds annotations alone and never runs, so a
lower layer may still name a transport type in a signature. Read with ``ast``, so every module is covered whether
or not a test imports it
"""
import ast
from pathlib import Path

import pytest
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'

TRANSPORT_PACKAGE: str = 'cmdb.interface'
TYPE_CHECKING_NAME: str = 'TYPE_CHECKING'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 500


def _is_type_checking_block(node: ast.AST) -> bool:
    """`if TYPE_CHECKING:` or `if typing.TYPE_CHECKING:`."""
    if not isinstance(node, ast.If):
        return False

    test: ast.expr = node.test

    return (isinstance(test, ast.Name) and test.id == TYPE_CHECKING_NAME) \
        or (isinstance(test, ast.Attribute) and test.attr == TYPE_CHECKING_NAME)


def _imported_modules(node: ast.AST) -> list[str]:
    """The module names an import statement loads."""
    if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        return [node.module]

    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]

    return []


def runtime_transport_imports(source: str) -> list[int]:
    """
    The line numbers of every runtime import of the transport package in one module

    Args:
        source (str): The module's source

    Returns:
        list[int]: One line number per offending import, in source order
    """
    tree: ast.Module = ast.parse(source)
    annotation_only: set[int] = {
        id(inner) for node in ast.walk(tree) if _is_type_checking_block(node) for inner in ast.walk(node)
    }

    return sorted(
        node.lineno for node in ast.walk(tree)
        if id(node) not in annotation_only
        and any(name == TRANSPORT_PACKAGE or name.startswith(f'{TRANSPORT_PACKAGE}.')
                for name in _imported_modules(node))
    )


def _lower_layer_modules() -> list[Path]:
    """Every module of ``cmdb/`` outside ``cmdb/interface``."""
    transport_root: Path = CMDB_ROOT / 'interface'

    return sorted(path for path in CMDB_ROOT.rglob('*.py') if transport_root not in path.parents)


class TestTheScan:
    """The whole tree below the transport layer."""

    def test_it_covers_the_tree(self) -> None:
        """A moved package must not make the scan pass vacuously"""
        assert len(_lower_layer_modules()) >= MIN_SCANNED_MODULES

    def test_no_lower_layer_module_imports_the_transport(self) -> None:
        """Each offender listed with its line, so the failure names what to move"""
        offenders: list[str] = [
            f'{path.relative_to(CMDB_ROOT.parent)}:{line}'
            for path in _lower_layer_modules()
            for line in runtime_transport_imports(path.read_text(encoding='utf-8'))
        ]

        assert not offenders, offenders


class TestTheDetector:
    """What counts as an import of the transport, and what does not."""

    @pytest.mark.parametrize('source', [
        'from cmdb.interface.rest_api.responses import DefaultResponse\n',
        'import cmdb.interface.route_utils\n',
        'from cmdb.interface import blueprints\n',
        'def build():\n    from cmdb.interface.rest_api.routes import routes_helper\n',
    ], ids=['from-import', 'plain-import', 'package-import', 'function-local'])
    def test_a_runtime_import_is_caught(self, source: str) -> None:
        """Wherever it sits - module level or inside a function, it runs"""
        assert runtime_transport_imports(source) != []

    @pytest.mark.parametrize('source', [
        'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from cmdb.interface.blueprints import APIBlueprint\n',
        'import typing\nif typing.TYPE_CHECKING:\n    import cmdb.interface.route_utils\n',
        'from cmdb.interfaces_elsewhere import thing\n',
        'from .interface import thing\n',
    ], ids=['type-checking', 'typing-type-checking', 'look-alike-name', 'relative'])
    def test_an_annotation_only_or_unrelated_import_is_not(self, source: str) -> None:
        """Annotation-only imports never run; a name that merely starts alike is another package"""
        assert runtime_transport_imports(source) == []

    def test_the_line_of_each_offender_is_reported(self) -> None:
        """Two offenders, two lines"""
        source: str = 'import os\nimport cmdb.interface.route_utils\nx = 1\nfrom cmdb.interface import blueprints\n'

        assert runtime_transport_imports(source) == [2, 4]
