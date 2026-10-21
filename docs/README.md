# DataGerry documentation

The user documentation, built with Sphinx and published at docs.datagerry.com.

## Build

```bash
pip install -r docs/source/requirements.txt
cd docs
make html
```

The HTML ends up in `docs/_build/html`. A clean build has no warnings — keep it that way.

## Layout

The structure follows the OpenCelium documentation (docs.opencelium.io), organised by what the
reader is trying to do:

| Directory     | Holds                                                               |
|---------------|---------------------------------------------------------------------|
| `start/`      | Introduction, cloud vs. self-hosted, quick starts, tutorial, what's new |
| `concepts/`   | The model, explained once                                           |
| `guides/`     | Task-oriented how-tos, grouped by area in `index.rst`               |
| `reference/`  | Lookup tables: field types, rights, REST API, CSV formats, changelog |
| `cloud/`      | Service Portal, cloud users, API keys (cloud only)                  |
| `operations/` | Install, configure, update, back up a self-hosted installation      |
| `about/`      | Contact, license                                                    |
| `img/`        | All screenshots, one folder per topic                               |

Each fact has one home; other pages link to it.

## Cloud and self-hosted

Mark what exists in only one edition with the badges `|cloud|`, `|selfhosted|` and `|licensed|`
(defined in `conf.py`). Where behaviour differs, use one callout instead of duplicating pages:

```rst
.. admonition:: Cloud and self-hosted
   :class: edition

   In the cloud ... . On a self-hosted installation ... .
```

The full comparison lives in `start/editions.rst`.

## Moved pages

Old URLs are kept alive by the `redirects` table in `conf.py`. When you move or rename a page, add
the old docname there.

## Screenshots

`docs/_tools/screenshots/` contains the Playwright script that regenerates the screenshots from a
running instance; see its README.

## Changelog

`reference/changelog.rst` includes `CHANGELOG.md` from the repository root — edit that file only.
