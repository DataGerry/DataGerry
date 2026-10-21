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
Annotation tripwire for every module under ``cmdb/``

Each module is held to four rules, read from the source with ``ast``:

* every parameter (``self`` / ``cls`` aside, ``*args`` / ``**kwargs`` included) carries an annotation
* every function carries a return annotation - ``-> None`` included
* a parameter that defaults to ``None`` says so in its annotation (``str | None = None``, not the implicit
  Optional ``str = None``, which claims the value is always a string)
* no annotation is a bare ``dict``, ``list``, ``tuple``, ``set`` or ``frozenset`` - the item types are part of
  the contract

The whole tree is scanned against a **baseline**: ``annotation_tripwire_baseline.json`` next to this file
lists the modules that still break a rule, with how many violations each has (backend backlog T287). So:

* a module NOT in the baseline must stay clean - a new violation anywhere else fails
* a listed module may not get worse - its count may only go down
* the baseline may not go stale - a module that improved, or got clean, has to be updated or dropped in
  the same change, so the list only ever shrinks and always says what is left

After cleaning modules, regenerate the baseline with::

    python -m tests.unit.test_annotation_tripwire --write-baseline

DB-free and import-free: the modules are parsed, never imported
"""
import ast
import json
import sys
from pathlib import Path

import pytest
# A clean module is the exact value [] - asserting it (not falsiness) shows every violation on failure
# pylint: disable=use-implicit-booleaness-not-comparison
# -------------------------------------------------------------------------------------------------------------------- #

REPO_ROOT: Path = Path(__file__).resolve().parents[2]

#: The tree every module of which is held to the rules
SCANNED_ROOT: Path = REPO_ROOT / 'cmdb'

#: Module path (relative to the repository root) -> its number of violations, for every module that has any
BASELINE_PATH: Path = Path(__file__).with_name('annotation_tripwire_baseline.json')

#: Fewer modules than this means the scan is broken, not that the tree shrank
MIN_EXPECTED_MODULES: int = 1000

#: The command-line switch that rewrites the baseline from the current tree
WRITE_BASELINE_FLAG: str = '--write-baseline'

#: Parameters that are never annotated
IMPLICIT_PARAMETERS: frozenset[str] = frozenset({'self', 'cls'})

#: Collection builtins whose item types have to be spelled out
BARE_COLLECTIONS: frozenset[str] = frozenset({'dict', 'list', 'tuple', 'set', 'frozenset'})

#: Names whose annotation admits None by themselves: ``Any`` bare, and ``Optional[...]``
NONE_ADMITTING_NAMES: frozenset[str] = frozenset({'Any', 'Optional'})


def _scanned_files() -> list[Path]:
    """Every Python module under SCANNED_ROOT, sorted"""
    return sorted(SCANNED_ROOT.rglob('*.py'))


def _relative(path: Path) -> str:
    """A module path as the baseline spells it: relative to the repository root, with forward slashes"""
    return path.relative_to(REPO_ROOT).as_posix()


def current_violations() -> dict[str, list[str]]:
    """Module path -> its violations, for every module under SCANNED_ROOT that has any"""
    found: dict[str, list[str]] = {}

    for path in _scanned_files():
        label: str = _relative(path)
        violations: list[str] = find_violations(path.read_text(encoding='utf-8'), label)

        if violations:
            found[label] = violations

    return found


def read_baseline() -> dict[str, int]:
    """The checked-in baseline: module path -> number of violations still allowed"""
    return json.loads(BASELINE_PATH.read_text(encoding='utf-8'))


def write_baseline() -> dict[str, int]:
    """
    Rewrites the baseline from the current tree

    Returns:
        dict[str, int]: The baseline as written
    """
    baseline: dict[str, int] = {label: len(found) for label, found in sorted(current_violations().items())}
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + '\n', encoding='utf-8')

    return baseline


def _parameters(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    """Every parameter of a function, of every kind, the implicit self / cls excluded"""
    arguments: ast.arguments = function.args
    parameters: list[ast.arg] = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]

    if arguments.vararg:
        parameters.append(arguments.vararg)

    if arguments.kwarg:
        parameters.append(arguments.kwarg)

    return [parameter for parameter in parameters if parameter.arg not in IMPLICIT_PARAMETERS]


def _none_defaulted(function: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.arg]:
    """The parameters whose default is the literal None"""
    arguments: ast.arguments = function.args
    positional: list[ast.arg] = [*arguments.posonlyargs, *arguments.args]
    pairs: list[tuple[ast.arg, ast.expr | None]] = [
        *zip(positional[len(positional) - len(arguments.defaults):], arguments.defaults),
        *zip(arguments.kwonlyargs, arguments.kw_defaults),
    ]

    return [
        parameter for parameter, default in pairs
        if isinstance(default, ast.Constant) and default.value is None
    ]


def _admits_none(annotation: ast.expr) -> bool:
    """
    Whether an annotation admits None: ``None`` itself, bare ``Any``, ``Optional[...]``, or a union with a
    member that does (``X | None``, ``Union[X, None]``). A string annotation is parsed first

    Read from the tree, not the text: ``dict[str, Any]`` mentions ``Any`` and still does not admit None
    """
    if isinstance(annotation, ast.Constant):
        if annotation.value is None:
            return True
        if isinstance(annotation.value, str):
            return _admits_none(ast.parse(annotation.value, mode='eval').body)
        return False

    if isinstance(annotation, (ast.Name, ast.Attribute)):
        name: str = annotation.id if isinstance(annotation, ast.Name) else annotation.attr
        return name == 'Any'

    if isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        return _admits_none(annotation.left) or _admits_none(annotation.right)

    if isinstance(annotation, ast.Subscript):
        origin: ast.expr = annotation.value
        origin_name: str = origin.id if isinstance(origin, ast.Name) else getattr(origin, 'attr', '')

        if origin_name == 'Optional':
            return True

        if origin_name == 'Union':
            members: list[ast.expr] = (
                list(annotation.slice.elts) if isinstance(annotation.slice, ast.Tuple) else [annotation.slice]
            )
            return any(_admits_none(member) for member in members)

    return False


def _bare_collections(annotation: ast.expr | None) -> list[str]:
    """
    The bare collection names an annotation uses, at any depth (``dict[str, list]`` finds ``list``)

    A name directly inside ``type[...]`` is exempt: ``type[dict]`` means the class itself, which has no
    item types to spell out
    """
    if annotation is None:
        return []

    subscripted: set[int] = {id(node.value) for node in ast.walk(annotation) if isinstance(node, ast.Subscript)}
    subscripted |= {
        id(node.slice) for node in ast.walk(annotation)
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'type'
    }

    return [
        node.id for node in ast.walk(annotation)
        if isinstance(node, ast.Name) and node.id in BARE_COLLECTIONS and id(node) not in subscripted
    ]


def find_violations(source: str, label: str) -> list[str]:
    """
    Applies the four rules to one module's source

    Args:
        source (str): The module source
        label (str): How the module is named in the messages

    Returns:
        list[str]: One ``<label>:<line> <function>: <rule>`` message per violation, in source order
    """
    violations: list[str] = []
    tree: ast.Module = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            where: str = f'{label}:{node.lineno} {node.name}'

            for parameter in _parameters(node):
                if parameter.annotation is None:
                    violations.append(f'{where}: parameter {parameter.arg!r} has no annotation')

            if node.returns is None:
                violations.append(f'{where}: no return annotation')

            for parameter in _none_defaulted(node):
                if parameter.annotation is None:
                    continue

                if not _admits_none(parameter.annotation):
                    text: str = ast.unparse(parameter.annotation)
                    violations.append(f'{where}: {parameter.arg!r} defaults to None but is annotated {text!r}')

            annotations: list[ast.expr | None] = [parameter.annotation for parameter in _parameters(node)]

            for name in [bare for annotation in [*annotations, node.returns] for bare in _bare_collections(annotation)]:
                violations.append(f'{where}: bare {name!r} annotation')

        elif isinstance(node, ast.AnnAssign):
            for name in _bare_collections(node.annotation):
                violations.append(f'{label}:{node.lineno}: bare {name!r} annotation')

    return violations


# ------------------------------------------------------------------------------------------------------------------ #

@pytest.fixture(name='current', scope='module')
def fixture_current() -> dict[str, list[str]]:
    """The tree's violations, scanned once per test module"""
    return current_violations()


