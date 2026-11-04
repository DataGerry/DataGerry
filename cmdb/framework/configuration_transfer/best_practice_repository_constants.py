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
The settings, limits and messages of the best-practice repository sync (hosted cloud only)

A private GitHub repository named by environment variables holds best-practice model files. At startup its archive is
downloaded once and the ``*.json`` files of the configured folder are mirrored into the ``repository`` subfolder of the
models folder (``best_practice_repository``)
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class BestPracticeRepositoryEnv(BaseStrEnum):
    """
    The environment variables that configure the repository sync

    Attributes:
        REPOSITORY: ``owner/repo`` of the GitHub repository; unset or empty turns the sync off
        TOKEN: A GitHub token that may read the repository's contents; required when REPOSITORY is set
        REF: The branch, tag or commit to read; unset or empty reads the repository's default branch
        PATH: The folder inside the repository that holds the model files; unset or empty is the root
    """
    REPOSITORY = 'DG_BEST_PRACTICE_REPO'
    TOKEN = 'DG_BEST_PRACTICE_REPO_TOKEN'
    REF = 'DG_BEST_PRACTICE_REPO_REF'
    PATH = 'DG_BEST_PRACTICE_REPO_PATH'


# The GitHub REST API the archive is downloaded from
GITHUB_API_URL: str = 'https://api.github.com'
# The archive of a repository: the default branch without a ref, the ref's tree with one
TARBALL_PATH: str = '/repos/{repository}/tarball'
TARBALL_REF_PATH: str = '/repos/{repository}/tarball/{ref}'
# What a GitHub repository name may be spelled as: owner/repo
REPOSITORY_NAME_PATTERN: str = r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+'
# The parent-folder path segment, refused in the repository folder
PARENT_SEGMENT: str = '..'


class GitHubRequestHeader(BaseStrEnum):
    """The headers of the archive request"""
    ACCEPT = 'Accept'
    AUTHORIZATION = 'Authorization'
    API_VERSION = 'X-GitHub-Api-Version'


GITHUB_ACCEPT: str = 'application/vnd.github+json'
GITHUB_API_VERSION: str = '2022-11-28'
BEARER_TOKEN: str = 'Bearer {token}'

# How long the download may take: connecting, and the wait for each part of the answer (seconds)
CONNECT_TIMEOUT_SECONDS: int = 10
READ_TIMEOUT_SECONDS: int = 30
# The download is read in parts of this size (bytes)
DOWNLOAD_CHUNK_BYTES: int = 64 * 1024
# The largest archive downloaded, and the largest model file taken from it (bytes)
MAX_ARCHIVE_BYTES: int = 64 * 1024 * 1024
MAX_MODEL_FILE_BYTES: int = 16 * 1024 * 1024
# How the downloaded archive is opened: a gzip-compressed tar
ARCHIVE_READ_MODE: str = 'r:gz'
# A model file is written under this name first and then moved into place; it never ends with '.json'
PARTIAL_FILE_NAME: str = '.{file_name}.partial'

# Why the sync did not run or failed - logged, never answered to a client. The token is never part of a message
TOKEN_MISSING: str = "{token_env} is not set, but {repository_env} is"
REPOSITORY_NAME_INVALID: str = "{repository_env} must be 'owner/repo', not '{repository}'"
REPOSITORY_PATH_INVALID: str = "{path_env} may not leave the repository: '{path}'"
DOWNLOAD_FAILED: str = "the archive of '{repository}' could not be downloaded: {detail}"
DOWNLOAD_REFUSED: str = "GitHub answered the archive of '{repository}' with status {status}"
ARCHIVE_TOO_LARGE: str = "the archive of '{repository}' is larger than {limit} bytes"
ARCHIVE_UNREADABLE: str = "the archive of '{repository}' could not be read: {detail}"
FOLDER_NOT_WRITABLE: str = "the folder '{folder}' could not be written: {detail}"

SYNC_FAILED: str = "[best_practice_repository] The best-practice repository was not synced: %s"
SYNC_NOT_CONFIGURED: str = "[best_practice_repository] No best-practice repository is configured (%s is not set)"
SYNC_DONE: str = (
    "[best_practice_repository] Synced %d best-practice model file(s) from '%s': added %s, updated %s, removed %s"
)
MODEL_FILE_TOO_LARGE: str = (
    "[best_practice_repository] The model file '%s' is left out: it is larger than %d bytes"
)
MODEL_HAS_PROBLEMS: str = "[best_practice_repository] The repository's model '%s' is inconsistent: %s"
# A URL query string in a message, and what replaces it - a redirect's URL carries a temporary download token
QUERY_STRING_PATTERN: str = r"\?[^\s'\")]*"
HIDDEN_QUERY: str = '?<hidden>'
