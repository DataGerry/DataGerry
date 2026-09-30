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
Override tripwire: a method that overrides a base-class method keeps the base's return contract

The annotation tripwire (``test_annotation_tripwire.py``) checks that annotations EXIST. This module checks
that they AGREE along the class hierarchy: a caller holding the base class relies on the base's return
annotation, so an override may return the same type or a narrower one, never a different one. Two found by
hand before this test existed - ``SettingsManager.get_sections`` answering documents where ``SystemReader``
promises section names, and ``SystemEnvironmentReader.get_sections`` answering a dict view annotated as a
list.

An override's return annotation is accepted when it is:

* the same annotation as the base's (compared once resolved, so a string forward reference counts)
* narrower than the base's: a subclass of the base's class (``ObjectParserResponse`` under
  ``BaseParserResponse``), or a member / sub-union of the base's union (``int`` under ``int | None``)
* anything, when the base's is ``Any`` or missing (the base promises nothing to narrow), or a TypeVar
  (``CmdbDAO.from_data -> T``): any class satisfies it, within the TypeVar's bound when it has one
* a subclass of a generic base's origin (``GroupACL`` under ``AccessControlListSection[T]``)

A MISSING or bare-generic override annotation (``-> dict`` under ``dict[str, Any]``) is not reported here:
that is annotation debt, and ``test_annotation_tripwire.py`` counts it already.

