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
Tripwire: every CmdbDAO model's ``__init__`` is keyword-only

``CmdbDAO.__new__`` reads the required keys out of the KEYWORD arguments, so a model has never been constructible by
position. The ``*`` marker states that in the signature - and it is what keeps ``too-many-positional-arguments`` off a
constructor as wide as its document, so a new model written without it shows up here instead of as a new waiver.

Read at runtime over every module under ``cmdb.models``: a model is a CmdbDAO subclass however many classes sit
between, which an import resolves and a source scan cannot.
"""
import importlib
import inspect
import pkgutil
from inspect import Parameter
from typing import Any

import cmdb.models
from cmdb.models.cmdb_dao import CmdbDAO
# -------------------------------------------------------------------------------------------------------------------- #

# The smallest population the census must still find, so a moved package cannot make it pass vacuously
MIN_MODELS: int = 35

POSITIONAL_KINDS: frozenset[Any] = frozenset({Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD})


def _import_every_model_module() -> None:
    """Imports every module under cmdb.models, so each CmdbDAO subclass is registered."""
    for module in pkgutil.walk_packages(cmdb.models.__path__, f'{cmdb.models.__name__}.'):
        importlib.import_module(module.name)


def _subclasses(cls: type) -> set[type]:
    """Every subclass of the class, however deep."""
    found: set[type] = set()

    for subclass in cls.__subclasses__():
        found |= {subclass} | _subclasses(subclass)

    return found


def positional_parameters(cls: type) -> list[str]:
    """
    The parameters of a class's OWN ``__init__`` that can be passed by position, ``self`` left out

    Args:
        cls (type): The class to inspect

    Returns:
        list[str]: Their names; empty when the class defines no ``__init__`` or every parameter is keyword-only
    """
    if '__init__' not in vars(cls):
        return []

    parameters = list(inspect.signature(cls.__init__).parameters.values())[1:]

    return [parameter.name for parameter in parameters if parameter.kind in POSITIONAL_KINDS]


def _models() -> set[type]:
    """Every CmdbDAO subclass defined under cmdb.models."""
    _import_every_model_module()

    return {model for model in _subclasses(CmdbDAO) if model.__module__.startswith(cmdb.models.__name__)}


def test_the_census_finds_the_models() -> None:
    """Guards the census itself"""
    assert len(_models()) >= MIN_MODELS


def test_every_model_constructor_is_keyword_only() -> None:
    """Names each model whose ``__init__`` still takes a parameter by position"""
    offenders: dict[str, list[str]] = {
        f'{model.__module__}.{model.__qualname__}': positional
        for model in _models()
        if (positional := positional_parameters(model))
    }

    assert not offenders, f'add the keyword-only marker (*) after self: {offenders}'


def test_the_check_sees_a_positional_parameter() -> None:
    """The checker itself: a positional parameter is reported, a keyword-only one and an inherited init are not"""

    class Positional:
        """A constructor taking its argument by position"""
        def __init__(self, public_id: int) -> None:
            self.public_id = public_id

    class KeywordOnly:
        """A keyword-only constructor"""
        def __init__(self, *, public_id: int) -> None:
            self.public_id = public_id

    class Inheriting(KeywordOnly):
        """No __init__ of its own"""

    assert positional_parameters(Positional) == ['public_id']
    assert not positional_parameters(KeywordOnly)
    assert not positional_parameters(Inheriting)
