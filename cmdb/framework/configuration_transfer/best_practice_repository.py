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
The best-practice repository sync: the models of a private GitHub repository, mirrored into the models folder

Hosted cloud only, once at startup before gunicorn forks its workers (``WebCmdbService._run``). The repository is named
by environment variables (``BestPracticeRepositoryEnv``); unset, nothing happens. Its archive is downloaded through the
GitHub REST API (``GET /repos/{owner}/{repo}/tarball[/{ref}]``, the token as a Bearer header) and the ``*.json`` files
directly in the configured folder are mirrored into the ``repository`` subfolder of the models folder: a new file is
added, a changed one rewritten, one the repository no longer holds removed. **The repository is the source of truth
for that subfolder only** - the bundled models next to it are never touched. The catalogue reads the subfolder too,
and a repository model replaces a bundled model of the same id.

**A failed sync never stops the startup**: a missing token, a misspelt name, an unreachable or refusing GitHub, an
unreadable archive or a folder that cannot be written is one WARNING, and the assistant offers what the folder holds.
The token never reaches a log line or an error message. A repository model that cannot be offered is left out and
logged at ERROR like a bundled one, and one whose own references do not resolve is logged at ERROR - repository files
are not checked in CI as the bundled ones are
"""
import io
import os
import re
import tarfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from http import HTTPStatus
from logging import Logger, getLogger
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import requests
from requests import RequestException

from cmdb.errors.configuration_transfer import BestPracticeRepositoryError
from cmdb.framework.configuration_transfer.best_practice_catalogue import (
    find_model_files,
    load_models,
    repository_models_folder,
)
from cmdb.framework.configuration_transfer.best_practice_constants import MODEL_FILE_SUFFIX
from cmdb.framework.configuration_transfer.best_practice_preview import find_preview_problems
from cmdb.framework.configuration_transfer.best_practice_repository_constants import (
    ARCHIVE_READ_MODE,
    ARCHIVE_TOO_LARGE,
    ARCHIVE_UNREADABLE,
    BEARER_TOKEN,
    CONNECT_TIMEOUT_SECONDS,
    DOWNLOAD_CHUNK_BYTES,
    DOWNLOAD_FAILED,
    DOWNLOAD_REFUSED,
    FOLDER_NOT_WRITABLE,
    GITHUB_ACCEPT,
    GITHUB_API_URL,
    GITHUB_API_VERSION,
    HIDDEN_QUERY,
    MAX_ARCHIVE_BYTES,
    MAX_MODEL_FILE_BYTES,
    MODEL_FILE_TOO_LARGE,
    MODEL_HAS_PROBLEMS,
    PARENT_SEGMENT,
    PARTIAL_FILE_NAME,
    QUERY_STRING_PATTERN,
    READ_TIMEOUT_SECONDS,
    REPOSITORY_NAME_INVALID,
    REPOSITORY_NAME_PATTERN,
    REPOSITORY_PATH_INVALID,
    SYNC_DONE,
    SYNC_FAILED,
    SYNC_NOT_CONFIGURED,
    TARBALL_PATH,
    TARBALL_REF_PATH,
    TOKEN_MISSING,
    BestPracticeRepositoryEnv,
    GitHubRequestHeader,
)
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)


@dataclass(frozen=True)
class RepositorySettings:
    """
    The repository the models are synced from, as the environment names it

    Attributes:
        repository (str): ``owner/repo``
        token (str): The GitHub token - never part of the repr
        ref (str): The branch, tag or commit; empty reads the default branch
        path (PurePosixPath): The folder inside the repository; ``.`` is the root
        api_url (str): The GitHub REST API the archive is downloaded from
    """
    repository: str
    token: str = field(repr=False)
    ref: str = ''
    path: PurePosixPath = PurePosixPath()
    api_url: str = GITHUB_API_URL


@dataclass(frozen=True)
class RepositorySyncReport:
    """
    What one sync changed in the repository folder, each by file name in name order

    Attributes:
        added (tuple[str, ...]): Files the folder did not hold
        updated (tuple[str, ...]): Files whose content changed
        removed (tuple[str, ...]): Files the repository no longer holds
        unchanged (tuple[str, ...]): Files already as the repository holds them
    """
    added: tuple[str, ...] = ()
    updated: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()


def read_repository_settings(environ: Mapping[str, str], api_url: str = GITHUB_API_URL) -> RepositorySettings | None:
    """
    Reads the repository settings from the environment

    Args:
        environ (Mapping[str, str]): The environment variables
        api_url (str): The GitHub REST API the archive is downloaded from

    Raises:
        BestPracticeRepositoryError: When a repository is named but the token is missing, the name is not
            ``owner/repo`` or the folder leaves the repository

    Returns:
        RepositorySettings | None: The settings, or None when no repository is named (the sync is off)
    """
    repository: str = environ.get(BestPracticeRepositoryEnv.REPOSITORY.value, '').strip()

    if not repository:
        return None

    token: str = environ.get(BestPracticeRepositoryEnv.TOKEN.value, '').strip()

    if not token:
        raise BestPracticeRepositoryError(TOKEN_MISSING.format(
            token_env=BestPracticeRepositoryEnv.TOKEN.value, repository_env=BestPracticeRepositoryEnv.REPOSITORY.value,
        ))

    if not re.fullmatch(REPOSITORY_NAME_PATTERN, repository):
        raise BestPracticeRepositoryError(REPOSITORY_NAME_INVALID.format(
            repository_env=BestPracticeRepositoryEnv.REPOSITORY.value, repository=repository,
        ))

    raw_path: str = environ.get(BestPracticeRepositoryEnv.PATH.value, '').strip().strip('/')
    path: PurePosixPath = PurePosixPath(raw_path)

    if PARENT_SEGMENT in path.parts:
        raise BestPracticeRepositoryError(REPOSITORY_PATH_INVALID.format(
            path_env=BestPracticeRepositoryEnv.PATH.value, path=raw_path,
        ))

    return RepositorySettings(
        repository=repository,
        token=token,
        ref=environ.get(BestPracticeRepositoryEnv.REF.value, '').strip(),
        path=path,
        api_url=api_url,
    )


def archive_url(settings: RepositorySettings) -> str:
    """
    The URL of the repository's archive: the ref's tree, or the default branch's when no ref is set

    Args:
        settings (RepositorySettings): The repository

    Returns:
        str: The URL
    """
    if not settings.ref:
        return settings.api_url + TARBALL_PATH.format(repository=settings.repository)

    return settings.api_url + TARBALL_REF_PATH.format(repository=settings.repository, ref=quote(settings.ref, safe='/'))


def hide_query_strings(text: str) -> str:
    """
    Removes every URL query string from a text - GitHub redirects the download to a URL carrying a temporary token

    Args:
        text (str): A message that may name a URL

    Returns:
        str: The message without query strings
    """
    return re.sub(QUERY_STRING_PATTERN, HIDDEN_QUERY, text)


def read_limited(response: requests.Response, repository: str) -> bytes:
    """
    Reads a streamed answer up to ``MAX_ARCHIVE_BYTES``

    Args:
        response (requests.Response): The streamed answer
        repository (str): The repository, for the message

    Raises:
        BestPracticeRepositoryError: When the answer is larger than the limit

    Returns:
        bytes: The answer's body
    """
    body: bytearray = bytearray()

    for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_BYTES):
        body.extend(chunk)

        if len(body) > MAX_ARCHIVE_BYTES:
            raise BestPracticeRepositoryError(ARCHIVE_TOO_LARGE.format(repository=repository, limit=MAX_ARCHIVE_BYTES))

    return bytes(body)


def download_repository_archive(settings: RepositorySettings) -> bytes:
    """
    Downloads the repository's archive (a gzip-compressed tar) through the GitHub REST API

    Args:
        settings (RepositorySettings): The repository

    Raises:
        BestPracticeRepositoryError: When GitHub cannot be reached, answers another status than 200 or the archive is
            larger than ``MAX_ARCHIVE_BYTES``

    Returns:
        bytes: The archive
    """
    headers: dict[str, str] = {
        GitHubRequestHeader.ACCEPT.value: GITHUB_ACCEPT,
        GitHubRequestHeader.AUTHORIZATION.value: BEARER_TOKEN.format(token=settings.token),
        GitHubRequestHeader.API_VERSION.value: GITHUB_API_VERSION,
    }

    try:
        with requests.get(archive_url(settings), headers=headers, stream=True,
                          timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS)) as response:
            if response.status_code != HTTPStatus.OK:
                raise BestPracticeRepositoryError(DOWNLOAD_REFUSED.format(
                    repository=settings.repository, status=response.status_code,
                ))

            return read_limited(response, settings.repository)
    except RequestException as err:
        raise BestPracticeRepositoryError(DOWNLOAD_FAILED.format(
            repository=settings.repository, detail=hide_query_strings(f'{type(err).__name__}: {err}'),
        )) from err


def path_in_repository(member_name: str) -> PurePosixPath | None:
    """
    A file's path inside the repository - the archive puts every file under one ``{owner}-{repo}-{sha}`` folder

    Args:
        member_name (str): The file's name in the archive

    Returns:
        PurePosixPath | None: The path below that folder, or None for the folder itself
    """
    parts: tuple[str, ...] = PurePosixPath(member_name).parts[1:]

    return PurePosixPath(*parts) if parts else None


def extract_model_files(archive: bytes, settings: RepositorySettings) -> dict[str, bytes]:
    """
    The model files of the archive: every regular ``*.json`` file directly in the configured folder

    Nothing is extracted to disk here - the files are read into memory by name. Links are skipped, and so is a file
    larger than ``MAX_MODEL_FILE_BYTES`` (logged at WARNING)

    Args:
        archive (bytes): The downloaded archive
        settings (RepositorySettings): The repository and its folder

    Raises:
        BestPracticeRepositoryError: When the archive cannot be read

    Returns:
        dict[str, bytes]: File name -> content
    """
    files: dict[str, bytes] = {}

    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode=ARCHIVE_READ_MODE) as tar:
            for member in tar.getmembers():
                path: PurePosixPath | None = path_in_repository(member.name)

                if not member.isfile() or path is None or path.parent != settings.path:
                    continue

                if not path.name.endswith(MODEL_FILE_SUFFIX):
                    continue

                if member.size > MAX_MODEL_FILE_BYTES:
                    LOGGER.warning(MODEL_FILE_TOO_LARGE, path.name, MAX_MODEL_FILE_BYTES)
                    continue

                content = tar.extractfile(member)

                if content is not None:
                    files[path.name] = content.read()
    except (tarfile.TarError, OSError, EOFError, zlib.error) as err:
        raise BestPracticeRepositoryError(ARCHIVE_UNREADABLE.format(
            repository=settings.repository, detail=err,
        )) from err

    return files


def write_file_atomically(path: Path, content: bytes) -> None:
    """
    Writes a file under a name the catalogue ignores first, then moves it into place - never half a model

    Args:
        path (Path): The file
        content (bytes): Its content
    """
    partial: Path = path.with_name(PARTIAL_FILE_NAME.format(file_name=path.name))
    partial.write_bytes(content)
    os.replace(partial, path)


def mirror_model_files(folder: Path, files: dict[str, bytes]) -> RepositorySyncReport:
    """
    Makes the folder's model files exactly the repository's: adds new ones, rewrites changed ones, removes the rest

    Only the folder's ``*.json`` files are its model files; anything else in it is left alone

    Args:
        folder (Path): The repository folder; created when missing
        files (dict[str, bytes]): File name -> content, as the repository holds them

    Raises:
        BestPracticeRepositoryError: When the folder cannot be written

    Returns:
        RepositorySyncReport: What changed
    """
    added: list[str] = []
    updated: list[str] = []
    unchanged: list[str] = []

    try:
        folder.mkdir(parents=True, exist_ok=True)
        existing: set[str] = {path.name for path in find_model_files(folder)}
        removed: list[str] = sorted(existing - set(files))

        for file_name in removed:
            (folder / file_name).unlink()

        for file_name in sorted(files):
            target: Path = folder / file_name

            if file_name in existing and target.read_bytes() == files[file_name]:
                unchanged.append(file_name)
                continue

            write_file_atomically(target, files[file_name])
            (updated if file_name in existing else added).append(file_name)
    except OSError as err:
        raise BestPracticeRepositoryError(FOLDER_NOT_WRITABLE.format(folder=folder, detail=err)) from err

    return RepositorySyncReport(tuple(added), tuple(updated), tuple(removed), tuple(unchanged))


def log_model_problems(folder: Path) -> None:
    """
    Logs at ERROR every repository model whose own references do not resolve - what CI fails for a bundled model

    A model that cannot be offered at all is logged by the catalogue while loading

    Args:
        folder (Path): The repository folder
    """
    for model in load_models(folder):
        problems: list[str] = find_preview_problems(model.document, model.meta)

        if problems:
            LOGGER.error(MODEL_HAS_PROBLEMS, model.model_id, '; '.join(problems))


def sync_best_practice_repository(folder: Path | None = None, environ: Mapping[str, str] | None = None,
                                  api_url: str = GITHUB_API_URL) -> RepositorySyncReport | None:
    """
    Syncs the configured repository's models into the repository folder - never raises for a failed sync

    Args:
        folder (Path | None): The repository folder. Defaults to ``repository_models_folder()``
        environ (Mapping[str, str] | None): The environment variables. Defaults to ``os.environ``
        api_url (str): The GitHub REST API the archive is downloaded from

    Returns:
        RepositorySyncReport | None: What changed, or None when no repository is configured or the sync failed
            (logged at INFO / WARNING)
    """
    target: Path = repository_models_folder() if folder is None else folder

    try:
        settings: RepositorySettings | None = read_repository_settings(
            os.environ if environ is None else environ, api_url,
        )

        if settings is None:
            LOGGER.info(SYNC_NOT_CONFIGURED, BestPracticeRepositoryEnv.REPOSITORY.value)
            return None

        files: dict[str, bytes] = extract_model_files(download_repository_archive(settings), settings)
        report: RepositorySyncReport = mirror_model_files(target, files)
    except BestPracticeRepositoryError as err:
        LOGGER.warning(SYNC_FAILED, err)
        return None

    LOGGER.info(SYNC_DONE, len(files), settings.repository, list(report.added), list(report.updated),
                list(report.removed))
    log_model_problems(target)

    return report
