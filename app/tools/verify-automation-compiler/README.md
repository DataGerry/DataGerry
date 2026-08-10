# Automation compiler verification

Compares the output of `AutomationCompilerService` against the OpenCelium connection payloads
captured from a running installation, which are the ground truth for what the compiler must produce.

Unlike `ng test` this needs no browser, so it also runs in a bare container.

## Running

From the `app/` directory:

```bash
node tools/verify-automation-compiler/run.mjs
```

Expected output: `UPDATE (PUT /connections): 0 difference(s)` and `PASS`. The CREATE comparison
reports three known differences, listed as accepted in `verify.ts` - the two captures were taken
from differently named connections, and only the update capture carries a description.

## Reference payloads

By default the script reads them from the repository root. Both hold a flat connection; they are
bound by shape, not by name, because only the update body carries `connectionId`:

- `OpenCelium_Connection_Update_Request.json` - body of `PUT /rest/open_celium/connections/:id`
- `OpenCelium_Connection_Create_Request.json` - the `connection` half of `POST /rest/open_celium/schedulers`

Point it at other captures with `--create=<path> --update=<path>` to onboard a new target system:
capture a working connection from the OpenCelium editor, then make the compiler reproduce it.

## How the fixtures are derived

The compiler needs the connectors and their invoker definitions, and the automation to compile.
Both are recovered from the update capture rather than hand-written, so the fixtures cannot drift
away from the payload they are checked against:

- **The automation** is decoded from the connection description, where the wizard stores its
  business model as a `dg-automation` block. The capture must therefore come from a connection the
  wizard saved; one built in the OpenCelium editor carries no such block and is rejected with a
  message saying so.
- **The connectors** come from each method's `connector`, and their **invokers** from the methods
  themselves - a connection no longer carries invoker definitions. Recovering an operation means
  undoing what the compiler wrote into it: a mapped field holds a colour reference where the invoker
  holds an empty string, and the read endpoint has gained the filter and limit the compiler appends.

A consequence worth knowing: because the invoker is recovered from the very method it is used to
rebuild, this check confirms that the compiler is *self-consistent* with the capture. It cannot
catch a mistake in how an invoker's own schema is read - that is what `target-catalog.service` and
its specs cover.
