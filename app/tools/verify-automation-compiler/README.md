# Automation compiler verification

Compares the output of `AutomationCompilerService` against the OpenCelium connection payloads
captured from a running installation, which are the ground truth for what the compiler must produce.

Unlike `ng test` this needs no browser, so it also runs in a bare container.

## Running

From the `app/` directory:

```bash
node tools/verify-automation-compiler/run.mjs
```

Expected output: `CREATE (POST /schedulers): 0 difference(s)`. The UPDATE comparison reports three
known differences, listed as accepted in `run.mjs` - the two capture files carry different titles,
and the update capture sends `label: null` on the target method where the create capture omits the
key entirely.

## Reference payloads

By default the script reads them from the repository root:

- `OpenCelium_Connection_Update_Request.json` - contains `{ connection, scheduler }`, i.e. the body
  of `POST /rest/open_celium/schedulers`
- `OpenCelium_Connection_Create_Request.json` - contains the flat connection, i.e. the body of
  `PUT /rest/open_celium/connections/:id`

The file names are swapped relative to their contents; the script binds them by shape, not by name.
Point it at other captures with `--create=<path> --update=<path>` to onboard a new target system:
capture a working connection from the OpenCelium editor, then make the compiler reproduce it.
