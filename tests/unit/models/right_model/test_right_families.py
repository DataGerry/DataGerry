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
Census of the right family classes in cmdb.models.right_model

Every catalogue right is built through `DefaultLevelRight`: name first, and a level left out taken from
the class - its `DEFAULT_LEVEL` when set, its `MIN_LEVEL` otherwise. The classes used to carry one
forwarding constructor each (53 of them) whose only job was that default; they are gone, so what keeps
the defaults honest is this module:

* every right class is a DefaultLevelRight and declares no constructor of its own
* every class's default level lies inside its own MIN_LEVEL / MAX_LEVEL window
* the classes whose default sits ABOVE their minimum are exactly the pinned ones - a new family member
  inheriting SECURE by accident, or one losing it, fails here

Pure: the modules are imported, nothing touches Mongo or Flask
"""
import importlib
import inspect
import pkgutil

import pytest

import cmdb.models.right_model as right_model_package
from cmdb.models.right_model.base_right import BaseRight, DefaultLevelRight
from cmdb.models.right_model.levels_enum import Levels
# -------------------------------------------------------------------------------------------------------------------- #

#: The right classes whose default level is above their MIN_LEVEL, and the level they default to
DEFAULTS_ABOVE_MINIMUM: dict[str, Levels] = {
    'DocapiRight': Levels.SECURE,
    'DocapiTemplateRight': Levels.SECURE,
    'ExportRight': Levels.SECURE,
    'ExportObjectRight': Levels.SECURE,
    'ImportRight': Levels.SECURE,
    'ImportObjectRight': Levels.SECURE,
    'TypeRight': Levels.SECURE,
}

#: Fewer than this many right classes means the discovery below is broken, not that rights vanished
MIN_EXPECTED_RIGHT_CLASSES: int = 50


def _right_classes() -> list[type[BaseRight]]:
    """Every BaseRight subclass defined in the right_model package, DefaultLevelRight itself excluded"""
    found: list[type[BaseRight]] = []

    for module_info in pkgutil.iter_modules(right_model_package.__path__):
        module = importlib.import_module(f'{right_model_package.__name__}.{module_info.name}')

        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseRight) and cls not in (BaseRight, DefaultLevelRight) \
                    and cls.__module__ == module.__name__:
                found.append(cls)

    return sorted(found, key=lambda cls: cls.__name__)


RIGHT_CLASSES: list[type[BaseRight]] = _right_classes()


def test_the_census_finds_the_right_classes() -> None:
    """A broken discovery would pass every test below vacuously"""
    assert len(RIGHT_CLASSES) >= MIN_EXPECTED_RIGHT_CLASSES


@pytest.mark.parametrize('cls', RIGHT_CLASSES, ids=lambda cls: cls.__name__)
def test_every_right_class_takes_its_default_from_the_class(cls: type[BaseRight]) -> None:
    """A family right, with no constructor of its own to bind a default"""
    assert issubclass(cls, DefaultLevelRight)
    assert '__init__' not in vars(cls)


@pytest.mark.parametrize('cls', RIGHT_CLASSES, ids=lambda cls: cls.__name__)
def test_every_default_level_is_inside_the_class_window(cls: type[DefaultLevelRight]) -> None:
    """A right built without a level is a valid right of its class"""
    default: Levels = cls.default_level()

    assert cls.MIN_LEVEL <= default <= cls.MAX_LEVEL
    assert cls('probe').level is default


def test_only_the_pinned_classes_default_above_their_minimum() -> None:
    """Every other class defaults to its own MIN_LEVEL"""
    above: dict[str, Levels] = {
        cls.__name__: cls.default_level() for cls in RIGHT_CLASSES if cls.default_level() != cls.MIN_LEVEL
    }

    assert above == DEFAULTS_ABOVE_MINIMUM
