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
Tripwire: DocAPI templates are rendered only in the sandboxed Jinja2 environment

A DocAPI ``template_data`` string is author-supplied and rendered for a wider audience than its author, so an
un-sandboxed ``jinja2.Environment`` renders untrusted code with full interpreter access (the SSTI -> RCE surface).
The one environment is built by ``template_engine.build_docapi_environment`` (a ``SandboxedEnvironment``); this scan
fails on any other construction of a plain ``Environment`` and on any import of it, so a second, unsandboxed engine
cannot slip in.

Read with ``ast`` over every module under ``cmdb/``.
"""
import ast
from pathlib import Path
# -------------------------------------------------------------------------------------------------------------------- #

CMDB_ROOT: Path = Path(__file__).resolve().parents[2] / 'cmdb'

# The unsandboxed class name; its sandboxed counterpart is 'SandboxedEnvironment', which is allowed
UNSAFE_ENVIRONMENT: str = 'Environment'
JINJA_MODULE_PREFIX: str = 'jinja2'

# The smallest tree the scan must still cover, so a moved package cannot make it pass vacuously
MIN_SCANNED_MODULES: int = 1000


def unsandboxed_jinja_uses(source: str) -> list[int]:
    """
    The lines of a module that import or construct a plain Jinja2 ``Environment``

    Args:
        source (str): A module's source

    Returns:
        list[int]: Line numbers of ``from jinja2 import Environment`` / ``jinja2.Environment`` and of a bare
            ``Environment(...)`` call (``SandboxedEnvironment`` is left alone)
    """
    tree = ast.parse(source)
    found: list[int] = []

    for node in ast.walk(tree):
        # from jinja2 import Environment
        if isinstance(node, ast.ImportFrom) and (node.module or '').startswith(JINJA_MODULE_PREFIX):
            if any(alias.name == UNSAFE_ENVIRONMENT for alias in node.names):
                found.append(node.lineno)

        # import jinja2  ...  jinja2.Environment(...)
        if isinstance(node, ast.Attribute) and node.attr == UNSAFE_ENVIRONMENT:
            found.append(node.lineno)

        # a bare Environment(...) call
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == UNSAFE_ENVIRONMENT:
            found.append(node.lineno)

    return sorted(set(found))


def _modules() -> list[Path]:
    """Every Python module under cmdb/."""
    return sorted(CMDB_ROOT.rglob('*.py'))


def test_the_scan_covers_the_tree() -> None:
    """Guards the scan itself"""
    assert len(_modules()) >= MIN_SCANNED_MODULES


def test_no_module_uses_an_unsandboxed_jinja_environment() -> None:
    """Names each offending line"""
    offenders: list[str] = [
        f'{path.relative_to(CMDB_ROOT.parent)}:{line}'
        for path in _modules()
        for line in unsandboxed_jinja_uses(path.read_text(encoding='utf-8'))
    ]

    assert not offenders, 'render DocAPI templates only through build_docapi_environment (sandboxed): ' + \
        ', '.join(offenders)


def test_the_check_sees_the_unsafe_forms_and_allows_the_sandbox() -> None:
    """The checker itself: import, attribute access and a bare call are caught; the sandbox is not"""
    source = (
        'from jinja2 import Environment, ChainableUndefined\n'
        'import jinja2\n'
        'from jinja2.sandbox import SandboxedEnvironment\n'
        'a = Environment(autoescape=True)\n'
        'b = jinja2.Environment()\n'
        'c = SandboxedEnvironment(autoescape=True)\n'
    )

    # the import (1), the bare call (4), and the attribute access (5) - never the sandbox
    assert unsandboxed_jinja_uses(source) == [1, 4, 5]