@pytest.fixture(name='baseline', scope='module')
def fixture_baseline() -> dict[str, int]:
    """The checked-in baseline, read at test time so that writing it never needs it to exist"""
    return read_baseline()


def test_the_scan_covers_real_code() -> None:
    """The whole tree is scanned - a broken glob would pass every rule vacuously"""
    assert len(_scanned_files()) >= MIN_EXPECTED_MODULES


def test_a_clean_module_stays_clean(current: dict[str, list[str]], baseline: dict[str, int]) -> None:
    """A module the baseline does not list may not break a rule"""
    regressions: list[str] = [
        violation for label, found in current.items() if label not in baseline for violation in found
    ]

    assert regressions == []


def test_a_listed_module_does_not_get_worse(current: dict[str, list[str]], baseline: dict[str, int]) -> None:
    """A module the baseline lists may keep its violations, but not add to them"""
    worse: dict[str, list[str]] = {
        label: found for label, found in current.items() if label in baseline and len(found) > baseline[label]
    }

    assert worse == {}


def test_the_baseline_is_current(current: dict[str, list[str]], baseline: dict[str, int]) -> None:
    """
    An improved or cleaned module is recorded in the same change

    Otherwise the slack would let a later change reintroduce violations unnoticed. Regenerate with
    ``python -m tests.unit.test_annotation_tripwire --write-baseline``
    """
    stale: dict[str, tuple[int, int]] = {
        label: (allowed, len(current.get(label, [])))
        for label, allowed in baseline.items() if len(current.get(label, [])) < allowed
    }

    assert stale == {}


