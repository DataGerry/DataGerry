# Documentation screenshots

`capture.mjs` regenerates the DataGerry 3.3 screenshots in `docs/source/img/`
from a running DataGerry instance with sample data, so they can be refreshed
after a UI change instead of being re-shot by hand.

```sh
npm i playwright-core
npx playwright-core install chromium        # or point CHROMIUM at a Chrome binary

DG_BASE=https://cloud.example.com \
DG_USER=admin@example.com DG_PASS='...' \
DG_SUBSCRIPTION=Medium \
node capture.mjs                             # every shot -> ./out

ONLY=racks,ports node capture.mjs            # some groups (or single steps: ONLY=ports/table)
OUT=/tmp/shots node capture.mjs              # other output directory
STATE=/tmp/dg-login.json node capture.mjs    # cache the login between runs
```

| Variable          | Meaning |
|-------------------|---------|
| `DG_BASE`         | Frontend URL of the instance (no trailing slash). |
| `DG_USER`         | Login: a user name, or the e-mail address on a cloud instance. |
| `DG_PASS`         | Password. Never commit it; pass it from the environment. |
| `DG_SUBSCRIPTION` | Cloud only: the subscription to pick after login. |
| `DG_IDS`          | JSON that overrides the public IDs of the sample objects, e.g. `{"rack":12}`. |
| `CHROMIUM`        | Path to the Chromium/Chrome binary. |

The output has the same layout as `docs/source/img/`, so

```sh
cp -r out/* ../../source/img/
```

puts every file in place. Look at every image before committing it.

## Safety

The script is read-only. A route guard aborts every request that is not
`GET`, `HEAD` or `OPTIONS` (except the login) and prints it as `BLOCKED`, so even
an accidental click on *Save* cannot change the instance. Forms and dialogs are
only opened, sometimes filled in for the picture, and then cancelled; a type
builder or bulk change is never saved.

## Sample data the shots expect

The defaults in the `ID` block at the top of `capture.mjs` match the *Medium*
sample subscription on the becon test system (a German "Nordlicht Logistik"
data set). On another instance, pass `DG_IDS` or edit the block:

* `typeServer` — a type with several sections (type builder steps, ACL);
  `typeCompany` — a type with a custom multi data section; `typeClient` — a type
  with 10+ objects (search, filter, bulk change); `typeRouter`, `typeSwitch`.
* `server` — an object with relations, a location and several interface rows.
* `rack` — a rack with mounts, a reservation and blockers.
* `switch` — a standard device with cabled ports; `patchPanel` — a patch panel;
  `portless` — an object whose type has the Ports section (opens the Add ports
  assistant).
* `relation`, `relationTab` — a relation type and its tab label on `server`.
* ISMS: risks, controls with assignments, a risk assessment (`ismsAssessment`).

## Steps that skip themselves

Some shots need content the sample data may not have. The step then fails with
a message and leaves the existing image alone:

* **Start Assistant** (`dg_assistant/wizard`) — only offered on a new, empty
  workspace; elsewhere the dialog says *You're already set up*.
* **User form** (`users/create`) — read-only in the cloud, where users are
  managed in the Service Portal. Shoot it on a self-hosted instance.
* **Risk matrix / risk assessments** (`isms/configure_risk_matrix`,
  `isms/risk_assessment_open`, `isms/risk_assessment_form`) — need a fully
  configured ISMS (every matrix cell assigned to a risk class).
* **Reports, webhooks, automations, connectors, document templates** — need at
  least one entry each. On the test system, webhooks exist only in the *small*
  subscription: `DG_SUBSCRIPTION=small ONLY=webhooks/overview node capture.mjs`.

## Not automated

* `img/license_management/*`, `img/authentification/*` — self-hosted only.
* `img/service_portal/*` — a different application.
* `img/ipam/*` — annotated by hand (callouts); re-shoot manually if the IPAM UI
  changes.
* `objects/objects_bulk_changed.png` — shows the result of a saved bulk change.

## Things that will bite you

* **Tall elements** are shot by growing the viewport to the document height
  instead of scrolling; otherwise the fixed top bar covers the top of the image.
  Canvas views (CI Explorer, Cabling View) are shot full screen instead, because
  their canvas grows with the viewport.
* **The sidebar is collapsed** (`wide()`) for wide tables so the columns do not
  wrap. The state lives in the browser only.
* **Type builder drag and drop** needs `dragTo(..., { force: true })` onto the
  `.empty-section` drop zone; later fields are dropped on the lower edge of the
  last field, or they land above it.
* **Leaving an edit page** can raise *Do you want to save the changes …?*. Never
  answer it with *Save*; the next navigation discards it.
* **Personal data**: object lists show the author's display name. Check every
  image before committing; mask or crop anything that is not sample data.
