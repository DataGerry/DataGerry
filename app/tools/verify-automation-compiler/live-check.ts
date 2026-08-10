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
definition.mapping = [{ source: 'text-98758', target: 'params.title', origin: 'manual', confidence: 1 }];
definition.matching = { identifyBy: 'text-98758', whenMissing: 'create', whenPresent: 'update' };

const context = { internalConnector: dg, targetConnector: idoit, objectTypeFieldOrder: ['text-98758'] };
const errors = compiler.validate(definition, context);
check('validate()', errors.length === 0, errors.length ? errors.join(' | ') : 'keine Fehler');

if (errors.length === 0) {
    const { payload, warnings } = compiler.compileForCreate(definition, context);
    const c = payload.connection;
    check('fromConnector.connectorId', c.fromConnector.connectorId === -1, String(c.fromConnector.connectorId));
    check('toConnector null', c.toConnector === null, String(c.toConnector));
    check('Methoden', c.fromConnector.methods.length >= 3,
        c.fromConnector.methods.map(m => `${m.index}:${m.name}`).join('  '));
    check('Operatoren', c.fromConnector.operators.length >= 2,
        c.fromConnector.operators.map(o => `${o.index}:${o.type}`).join('  '));
    check('Bindungen', c.fieldBinding.length >= 2, String(c.fieldBinding.length));
    const idBinding = c.fieldBinding.find(b => b.to[0].field.endsWith('params.id'));
    check('ID-Bindung aus der Suche', idBinding, idBinding ? `${idBinding.from[0].field} → ${idBinding.to[0].field}` : 'fehlt');
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