def test_every_baseline_entry_names_an_existing_module(baseline: dict[str, int]) -> None:
    """A renamed or deleted module is dropped from the baseline too"""
    assert [label for label in baseline if not (REPO_ROOT / label).is_file()] == []


def test_the_baseline_only_lists_real_debt(baseline: dict[str, int]) -> None:
    """Every listed count is positive - a clean module has no entry"""
    assert [label for label, allowed in baseline.items() if allowed <= 0] == []


class TestTheRules:
    """The scan reports what it exists to report - each rule is proved on a source that breaks it"""

    @pytest.mark.parametrize('source, expected', [
        ('def f(x) -> None: ...', "parameter 'x' has no annotation"),
        ('def f(*args) -> None: ...', "parameter 'args' has no annotation"),
        ('def f(**kwargs) -> None: ...', "parameter 'kwargs' has no annotation"),
        ('def f(x: int): ...', 'no return annotation'),
        ('def f(x: str = None) -> None: ...', "'x' defaults to None but is annotated 'str'"),
        ('def f(*, x: str = None) -> None: ...', "'x' defaults to None but is annotated 'str'"),
        ('def f(x: dict[str, Any] = None) -> None: ...', "'x' defaults to None but is annotated 'dict[str, Any]'"),
        ('def f(x: list[Any] = None) -> None: ...', "'x' defaults to None but is annotated 'list[Any]'"),
        ('def f(x: "int" = None) -> None: ...', "'x' defaults to None but is annotated"),
        ('def f(x: dict) -> None: ...', "bare 'dict' annotation"),
        ('def f() -> list: ...', "bare 'list' annotation"),
        ('def f(x: dict[str, list]) -> None: ...', "bare 'list' annotation"),
        ('class A:\n    SCHEMA: dict = {}', "bare 'dict' annotation"),
        ('def f(x: tuple) -> None: ...', "bare 'tuple' annotation"),
        ('def f() -> set: ...', "bare 'set' annotation"),
        ('class A:\n    KEYS: frozenset = frozenset()', "bare 'frozenset' annotation"),
    ], ids=['unannotated', 'varargs', 'kwargs', 'no-return', 'implicit-optional', 'implicit-optional-kwonly',
            'implicit-optional-mentions-any', 'implicit-optional-list-of-any', 'implicit-optional-string',
            'bare-dict-param', 'bare-list-return', 'bare-list-nested', 'bare-dict-attribute',
            'bare-tuple-param', 'bare-set-return', 'bare-frozenset-attribute'])
    def test_a_violation_is_reported(self, source: str, expected: str) -> None:
        """One broken rule, one message naming it"""
        violations: list[str] = find_violations(source, 'sample.py')

        assert len(violations) == 1
        assert expected in violations[0]

    @pytest.mark.parametrize('source', [
        'def f(self, x: str | None = None) -> None: ...',
        'def f(cls, x: Optional[str] = None) -> None: ...',
        'def f(x: Any = None) -> None: ...',
        'def f(x: typing.Any = None) -> None: ...',
        'def f(x: Union[int, None] = None) -> None: ...',
        'def f(x: "int | None" = None) -> None: ...',
        'def f(x: dict[str, Any] | None = None) -> None: ...',
        'def f(x: dict[str, Any]) -> list[int]: ...',
        'def f(x: int = 0, *args: Any, **kwargs: Any) -> None: ...',
        'class A:\n    SCHEMA: dict[str, Any] = {}\n    COLLECTION = "x"',
        'def f(x: tuple[str, ...], y: set[int]) -> frozenset[str]: ...',
        'def f(x: type[dict]) -> None: ...',
    ], ids=['union-none', 'optional', 'any', 'typing-any', 'union-of-none', 'string-union', 'dict-of-any-or-none',
            'subscripted', 'annotated-varargs', 'subscripted-attribute', 'subscripted-tuple-set',
            'type-of-a-collection'])
    def test_a_clean_signature_is_not_reported(self, source: str) -> None:
        """The spellings the rules allow"""
        assert find_violations(source, 'sample.py') == []


if __name__ == '__main__':
    if WRITE_BASELINE_FLAG in sys.argv[1:]:
        WRITTEN: dict[str, int] = write_baseline()
        print(f'{BASELINE_PATH.name}: {len(WRITTEN)} modules, {sum(WRITTEN.values())} violations')
    else:
        print(f'usage: python -m tests.unit.test_annotation_tripwire {WRITE_BASELINE_FLAG}')

