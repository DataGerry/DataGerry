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
Tripwire: no test registers a licensed REST blueprint on its own app except through the factory's order

A blueprint of a licensed group (``licensed_blueprint_groups``) is a module-level singleton that ``create_rest_api``
gates - a ``before_request`` hook - before registering it, and Flask refuses a new hook once a blueprint is
registered. One test that registered such a blueprint ungated made every later ``create_rest_api`` in the process
fail, but only when ``tests/unit`` ran on its own, so the full suite never showed it. A test registers a licensed
blueprint through ``tests.utils.blueprint_registration.register_as_the_factory_does``, which gates first; a direct
``register_blueprint(<licensed blueprint>)`` anywhere in ``tests/`` fails here.

Read with ``ast``: a call's first argument is matched by the name the blueprint is bound to in its routes module.
"""
import ast
import sys
from pathlib import Path

from flask import Blueprint

from cmdb.interface.rest_api.init_rest_api import licensed_blueprint_groups
# -------------------------------------------------------------------------------------------------------------------- #

TESTS_ROOT: Path = Path(__file__).resolve().parents[1]
HELPER_MODULE: Path = TESTS_ROOT / 'utils' / 'blueprint_registration.py'
REGISTER_METHOD: str = 'register_blueprint'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000


def licensed_blueprint_names() -> frozenset[str]:
    """
    Every name a licensed blueprint is bound to in the module that defines it

    Returns:
        frozenset[str]: The variable names of the licensed blueprints (``ipam_tree_blueprint``, ...)
    """
    names: set[str] = set()

    for mounts in licensed_blueprint_groups().values():
        for blueprint, _url_prefix in mounts:
            module_vars: dict[str, object] = vars(sys.modules[blueprint.import_name])
            names.update(name for name, value in module_vars.items() if value is blueprint)

    return frozenset(names)


def _argument_name(node: ast.expr) -> str | None:
    """The bare name a call argument refers to - ``x`` for ``x`` and ``pkg.x`` - or None for anything else"""
    if isinstance(node, ast.Name):
        return node.id

    if isinstance(node, ast.Attribute):
        return node.attr

    return None


def direct_registrations(source: str, licensed_names: frozenset[str]) -> list[int]:
    """
    The lines of a module that register a licensed blueprint directly

    Args:
        source (str): A module's source
        licensed_names (frozenset[str]): The names the licensed blueprints are bound to

    Returns:
        list[int]: The line of every ``<app>.register_blueprint(<licensed blueprint>, ...)`` call
    """
    return sorted(
        node.lineno for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == REGISTER_METHOD
        and node.args
        and _argument_name(node.args[0]) in licensed_names
    )


def test_the_names_cover_every_licensed_blueprint() -> None:
    """Each licensed blueprint is found under at least one name, so the scan cannot miss one silently"""
    groups = licensed_blueprint_groups()
    blueprints: list[Blueprint] = [blueprint for mounts in groups.values() for blueprint, _prefix in mounts]

    unnamed: list[str] = [
        blueprint.name for blueprint in blueprints
        if not any(value is blueprint for value in vars(sys.modules[blueprint.import_name]).values())
    ]

    assert not unnamed
    assert 'ipam_tree_blueprint' in licensed_blueprint_names()


def test_the_scan_finds_a_direct_registration() -> None:
    """A bare and a package-qualified registration of a licensed blueprint; other blueprints and calls pass"""
    source = '''
app.register_blueprint(ipam_tree_blueprint, url_prefix='/ipam/tree')
app.register_blueprint(routes.ipam_tree_blueprint)
app.register_blueprint(setup_blueprint, url_prefix='/setup')
register_as_the_factory_does(app, ipam_tree_blueprint)
app.register_blueprint(url_prefix='/x')
'''
    assert direct_registrations(source, frozenset({'ipam_tree_blueprint'})) == [2, 3]


def test_no_test_registers_a_licensed_blueprint_directly() -> None:
    """Every licensed blueprint a test mounts goes through ``register_as_the_factory_does``"""
    licensed_names: frozenset[str] = licensed_blueprint_names()
    modules: list[Path] = [path for path in sorted(TESTS_ROOT.rglob('*.py')) if path != HELPER_MODULE]
    offenders: list[str] = [
        f'{path.relative_to(TESTS_ROOT)}:{line}'
        for path in modules
        for line in direct_registrations(path.read_text(encoding='utf-8'), licensed_names)
    ]

    assert len(modules) >= MIN_SCANNED_MODULES
    assert not offenders, f'register these through register_as_the_factory_does: {offenders}'