Only bases defined in ``cmdb`` are compared: a framework class (Flask's ``Blueprint``, ``GridFS``, ...) states
its own contract, which the override is free to narrow in its own way.

Anything else fails, unless it is listed in ``ALLOWED_WIDENINGS`` with its reason.

The ``cmdb`` package is imported, not parsed - the hierarchy only exists at runtime
"""
import importlib
import inspect
import pkgutil
import types
import typing
from typing import Any

import pytest

import cmdb
# A clean result is the exact value [] - asserting it (not falsiness) shows every finding on failure
# pylint: disable=use-implicit-booleaness-not-comparison
# -------------------------------------------------------------------------------------------------------------------- #

#: (qualified class name, method name) -> why the override may widen its base's return type
ALLOWED_WIDENINGS: dict[tuple[str, str], str] = {
    ('cmdb.interface.rest_api.responses.default_response.DefaultResponse', 'export'):
        'the one response whose body is its payload, bare - every other export returns the envelope dict',
}

#: Module-name prefix of the classes whose contracts are compared
CMDB_PREFIX: str = f'{cmdb.__name__}.'

#: Fewer classes than this means the discovery is broken, not that the package shrank
MIN_EXPECTED_CLASSES: int = 300


def _function_of(member: Any) -> Any:
    """The plain function behind a method, classmethod or staticmethod; None for anything else"""
    if isinstance(member, (classmethod, staticmethod)):
        member = member.__func__

    return member if inspect.isfunction(member) else None


def _return_annotation(function: Any) -> Any:
    """A function's return annotation, resolved when it is a forward reference; empty when it has none"""
    try:
        hints: dict[str, Any] = typing.get_type_hints(function)
    except Exception:  # pylint: disable=broad-exception-caught
        hints = dict(function.__annotations__)

    return hints.get('return', inspect.Signature.empty)


def _union_members(annotation: Any) -> tuple[Any, ...] | None:
    """The members of a union annotation (``X | Y`` or ``Optional[X]``); None when it is not a union"""
    if isinstance(annotation, types.UnionType) or typing.get_origin(annotation) is typing.Union:
        return typing.get_args(annotation)

    return None


def _satisfies_bound(override: Any, bound: Any) -> bool:
    """Whether an annotation satisfies a TypeVar bound - a class, or a forward reference to one by name"""
    if bound is None:
        return True

    if not inspect.isclass(override):
        return False

    if isinstance(bound, (str, typing.ForwardRef)):
        bound_name: str = bound if isinstance(bound, str) else bound.__forward_arg__
        return any(ancestor.__name__ == bound_name for ancestor in override.__mro__)

    return inspect.isclass(bound) and issubclass(override, bound)


def _is_narrower(override: Any, base: Any) -> bool:
    """Whether a single (non-union) annotation is the base's, or a class below the base's class"""
    if override == base:
        return True

    if isinstance(base, typing.TypeVar):
        return _satisfies_bound(override, base.__bound__)

    base_class: Any = typing.get_origin(base) or base

    return inspect.isclass(override) and inspect.isclass(base_class) and issubclass(override, base_class)


def _returns_agree(override: Any, base: Any) -> bool:
    """Whether an override's return annotation keeps the base's contract (see the module docstring)"""
    if base is inspect.Signature.empty or base is Any or override is inspect.Signature.empty:
        return True

    if override == base or str(override) == str(base):
        return True

    base_members: tuple[Any, ...] | None = _union_members(base)

    if base_members is None:
        return _is_narrower(override, base)

    override_members: tuple[Any, ...] = _union_members(override) or (override,)

    return all(any(_is_narrower(member, allowed) for allowed in base_members) for member in override_members)


def find_disagreements(classes: list[type], compared_prefix: str = CMDB_PREFIX) -> list[str]:
    """
    Compares every overriding method's return annotation with the nearest base that defines the method

    Dunder methods are skipped: constructors and protocol methods legitimately change shape

    Args:
        classes (list[type]): The classes to check
        compared_prefix (str): Only a base whose module starts with this is compared (see the module
            docstring); the self-tests pass their own module

    Returns:
        list[str]: One ``Class.method: base returns X, override returns Y`` message per disagreement
    """
    found: list[str] = []

    for cls in classes:
        for name, member in vars(cls).items():
            function = _function_of(member)

            if function is None or (name.startswith('__') and name.endswith('__')):
                continue

            for base in cls.__mro__[1:]:
                base_function = _function_of(vars(base).get(name))

                if base_function is None:
                    continue

                if not base.__module__.startswith(compared_prefix):
                    break

                override_return = _return_annotation(function)
                base_return = _return_annotation(base_function)
                qualified = f'{cls.__module__}.{cls.__qualname__}'

                if not _returns_agree(override_return, base_return) and (qualified, name) not in ALLOWED_WIDENINGS:
                    found.append(f'{qualified}.{name}: base {base.__qualname__} returns {base_return!r}, '
                                 f'the override returns {override_return!r}')
                break

    return found


def _cmdb_classes() -> list[type]:
    """Every class defined in a module of the cmdb package"""
    classes: dict[str, type] = {}

    for module_info in pkgutil.walk_packages(cmdb.__path__, f'{cmdb.__name__}.'):
        module = importlib.import_module(module_info.name)

        for _, cls in inspect.getmembers(module, inspect.isclass):
            if cls.__module__ == module.__name__:
                classes[f'{cls.__module__}.{cls.__qualname__}'] = cls

    return [classes[key] for key in sorted(classes)]


@pytest.fixture(name='cmdb_classes', scope='module')
def fixture_cmdb_classes() -> list[type]:
    """The cmdb classes, discovered once for the module"""
    return _cmdb_classes()


def test_the_discovery_finds_the_package(cmdb_classes: list[type]) -> None:
    """A broken walk would pass the census vacuously"""
    assert len(cmdb_classes) >= MIN_EXPECTED_CLASSES


def test_every_override_keeps_its_base_return_contract(cmdb_classes: list[type]) -> None:
    """The census over the whole package"""
    assert find_disagreements(cmdb_classes) == []


def test_every_allowed_widening_still_exists(cmdb_classes: list[type]) -> None:
    """An allowance whose method is gone or agrees again is removed, not left behind"""
    by_name: dict[str, type] = {f'{cls.__module__}.{cls.__qualname__}': cls for cls in cmdb_classes}

    for qualified, method in ALLOWED_WIDENINGS:
        assert qualified in by_name, qualified
        assert method in vars(by_name[qualified]), (qualified, method)


# ------------------------------------------------------------------------------------------------------------------ #

#: The self-tests' sample classes live in this module, so their bases are compared under its name
SAMPLE_PREFIX: str = __name__


class SampleBase:
    """A sample base class: the contracts the overrides below keep or break"""

    def names(self) -> list[str]:
        """Section names"""
        return []

    def anything(self) -> Any:
        """Promises nothing"""

    def maybe(self) -> int | None:
        """A value or nothing"""
        return None

    def make(self) -> 'SampleBase':
        """A factory, annotated with a forward reference"""
        return SampleBase()

    @classmethod
    def build(cls) -> int:
        """A classmethod"""
        return 0

    def __call__(self) -> int:
        """A dunder, never compared"""
        return 0


class ChangesTheReturn(SampleBase):
    """The SettingsManager case: documents where names were promised"""

    def names(self) -> list[dict[str, Any]]:
        """Breaks the contract"""
        return []


class ChangesAClassmethod(SampleBase):
    """classmethod overrides are unwrapped and compared"""

    @classmethod
    def build(cls) -> str:
        """Breaks the contract"""
        return ''


class KeepsTheContract(SampleBase):
    """Every allowed way of overriding"""

    def names(self) -> 'list[str]':
        """The same type, written as a forward reference"""
        return []

    def anything(self) -> str:
        """Narrowing from Any"""
        return ''

    def maybe(self) -> int:
        """A member of the base's union"""
        return 0

    def make(self) -> 'KeepsTheContract':
        """A subclass of the base's (forward-referenced) class"""
        return KeepsTheContract()

    def __call__(self) -> str:  # type: ignore[override]
        """A dunder may change shape"""
        return ''


class LeavesTheUnion(SampleBase):
    """str is not a member of int | None"""

    def maybe(self) -> str:
        """Breaks the contract"""
        return ''


class TestTheRule:
    """The comparison accepts what keeps the contract and reports what breaks it"""

    @pytest.mark.parametrize('override, method', [
        (ChangesTheReturn, 'names'), (ChangesAClassmethod, 'build'), (LeavesTheUnion, 'maybe'),
    ], ids=['different-return', 'classmethod', 'outside-the-union'])
    def test_a_broken_contract_is_reported(self, override: type, method: str) -> None:
        """One disagreement, naming the method"""
        found: list[str] = find_disagreements([override], SAMPLE_PREFIX)

        assert len(found) == 1
        assert f'.{method}:' in found[0]

    def test_every_allowed_override_agrees(self) -> None:
        """Same type, forward reference, narrowing from Any, union member, subclass, dunder"""
        assert find_disagreements([KeepsTheContract], SAMPLE_PREFIX) == []

    def test_a_base_outside_the_compared_prefix_is_skipped(self) -> None:
        """A framework base states its own contract - the census compares cmdb bases only"""
        assert find_disagreements([ChangesTheReturn], CMDB_PREFIX) == []
