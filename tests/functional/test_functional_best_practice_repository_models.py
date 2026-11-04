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
Functional tests: the synced best-practice repository's models, offered by ``GET /start_assistant/models``

A models folder in ``tmp_path`` holds a bundled model; the repository sync (GitHub stubbed by an in-memory archive)
mirrors the repository's models into its ``repository`` subfolder, and the route - its catalogue loaded by the real
catalogue code from that folder - lists them. Pinned: a repository model is offered, it replaces the bundled model of
its id, and a model removed from the repository is no longer offered after the next sync (the next restart)
"""
from http import HTTPStatus
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.framework.configuration_transfer import load_catalogue, sync_best_practice_repository
from cmdb.framework.configuration_transfer import best_practice_repository
from cmdb.framework.configuration_transfer.best_practice_constants import REPOSITORY_MODELS_FOLDER
from cmdb.framework.configuration_transfer.best_practice_repository_constants import BestPracticeRepositoryEnv
from cmdb.interface.rest_api.routes.start_assistant_routes import start_assistant_routes
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import BestPracticeModelKey

from tests.utils.best_practice_model_fixture import model_meta, write_model_file
from tests.utils.best_practice_repository_fixture import REPOSITORY, TOKEN, build_archive, model_file_bytes
# -------------------------------------------------------------------------------------------------------------------- #

MODELS_URL: str = '/start_assistant/models'
ENVIRON: dict[str, str] = {
    BestPracticeRepositoryEnv.REPOSITORY.value: REPOSITORY, BestPracticeRepositoryEnv.TOKEN.value: TOKEN,
}
SHARED_ID: str = 'clients'
REPOSITORY_ONLY_ID: str = 'network'
BUNDLED_TITLE: str = 'Bundled clients'
REPOSITORY_TITLE: str = 'Repository clients'
NETWORK_TITLE: str = 'Repository network'
TITLE_KEY: str = BestPracticeModelKey.TITLE.value


def _sync_and_list(rest_api, models_folder: Path, monkeypatch: pytest.MonkeyPatch,
                   files: dict[str, bytes]) -> list[tuple[str, Any]]:
    """Syncs an archive holding ``files``, loads the folder's catalogue for the route; the cards' (id, title)"""
    with patch.object(best_practice_repository, 'download_repository_archive', return_value=build_archive(files)):
        assert sync_best_practice_repository(models_folder / REPOSITORY_MODELS_FOLDER, environ=ENVIRON) is not None

    catalogue = load_catalogue(models_folder)
    monkeypatch.setattr(start_assistant_routes, 'get_best_practice_catalogue', lambda: catalogue)
    response = rest_api.get(MODELS_URL)

    assert response.status_code == HTTPStatus.OK
    return [(card[BestPracticeModelKey.MODEL_ID.value], card[TITLE_KEY]) for card in response.get_json()]


def test_the_repository_models_are_offered_and_win_on_a_shared_id(rest_api, tmp_path: Path,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """The bundled 'clients' is replaced, 'network' is the repository's own"""
    write_model_file(tmp_path, SHARED_ID, meta=model_meta(title=BUNDLED_TITLE, order=0))

    cards = _sync_and_list(rest_api, tmp_path, monkeypatch, {
        f'{SHARED_ID}.json': model_file_bytes(title=REPOSITORY_TITLE, order=0),
        f'{REPOSITORY_ONLY_ID}.json': model_file_bytes(title=NETWORK_TITLE, order=1),
    })

    assert cards == [(SHARED_ID, REPOSITORY_TITLE), (REPOSITORY_ONLY_ID, NETWORK_TITLE)]


def test_a_model_removed_from_the_repository_is_no_longer_offered(rest_api, tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    """The next sync removes its file; the bundled model of that id is offered again"""
    write_model_file(tmp_path, SHARED_ID, meta=model_meta(title=BUNDLED_TITLE, order=0))
    _sync_and_list(rest_api, tmp_path, monkeypatch, {
        f'{SHARED_ID}.json': model_file_bytes(title=REPOSITORY_TITLE, order=0),
        f'{REPOSITORY_ONLY_ID}.json': model_file_bytes(title=NETWORK_TITLE, order=1),
    })

    cards = _sync_and_list(rest_api, tmp_path, monkeypatch, {})

    assert cards == [(SHARED_ID, BUNDLED_TITLE)]
    assert not list((tmp_path / REPOSITORY_MODELS_FOLDER).iterdir())
