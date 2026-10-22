# Best-practice data models

The start assistant offers every model in this folder on an empty installation; the user picks **one**, and the
administrator account applies it. Read by `cmdb/framework/configuration_transfer/best_practice_catalogue.py`; the file
contract is in `best_practice_constants.py`; the rules are in `workflows/start-assistant.md`.

A model is **two files** in this folder:

| File | Content | Written by |
|---|---|---|
| `<model_id>.json` | the data model, exported from DataGerry, **unchanged** | DataGerry's export |
| `<model_id>.meta.json` | what the start assistant shows about it | you, by hand |

The backend works out everything else from the model file: the counts, the type tree, the reference targets and the
licence the model needs.

**An example** is in [`example/`](example/): `example_contacts.json` - a real export of a tiny model (the types
*Company* and *Contact person*, where a contact person references its company; the category *Contacts*; the relation
*works_for*) - and its `example_contacts.meta.json`. It is **not offered** by the assistant: only the files directly in
this folder are models, a subfolder is ignored. The bundle test applies it like a real model, so it stays valid as
the format evolves. To try the format, copy both files up into this folder under a new id.

---

## 1. Prepare a design installation

- Use a separate DataGerry instance (local or a test VM), **never production**. Its types, categories, relations and
  user section templates become the model, so start from an empty data model.
- Use the **same or an older DataGerry version** than the release the model ships in. An older export is upgraded
  automatically when it is applied; a newer one is refused.

## 2. Build the model

Create, in that instance:

- **Categories** - their **name** (not the label) is what the description file refers to later.
- **Types** with their sections and fields - reference fields may only target types inside this model.
- **Relations** between the types.
- **User section templates**, if the types use them.

Keep in mind:

| What | Effect |
|---|---|
| **Objects** | not exported - a model is only the data model |
| **Type ACLs** | reset to the default when applied |
| **Author** | becomes the administrator who applies the model |
| **Supernet, Subnet, VLAN, Rack, Cable, or a type with ports** | the model needs the **IPAM** licence; installations without it cannot apply the model |

## 3. Export it

**In the UI:** *Export → Export Complete Data Model*.

**Or via the API**, as the administrator, with a token from the login:

```bash
TOKEN=$(curl -s -X POST http://localhost:4000/rest/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"user_name":"admin","password":"admin"}' | jq -r .token)

curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:4000/rest/configuration_transfer/export -o export.json
```

Both produce one JSON file with `format_version`, `db_version`, `exported_at` and `components`. **Do not edit it by
hand** - if something is wrong, fix it in the design instance and export again.

## 4. Choose the id and add the model file

- The id is the file name: **lowercase letters, digits and `_` only** - e.g. `it_infrastructure`,
  `workplace_management`. A client names a model by that id alone, never by a path.
- Copy the export into this folder as `<model_id>.json`.

## 5. Write the description file

Create `<model_id>.meta.json` next to the model file:

```json
{
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
| `suited_for` | the "Suited for" list | list of texts, may be empty |
| `profiles` | the "Built from assistant profiles" chips | list of texts, may be empty |
| `category_descriptions` | the line above each category's types | keys = category **names** from the model file |
| `order` | the card order (smaller first; ties sorted by id) | whole number of 0 or more |

**Every key is required and no other key is allowed**, so a misspelled key is caught. The category names are in the
exported file under `components.categories.items[*].name`.

## 6. Check it locally

With MongoDB running (see `CLAUDE.md`):

```bash
pytest tests/unit/framework/configuration_transfer/test_best_practice_catalogue.py \
       tests/unit/framework/configuration_transfer/test_best_practice_preview.py \
       tests/integration/framework/test_integration_best_practice_bundles.py
```

They check that:

- both files are readable and valid, and the description file has exactly the right keys;
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

- Commit both files together; CI runs the same checks as step 6.
- Nothing else is needed: the `Makefile`'s `bin` target already bundles this folder into the binary (`--add-data`),
  and a test fails without that line.
- In the release the start assistant lists the model on every empty installation, in cloud mode too. Only the
  administrator account (public_id 1) applies it, and only on an empty system - so an installation gets one model.

---

## Updating or removing a model

- **Update:** change it in the design instance, export again and replace `<model_id>.json`. Keep the id, so it stays
  the same model; adjust `<model_id>.meta.json` when categories were renamed. Installations that already applied the
  old version are not changed - a model is applied once.
- **Remove:** delete both files. A description file left without its model file is logged at ERROR and fails the
  tests.

## Common mistakes

| Symptom | Cause |
|---|---|
| the model is missing from the list, an ERROR in the log | the description file is missing or invalid, the id is misspelled, or the model file is not an unchanged export |
| test: "describes the category 'X', which the model does not hold" | `category_descriptions` uses a category **label** instead of its **name** |
| test: "targets the type ID N, which the model does not hold" | a reference field points at a type outside the model |
| the card shows `applicable: false` | the model holds IPAM, Rack or Cable types, or ports, and the installation is not licensed for IPAM |
| applying is refused: the file is newer | exported from a newer DataGerry than the release |
