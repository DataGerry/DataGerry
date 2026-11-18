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

Every catalogue right is a family class built name-first - `ObjectRight('view', description=...)` - whose only own
state is its `PREFIX`. Pinned here, for every right class:

* it is a BaseRight and declares no constructor of its own
* it carries none of the retired attributes (the security levels, the never-read ``DEFAULT_MASTER``) - a right is
  a name, a label and a description; ``is_master`` follows from the name

Pure: the modules are imported, nothing touches Mongo or Flask
"""
import importlib
import inspect
import pkgutil

import pytest

import cmdb.models.right_model as right_model_package
from cmdb.models.right_model.base_right import BaseRight
# -------------------------------------------------------------------------------------------------------------------- #

#: Fewer than this many right classes means the discovery below is broken, not that rights vanished
MIN_EXPECTED_RIGHT_CLASSES: int = 50

#: The class attributes the retired security levels lived in, and the never-read master default
RETIRED_ATTRIBUTES: tuple[str, ...] = (
    'MIN_LEVEL', 'MAX_LEVEL', 'DEFAULT_LEVEL', 'level', 'default_level', 'DEFAULT_MASTER',
)
PROBE_NAME: str = 'probe'


def _right_classes() -> list[type[BaseRight]]:
    """Every BaseRight subclass defined in the right_model package, BaseRight itself excluded"""
    found: list[type[BaseRight]] = []

    for module_info in pkgutil.iter_modules(right_model_package.__path__):
        module = importlib.import_module(f'{right_model_package.__name__}.{module_info.name}')

        for _, cls in inspect.getmembers(module, inspect.isclass):
            if issubclass(cls, BaseRight) and cls is not BaseRight and cls.__module__ == module.__name__:
                found.append(cls)

    return sorted(found, key=lambda cls: cls.__name__)


RIGHT_CLASSES: list[type[BaseRight]] = _right_classes()


def test_the_census_finds_the_right_classes() -> None:
    """A broken discovery would pass every test below vacuously"""
    assert len(RIGHT_CLASSES) >= MIN_EXPECTED_RIGHT_CLASSES


@pytest.mark.parametrize('cls', RIGHT_CLASSES, ids=lambda cls: cls.__name__)
def test_every_right_class_is_a_base_right_without_a_constructor(cls: type[BaseRight]) -> None:
    """A family right only sets its PREFIX"""
    assert issubclass(cls, BaseRight)
    assert '__init__' not in vars(cls)


@pytest.mark.parametrize('cls', [BaseRight, *RIGHT_CLASSES], ids=lambda cls: cls.__name__)
def test_no_right_class_carries_a_security_level(cls: type[BaseRight]) -> None:
    """Neither the class nor a right built from it"""
    right: BaseRight = cls(PROBE_NAME)

    assert [name for name in RETIRED_ATTRIBUTES if hasattr(cls, name) or hasattr(right, name)] == []
