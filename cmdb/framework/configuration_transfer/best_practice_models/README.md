# Best-practice data models

The start assistant offers every model in this folder on an empty installation; the user picks **one**, and a user
holding the master right `base.*` applies it. Read by `cmdb/framework/configuration_transfer/best_practice_catalogue.py`;
the file contract is in `best_practice_constants.py`; the rules are in `workflows/start-assistant.md`.

A model is **one file** in this folder: `<model_id>.json`, an export from DataGerry. It has four parts:

| Part | Content | Written by |
|---|---|---|
| `format_version`, `db_version`, `exported_at` | the file's envelope | DataGerry's export |
| `information` | the export's name and description, the DataGerry version, the number of entries per component | the export - name and description from the person exporting |
| `meta` | what the start assistant shows about the model | the export writes it **empty**; you fill it in by hand |
| `components` | the data model itself | DataGerry's export |

Only `meta` is edited by hand. The backend works out everything else from the file: the counts, the type tree, the
reference targets and the licence the model needs.

**An example** is in [`example/`](example/): `example_contacts.json` - a real export of a tiny model (the types
*Company* and *Contact person*, where a contact person references its company; the category *Contacts*; the relation
*works_for*) with its `meta` filled in. It is **not offered** by the assistant: only the files directly in this folder
are models, a subfolder is ignored. The bundle test applies it like a real model, so it stays valid as the format
evolves. To try the format, copy it up into this folder under a new id.

---

## 1. Prepare a design installation

- Use a separate DataGerry instance (local or a test VM), **never production**. Its types, categories, relations and
  user section templates become the model, so start from an empty data model.
- Use the **same or an older DataGerry version** than the release the model ships in. An older export is upgraded
  automatically when it is applied; a newer one is refused.

## 2. Build the model

Create, in that instance:

- **Categories** - their **name** (not the label) is what the `meta` section refers to later.
- **Types** with their sections and fields - reference fields may only target types inside this model.
- **Relations** between the types.
- **User section templates**, if the types use them.

Keep in mind:

| What | Effect |
|---|---|
| **Objects** | not exported - a model is only the data model |
| **Type ACLs** | reset to the default when applied |
| **Author** | becomes the user who applies the model |
| **Supernet, Subnet, VLAN, Rack, Cable, or a type with ports** | the model needs the **IPAM** licence; installations without it cannot apply the model |

## 3. Export it

**In the UI:** *Export → Export Complete Data Model*. The export needs a name; a description and a filename are
optional.

**Or via the API**, as a user holding `base.system.export`, with a token from the login:

```bash
TOKEN=$(curl -s -X POST http://localhost:4000/rest/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"user_name":"admin","password":"admin"}' | jq -r .token)

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"IT Infrastructure","description":"Every asset class in one model"}' \
  http://localhost:4000/rest/configuration_transfer/export -o export.json
```

| Body key | Rule |
|---|---|
| `name` | required, non-blank, at most 255 characters - written to `information.name` |
| `description` | optional, at most 4000 characters - written to `information.description` (`""` when left out) |
| `filename` | optional, at most 255 characters - the download's name; path separators and control characters are removed and `.json` is added. Left out or nothing usable left: a generated name |

Both produce one JSON file. **Edit nothing but `meta`** - if something else is wrong, fix it in the design instance
and export again. A hand edit elsewhere is caught: the `information` counts must match the entries.

## 4. Choose the id and add the model file

- The id is the file name: **lowercase letters, digits and `_` only** - e.g. `it_infrastructure`,
  `workplace_management`. A client names a model by that id alone, never by a path.
- Copy the export into this folder as `<model_id>.json`.

## 5. Fill in the `meta` section

The export writes `meta` with every value empty and one entry per exported category already in
`category_descriptions`:

```json
"meta": {
    "title": "",
    "badge": "",
    "summary": "",
    "description": "",
    "suited_for": [],
    "profiles": [],
    "category_descriptions": {"contact": "", "location": ""},
    "order": null
}
```

Fill it in:

