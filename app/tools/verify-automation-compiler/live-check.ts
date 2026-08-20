import * as fs from 'fs';

import { createEmptyAutomationDefinition, AutomationDefinition } from '../../src/app/toolbox/automations/wizard/models/automation-definition.model';
import { AutomationCompilerService } from '../../src/app/toolbox/automations/wizard/services/automation-compiler.service';
import { TargetCatalogService } from '../../src/app/toolbox/automations/wizard/services/target-catalog.service';

const dir = process.env['DG_DATA_DIR']!;
const read = (f: string) => JSON.parse(fs.readFileSync(`${dir}/${f}`, 'utf8'));

function unwrap(x: any): any {
    if (Array.isArray(x)) return x;
    if (x && typeof x === 'object') {
        for (const k of ['_embedded', 'content', 'invokers', 'connectors']) if (k in x) return unwrap(x[k]);
        const lists = Object.values(x).filter(Array.isArray);
        if (lists.length) return lists[0];
    }
    return x;
}

const invokers: any[] = unwrap(read('invokers.json'));
const connectors: any[] = unwrap(read('connectors.json'));
const byName = new Map(invokers.map(i => [i.name, i]));

const full = (c: any) => ({ ...c, invoker: byName.get(typeof c.invoker === 'string' ? c.invoker : c.invoker?.name) ?? c.invoker });
const idoit = full(connectors.find(c => c.connectorId === 1));
const dg = full(connectors.find(c => c.connectorId === 3));

const catalog = new TargetCatalogService();
const compiler = new AutomationCompilerService(catalog);
const ok = (b: any) => b ? '  ok  ' : ' FAIL ';
let failures = 0;
const check = (label: string, value: any, detail = '') => {
    const good = !!value && (!Array.isArray(value) || value.length > 0);
    if (!good) failures++;
    console.log(`[${ok(good)}] ${label.padEnd(46)} ${detail || JSON.stringify(value)}`);
};

console.log('=== Operationen auflösen ===');
for (const action of ['list', 'create', 'update', 'delete'] as const) {
    const op = catalog.resolveOperation(idoit.invoker, action);
    check(`i-doit ${action}`, op, op ? `${op.name}  verified=${op.verified}  array='${op.responseArrayPath}'` : 'nicht aufgelöst');
}
const dgList = catalog.resolveOperation(dg.invoker, 'list');
check('DataGerry list', dgList, dgList ? `${dgList.name}  array='${dgList.responseArrayPath}'` : 'nicht aufgelöst');

console.log('\n=== Abgleich-Auflösung gegen den echten i-doit-Invoker ===');
const lookup = catalog.resolveOperation(idoit.invoker, 'list')!;
const filter = catalog.matchFilter(idoit.invoker, lookup);
check('Filterpfad der Suche', filter, filter ? `${filter.basePath} → [${filter.keys.join(', ')}]` : 'kein Filter gefunden');
const elementId = catalog.elementIdPath(idoit.invoker, lookup);
check('ID im Suchergebnis', elementId, elementId || 'nicht gefunden');
const updateOp = catalog.resolveOperation(idoit.invoker, 'update')!;
const writeId = catalog.writeIdPath(updateOp, 'params.title');
check('ID-Feld der Schreiboperation', writeId, writeId || 'nicht gefunden');

console.log('\n=== "Update Clients" kompilieren ===');
const definition: AutomationDefinition = createEmptyAutomationDefinition();
definition.name = 'Update Clients';
definition.direction = 'outgoing';
definition.objectType = { typeId: 10, name: 'client', label: 'Client' };
definition.fields = [{ name: 'text-98758', label: 'Name', type: 'text' }];
definition.target = {
    connectorId: 1, connectorTitle: 'idoit', invokerName: 'i-doit',
    operation: 'update', remoteObjectTypeId: ''
};
definition.mapping = [{
    target: 'params.title',
    sources: [{ field: 'text-98758', origin: 'manual', confidence: 1 }]
}];

// The calls come from the sequence, which is what an automation written since the change looks
// like: a lookup in the target system and a write that reads its answer. Deriving them from an
// action is what this stopped doing, so asking for it back here would check a design nobody has.
const lookupStep = 'extra-lookup';
const writeStep = 'extra-write';

// Which field ends up where is a reference in a request value, which is what the sequence screen
// writes - not an entry in `mapping`, which is only applied where the compiler still derives a
// call. Colours are handed out by position: the read is the first, the lookup the second.
const readColour = '#FFCFB5';
const lookupColour = '#C77E7E';

definition.extras = [
    { id: lookupStep, after: '1', kind: 'operation', operation: 'cmdb.objects.read' },
    {
        id: writeStep,
        after: lookupStep,
        kind: 'operation',
        operation: 'cmdb.object.update',
        body: {
            'params.id': `${lookupColour}.(response).body.$.result[0].id`,
            'params.title': `${readColour}.(response).body.$.results[i].fields[0].value`
        }
    }
] as AutomationDefinition['extras'];

const context = { internalConnector: dg, targetConnector: idoit, objectTypeFieldOrder: ['text-98758'] };
const errors = compiler.validate(definition, context);
check('validate()', errors.length === 0, errors.length ? errors.join(' | ') : 'keine Fehler');

if (errors.length === 0) {
    const { payload, warnings } = compiler.compileForCreate(definition, context);
    const c = payload.connection;
    check('fromConnector.connectorId', c.fromConnector.connectorId === -1, String(c.fromConnector.connectorId));
    check('toConnector null', c.toConnector === null, String(c.toConnector));
    check('Methoden', c.fromConnector.methods.length === 3,
        c.fromConnector.methods.map(m => `${m.index}:${m.name}`).join('  '));
    check('Operatoren', c.fromConnector.operators.length >= 1,
        c.fromConnector.operators.map(o => `${o.index}:${o.type}`).join('  '));
    check('Bindungen', c.fieldBinding.length >= 1, String(c.fieldBinding.length));
    const written = c.fromConnector.methods.filter(m => m.name !== 'Get Objects');
    check('Die Sequenz liefert die Aufrufe', written.length === 2,
        written.map(m => m.name).join(', ') || 'keine');
    const iteratorRefs = JSON.stringify(c).match(/results\[i\]/g) ?? [];
    check('Iterator-Referenzen', iteratorRefs.length > 0, `${iteratorRefs.length}× results[i]`);
    fs.writeFileSync(`${dir}/compiled.json`, JSON.stringify(payload, null, 2));
    console.log(`\nWarnungen (${warnings.length}):`);
    warnings.forEach(w => console.log('  - ' + w));
}

// A second payload with a restriction, so the expression the engine has to parse can be
// tried against a real installation rather than only against the operator catalogue.
if (errors.length === 0) {
    const restricted: AutomationDefinition = JSON.parse(JSON.stringify(definition));
    restricted.name = 'Update Clients (mit Bedingung)';
    restricted.conditions = {
        combinator: 'and',
        negate: false,
        rules: [{ field: 'text-98758', operator: 'contains', value: 'srv' }]
    };

    const withCondition = compiler.compileForCreate(restricted, context);
    const gate = withCondition.payload.connection.fromConnector.operators.find(o => o.index === '1_0');
    console.log('\nBedingungs-Gate:', gate ? `${gate.index} ${gate.type}  ${gate.expression}` : 'keines erzeugt');
    fs.writeFileSync(`${dir}/compiled-conditions.json`, JSON.stringify(withCondition.payload, null, 2));
}

console.log(`\n${failures === 0 ? 'ALLES AUFGELÖST' : `${failures} FEHLER`}`);
process.exit(failures === 0 ? 0 : 1);
