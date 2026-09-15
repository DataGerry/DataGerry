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
Guard for the collection registries CollectionValidator iterates

A model reaches CollectionValidator only by being listed in one of three places:

    cmdb.framework.constants.__COLLECTIONS__              the framework collections
    cmdb.models.user_management_constants.__COLLECTIONS__  the user-management collections
    CollectionValidator.init_cache_collections             CmdbCachedUser, in its own database

A model missing from all three is NOT merely un-created: its collection appears anyway, created
implicitly by the first write, carrying no index but '_id_'. Every index the model declares - a unique
one included - then simply does not exist, in production, while every unit test still passes because
the test database never goes through CollectionValidator at all.

That is not a hypothetical. It was live twice: `CmdbPort` when the ports collection was added
(2026-09-01, caught during the step), and `DocapiTemplate`, whose unique index on 'name' had never
been built although the create route's own docstring names it as half of the name-uniqueness
guarantee.

The other registry tests in this folder monkeypatch FRAMEWORK_CLASSES to fakes, which is right for
testing the validator's behaviour and is exactly why nothing was checking its CONTENT. This module
checks the content, and discovers the models by walking the packages rather than from a list - a
hardcoded list would need the same maintenance the registries need, and would fail the same way.

Pure tests: the walk imports cmdb.models and cmdb.framework, nothing else
"""
import importlib
import inspect
import pkgutil
import sys
from typing import Any

import pytest

import cmdb.framework
import cmdb.models
from cmdb.framework.constants import __COLLECTIONS__ as FRAMEWORK_CLASSES
from cmdb.framework.media_library.media_file import MediaFile
from cmdb.models.cached_user_model.cmdb_cached_user import CmdbCachedUser
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.models.user_management_constants import __COLLECTIONS__ as USER_MANAGEMENT_CLASSES
# -------------------------------------------------------------------------------------------------------------------- #

# The packages a collection-owning model may live in. cmdb/models holds the domain entities;
# cmdb/framework holds the two older ones that predate that split (DocapiTemplate, MediaFile)
SEARCHED_PACKAGES: tuple[Any, ...] = (cmdb.models, cmdb.framework)

# Models that own a collection but must NOT be registered, each with the reason. Anything else
# missing from the registries is a defect, so this mapping is the only escape hatch - and adding a row
# to it is a deliberate, reviewed decision rather than a way to silence the guard
EXEMPT_FROM_REGISTRATION: dict[type, str] = {
    MediaFile: (
        "MediaFile.COLLECTION ('media.libary') is a GridFS BUCKET name, not a collection: the file "
        "documents live in 'media.libary.files' and carry 'filename', not 'name'. Registering it "
        "would create an empty 'media.libary' collection and a unique index on a field nothing "
        "stores. Its INDEX_KEYS is therefore unbuildable as declared - see the note in the module "
        "docstring of the media library sweep"
    ),
}


def _import_searched_packages() -> None:
    """Imports every module of the searched packages, so their classes are defined"""
    for package in SEARCHED_PACKAGES:
        for module in pkgutil.walk_packages(package.__path__, prefix=f'{package.__name__}.'):
            importlib.import_module(module.name)


def _owns_a_collection(candidate: type) -> bool:
    """
    Reports whether a class is something CollectionValidator could create a collection for

    The two requirements are exactly what the validator's loop uses: a concrete COLLECTION name and
    get_index_keys(). A '*' in the name marks an abstract base ('framework.*', 'docapi.*'), and a
    manager also carries a COLLECTION but no get_index_keys, so both drop out here
    """
    collection = getattr(candidate, 'COLLECTION', None)

    return (
        isinstance(collection, str)
        and '*' not in collection
        and hasattr(candidate, 'get_index_keys')
    )


def _discover_collection_owners() -> list[type]:
    """
    Returns every class in the searched packages that owns a collection

    Discovered by walking the packages, deliberately: a hardcoded list here would have to be
    maintained alongside the registries it is meant to guard, and would go stale in the same way

    Returns:
        list[type]: The collection-owning classes, sorted by name
    """
    _import_searched_packages()

    owners: set[type] = set()

    for name, module in list(sys.modules.items()):
        if not any(name.startswith(package.__name__) for package in SEARCHED_PACKAGES):
            continue

        for _, candidate in inspect.getmembers(module, inspect.isclass):
            # Only where the class is DEFINED, so a re-exported class is not reported twice
            if candidate.__module__ == name and _owns_a_collection(candidate):
                owners.add(candidate)

    return sorted(owners, key=lambda owner: owner.__name__)


def _registered_classes() -> set[type]:
    """Every class CollectionValidator creates a collection for, across its three paths"""
    return set(FRAMEWORK_CLASSES) | set(USER_MANAGEMENT_CLASSES) | {CmdbCachedUser}


def _index_names(model: type) -> set[str]:
    """The names of every index a model declares, its inherited public_id index included"""
    return {index.document['name'] for index in model.get_index_keys()}


COLLECTION_OWNERS: list[type] = _discover_collection_owners()

# -------------------------------------------------------------------------------------------------------------------- #
#                                              the guard itself                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_walk_finds_the_collection_owners() -> None:
    """
    A broken walk would make every assertion below vacuous

    The registries are the lower bound: whatever else discovery finds, it has to find at least what is
    already registered.
    """
    assert _registered_classes() <= set(COLLECTION_OWNERS)


@pytest.mark.parametrize('model', COLLECTION_OWNERS, ids=lambda model: model.__name__)
def test_every_collection_owner_reaches_the_collection_validator(model: type) -> None:
    """
    A model in no registry gets NO collection created and therefore NO index built

    Three ways to be legitimate:
      - registered directly, the normal case
      - exempt for a documented reason (EXEMPT_FROM_REGISTRATION)
      - a subtype stored in a registered class's collection, declaring no index of its own beyond
        what that class already declares (CmdbObjectLog in framework.logs)
    """
    registered = _registered_classes()

    if model in registered or model in EXEMPT_FROM_REGISTRATION:
        return

    covering = [other for other in registered if getattr(other, 'COLLECTION', None) == model.COLLECTION]

    assert covering, (
        f"{model.__name__} owns collection '{model.COLLECTION}' but is in no registry, so "
        f"CollectionValidator never creates it and none of its indexes "
        f"({sorted(_index_names(model))}) are ever built. Add it to "
        f"cmdb.framework.constants.__COLLECTIONS__ (or the user-management registry), or exempt it "
        f"here with a reason."
    )

    missing_indexes = _index_names(model) - set().union(*(_index_names(other) for other in covering))

    assert not missing_indexes, (
        f"{model.__name__} shares collection '{model.COLLECTION}' with "
        f"{[other.__name__ for other in covering]}, but declares indexes none of them do "
        f"({sorted(missing_indexes)}). Those are never built - declare them on the registered class "
        f"or register this one."
    )


@pytest.mark.parametrize('model', sorted(_registered_classes(), key=lambda m: m.__name__),
                         ids=lambda model: model.__name__)
def test_every_registered_class_satisfies_the_validator_contract(model: type) -> None:
    """
    The validator's loop calls exactly these two things on every entry

    A registry entry that does not answer them raises at startup, taking the whole
    init_framework_collections pass down with it (CollectionInitError).
    """
    assert isinstance(getattr(model, 'COLLECTION', None), str)
    assert '*' not in model.COLLECTION
    assert model.get_index_keys() is not None


def test_no_two_registered_classes_claim_the_same_collection() -> None:
    """
    Two entries for one collection would make the create-vs-reconcile branch order-dependent

    The first one creates the collection with its own indexes; the second then takes the reconcile
    branch and only adds what is missing by NAME - so a same-named index with different options
    silently keeps the first one's definition.
    """
    collections = [model.COLLECTION for model in _registered_classes()]

    assert len(collections) == len(set(collections))


# -------------------------------------------------------------------------------------------------------------------- #
#                                        the two cases the guard has to tolerate                                       #
# -------------------------------------------------------------------------------------------------------------------- #

def test_the_object_log_is_covered_by_the_meta_log() -> None:
    """
    CmdbObjectLog is a subtype sharing framework.logs and inherits its indexes, so it needs no entry

    Pinned because the guard's shared-collection branch exists for exactly this case: if
    CmdbObjectLog ever declares an index of its own, that index would never be built and the guard
    has to start failing.
    """
    assert CmdbObjectLog not in _registered_classes()
    assert CmdbObjectLog.COLLECTION == 'framework.logs'
    assert _index_names(CmdbObjectLog) <= _index_names(CmdbObjectLog.__mro__[1])


def test_every_exemption_carries_a_reason() -> None:
    """An exemption without a stated reason is indistinguishable from an oversight"""
    for model, reason in EXEMPT_FROM_REGISTRATION.items():
        assert reason.strip(), f"{model.__name__} is exempt without a reason"


def test_the_exemptions_are_still_unregistered() -> None:
    """
    An exempt model that got registered anyway means the exemption is stale

    Without this, a row here would keep silently excusing a model long after the reason stopped
    applying.
    """
    registered = _registered_classes()

    for model in EXEMPT_FROM_REGISTRATION:
        assert model not in registered, (
            f"{model.__name__} is now registered - remove its EXEMPT_FROM_REGISTRATION entry"
        )