```json
"meta": {
    "title": "IT Infrastructure",
    "badge": "Complete CMDB",
    "summary": "Every asset class from workplace to data center in one connected model.",
    "description": "A full CMDB for organizations that want to document their entire IT landscape.",
    "suited_for": ["IT departments of mid-sized companies", "Service providers documenting customer environments"],
    "profiles": ["user-management", "location", "server-management", "network-infrastructure"],
    "category_descriptions": {
        "contact": "People and organizations that use or own assets",
        "location": "Location tree from country down to room"
    },
    "order": 10
}
```

| Key | Shown on the screens as | Rule |
|---|---|---|
| `title` | the card's and the details' heading | non-blank text |
| `badge` | the chip above the title ("Complete CMDB") | non-blank text |
| `summary` | the card's text | non-blank text |
| `description` | the details' long text (line breaks allowed) | non-blank text |
| `suited_for` | the "Suited for" list | list of non-blank texts, may be empty |
| `profiles` | the "Built from assistant profiles" chips | list of non-blank texts, may be empty |
| `category_descriptions` | the line above each category's types | keys = category **names** from the model; each value non-blank. Remove an entry rather than leave it empty |
| `order` | the card order (smaller first; ties sorted by id) | whole number of 0 or more |

**Every key is required and no other key is allowed**, so a misspelled key is caught. A model whose `meta` is not
filled in completely is not offered. The category names are in the file under `components.categories.items[*].name`.

`information` stays as exported: it describes the export (who called it what, which DataGerry version wrote it, how
many entries it holds) and is what the import preview shows; `meta` is what the start assistant shows.

## 6. Check it locally

With MongoDB running (see `CLAUDE.md`):

```bash
pytest tests/unit/framework/configuration_transfer/test_best_practice_catalogue.py \
       tests/unit/framework/configuration_transfer/test_best_practice_preview.py \
       tests/integration/framework/test_integration_best_practice_bundles.py
```

They check that:

- the file is readable and a valid transfer file, and its `meta` has exactly the right keys, every value filled in;
- every reference resolves inside the file - field targets, reference sections, relation sides, category entries and
  the category descriptions;
- the model **applies into a freshly reset database at the newest version**, and what is created matches the counts
  the assistant shows.

A failing test names the problem, e.g. *"the field 'employer' of the type 'customer_user' targets the type ID 41,
which the model does not hold"*.

**Optional - look at it the way users will.** Start the backend (`python -m cmdb -s -c ./etc/cmdb.conf`) and call the
read routes as a user with the assistant's rights (`base.framework.type.add` and `base.framework.category.add`):

```bash
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4000/rest/start_assistant/models | jq
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:4000/rest/start_assistant/models/<model_id> | jq
```

Check the card (counts, category chips, `required_features`, `applicable`) and the type tree.

## 7. Ship it

- Commit the file; CI runs the same checks as step 6.
- Nothing else is needed: the `Makefile`'s `bin` target already bundles this folder into the binary (`--add-data`),
  and a test fails without that line.
- In the release the start assistant lists the model on every empty installation, in cloud mode too. Only a user
  holding the master right `base.*` applies it, and only on an empty system - so an installation gets one model.

---

## Updating or removing a model

- **Update:** change it in the design instance, export again, copy your filled-in `meta` into the new export and
  replace `<model_id>.json`. Keep the id, so it stays the same model; adjust `category_descriptions` when categories
  were renamed. Installations that already applied the old version are not changed - a model is applied once.
- **Remove:** delete the file.

## Common mistakes

| Symptom | Cause |
|---|---|
| the model is missing from the list, an ERROR in the log | `meta` is not filled in completely, the id is misspelled, or the file is not an export (or was edited outside `meta`) |
| the log says "its meta section is not filled in completely" | a text left `""`, an empty `category_descriptions` value, or `order` still `null` |
| the log names an `information` count | an entry was added or removed by hand - export again instead |
| test: "the meta section describes the category 'X', which the model does not hold" | `category_descriptions` uses a category **label** instead of its **name** |
| test: "targets the type ID N, which the model does not hold" | a reference field points at a type outside the model |
| the card shows `applicable: false` | the model holds IPAM, Rack or Cable types, or ports, and the installation is not licensed for IPAM |
| applying is refused: the file is newer | exported from a newer DataGerry than the release |
