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

## Checking against a live OpenCelium

`live-check.ts` answers a different question than the capture comparison: not "does the
compiler still produce what it produced before", but "does what it produces resolve against
the interface descriptions this installation actually has". It caught nothing the day it was
written, which is the point — it is the check that would have caught a renamed operation or a
filter that moved.

It reads three files from a directory you point it at, so it needs no credentials of its own:

```bash
OC=http://<host>:<port>
TOKEN=$(curl -s -D - -o /dev/null -X POST "$OC/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"<email>","password":"<password>"}' \
  | grep -i '^authorization:' | sed 's/^[Aa]uthorization: //' | tr -d '\r')

mkdir -p /tmp/oc && cd /tmp/oc
for f in invoker/all connector/all; do
  curl -s "$OC/$f" -H "Authorization: $TOKEN" -o "$(basename $(dirname $f))s.json"
done
```

Then, from `app/`:

```bash
node_modules/esbuild/bin/esbuild tools/verify-automation-compiler/live-check.ts \
  --bundle --platform=node --format=cjs \
  --alias:@angular/core=tools/verify-automation-compiler/stub-angular-core.js \
  --outfile=/tmp/oc/live.cjs --log-level=error
DG_DATA_DIR=/tmp/oc node /tmp/oc/live.cjs
```

It prints one line per resolution step and exits non-zero if any of them failed. Drop a
`connection<id>.json` into the same directory to compare the compiled payload against a
connection built by hand in the OpenCelium editor - the index trees should match exactly.

The credentials belong in the shell, not in a file next to this one, and the token is worth
discarding when you are done.

## Checking that OpenCelium accepts what is produced

A third question, and the one neither check above can answer: the capture comparison asks whether
the compiler still produces what it produced before, `live-check` whether that resolves against an
installation's interface descriptions - and only OpenCelium can say whether it takes the payload.

Which matters for the parts no capture covers. A shape derived from a captured connection is
checked by construction; a shape that had to be worked out - a free HTTP request, a condition of
the user's own, a loop over a list an answer holds - is checked by nothing until it is saved.

`live-save.ts` compiles an automation holding one of each, creates it, reads it back, prints the
execution tree that came home, and deletes it. Nothing is executed: acceptance is the question, and
running an automation would write into the target system.

```bash
node_modules/esbuild/bin/esbuild tools/verify-automation-compiler/live-save.ts \
  --bundle --platform=node --format=cjs \
  --alias:@angular/core=tools/verify-automation-compiler/stub-angular-core.js \
  --outfile=/tmp/oc/live-save.cjs --log-level=error
OC_BASE=$OC OC_TOKEN="$TOKEN" DG_DATA_DIR=/tmp/oc node /tmp/oc/live-save.cjs
```

`OC_DRY=1` writes the payload to `$DG_DATA_DIR/live-save-payload.json` and sends nothing, which is
what to reach for when a server rejects one.

It talks to OpenCelium directly - `POST /connection`, not the `/rest/open_celium/schedulers` the
wizard uses, which is DataGerry's own path in front of it. Only the connection half is sent; the
scheduler beside it decides when an automation runs, and this is about what it would run.

## Checking that the engine does what was compiled

The last question, and the one none of the three above can answer: a condition that is never
evaluated looks exactly like one that is, and so does a reference that resolves to nothing.

`live-run.ts` runs the same automation twice, differing only in what its condition compares
against - once so it holds, once so it does not - and reads back the execution tree OpenCelium
logged. What it prints is the `if` result and the payload the request actually carried:

```
[holds   ] connection 77, if -> true, sent {"title": "jakobs Client"}
[does not] connection 78, if -> false, nothing sent
```

**It is safe to run against a live installation.** The write into the target system is replaced,
after compiling and before sending, with a request to a host that does not resolve - so the
automation reads DataGerry, evaluates the condition, and at most fails to reach a hostname that has
no address. Nothing it runs can reach the target system. Both connections and both schedulers are
deleted afterwards.

```bash
node_modules/esbuild/bin/esbuild tools/verify-automation-compiler/live-run.ts \
  --bundle --platform=node --format=cjs \
  --alias:@angular/core=tools/verify-automation-compiler/stub-angular-core.js \
  --outfile=/tmp/oc/live-run.cjs --log-level=error

OC_BASE=$OC OC_TOKEN="$TOKEN" DG_DATA_DIR=/tmp/oc \
  RUN_TYPE_ID=10 RUN_FIELDS=text-98758,dg-modelspec-manufacturer RUN_MATCH=jakob \
  node /tmp/oc/live-run.cjs
```

`RUN_TYPE_ID` must be an object type that holds at least one object - a type with none makes the
loop run zero times and the check prove nothing. `RUN_FIELDS` is that type's field names **in the
order the type declares them**, because that order is the address of a value. `RUN_MATCH` is a
piece of text the first of those fields contains on at least one object.
