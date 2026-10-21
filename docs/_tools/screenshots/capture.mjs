/**
 * Regenerates the DataGerry 3.3 documentation screenshots from a running
 * DataGerry instance with sample data (see README.md).
 *
 * Usage
 *   npm i playwright-core
 *   DG_BASE=https://cmdb.example.com DG_USER=admin DG_PASS=secret \
 *   DG_SUBSCRIPTION=Medium node capture.mjs            # all shots
 *   ONLY=types,acl node capture.mjs                    # some groups
 *
 * Output goes to $OUT (default ./out) in the same layout as docs/source/img/,
 * so `cp -r out/* ../../source/img/` puts every file in place.
 *
 * Safety
 *   The script is read-only. Every request other than GET/HEAD/OPTIONS and the
 *   login call is aborted by a route guard and printed as BLOCKED, so even an
 *   accidental click on Save cannot change the instance. Forms and dialogs are
 *   only opened (and sometimes filled in) for the shot; nothing is submitted.
 */
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';

const BASE = (process.env.DG_BASE || 'http://127.0.0.1:4200').replace(/\/$/, '');
const USER = process.env.DG_USER;
const PASS = process.env.DG_PASS;
const SUBSCRIPTION = process.env.DG_SUBSCRIPTION || '';
const EXEC = process.env.CHROMIUM
  || `${process.env.HOME}/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome`;
const OUT = process.env.OUT || 'out';
const ONLY = process.env.ONLY ? process.env.ONLY.split(',') : null;
const STATE = process.env.STATE || '';   // optional file to cache the login between runs
if (!USER || !PASS) { console.error('Set DG_USER and DG_PASS'); process.exit(1); }

// Public IDs of sample data used by the shots. Override with DG_IDS='{"server":12,...}'.
const ID = {
  typeServer: 16,         // a type with several sections, used for the type builder steps
  typeSwitch: 19,
  typeClient: 13,         // object list for search / filter / bulk change
  typeCompany: 1,         // a type with a custom multi data section
  typeRouter: 20,
  category: 4,            // category shown in the edit form
  server: 316,            // object with relations for the object view / CI Explorer
  rack: 402,              // rack with mounted objects
  switch: 294,            // standard network device with ports and cables
  patchPanel: 305,        // patch panel with front/rear ports
  portless: 364,          // object whose type has the Ports section, used to open the Add ports wizard
  relation: 8,            // relation type shown in the relation builder
  ismsRiskRow: 0,         // row in the risk list used for the risk views
  ismsAssessment: 11,     // risk assessment shown in the form
  ismsControlRow: 3,      // row in the control list of a control that has assignments
  relationTab: 'nutzt Speicher von',  // relation tab on the server object
  ...JSON.parse(process.env.DG_IDS || '{}'),
};

const log = [];
const browser = await chromium.launch({ executablePath: EXEC, args: ['--no-sandbox', '--disable-dev-shm-usage'] });
const ctxOpts = { viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'en-GB', timezoneId: 'Europe/Berlin' };
let ctx = await browser.newContext(STATE && fs.existsSync(STATE) ? { ...ctxOpts, storageState: STATE } : ctxOpts);
// The closed notification drawer sits right of the viewport and casts a shadow
// over the right edge of every page; toasts would cover the content.
const HIDE_CSS = '.notification-drawer{box-shadow:none!important}#toast-container,.toast-container{display:none!important}';
await ctx.addInitScript(css => {
  document.addEventListener('DOMContentLoaded', () => { const st = document.createElement('style'); st.textContent = css; document.head.appendChild(st); });
}, HIDE_CSS);
let page = await ctx.newPage();
guard(page);
page.setDefaultTimeout(10000);

// ------------------------------------------------------------------ helpers
function guard(p) {
  p.route('**/*', route => {
    const r = route.request();
    if (['GET', 'HEAD', 'OPTIONS'].includes(r.method()) || /\/auth\/login\/?$/.test(r.url())) return route.continue();
    console.log(`     BLOCKED ${r.method()} ${r.url()}`);
    return route.abort();
  });
}
const sleep = ms => page.waitForTimeout(ms);
async function settle(ms = 1500) {
  await page.waitForLoadState('networkidle').catch(() => {});
  await sleep(ms);
}
async function go(p, ms = 2000) {
  await page.goto(BASE + p, { waitUntil: 'networkidle' }).catch(() => {});
  await settle(ms);
  await clearToasts();
}
async function clearToasts() {
  await page.evaluate(() => document.querySelectorAll('#toast-container, .toast-container, ngb-toast').forEach(e => e.remove())).catch(() => {});
}
const parkMouse = () => page.mouse.move(1435, 895);
function file(name) {
  const f = path.join(OUT, name);
  fs.mkdirSync(path.dirname(f), { recursive: true });
  return f;
}
/** Screenshot: target = locator (element), array of locators (union box), or nothing (viewport). */
async function snap(name, target, { pad = 0, maxHeight = 0, hover = false } = {}) {
  if (!hover) await parkMouse();
  await clearToasts();
  await sleep(300);
  if (!target) return page.screenshot({ path: file(name) });
  const locs = Array.isArray(target) ? target : [target];
  // Grow the viewport to the whole document instead of scrolling, so the fixed
  // navigation bar never covers the top of a tall element.
  const docH = await page.evaluate(() => Math.max(document.documentElement.scrollHeight, document.body.scrollHeight));
  const grown = docH > 900;
  if (grown) { await page.setViewportSize({ width: 1440, height: Math.min(docH + 20, 5000) }); await sleep(700); }
  await page.evaluate(() => window.scrollTo(0, 0));
  try {
    const boxes = [];
    for (const l of locs) { const b = await l.boundingBox(); if (b) boxes.push(b); }
    if (!boxes.length) throw new Error('nothing to shoot for ' + name);
    const x0 = Math.max(0, Math.min(...boxes.map(b => b.x)) - pad);
    const y0 = Math.max(0, Math.min(...boxes.map(b => b.y)) - pad);
    const x1 = Math.min(1440, Math.max(...boxes.map(b => b.x + b.width)) + pad);
    let y1 = Math.max(...boxes.map(b => b.y + b.height)) + pad;
    if (maxHeight) y1 = Math.min(y1, y0 + maxHeight);
    await page.screenshot({ path: file(name), clip: { x: x0, y: y0, width: x1 - x0, height: y1 - y0 } });
  } finally {
    if (grown) { await page.setViewportSize({ width: 1440, height: 900 }); await sleep(300); }
  }
}
const content = () => page.locator('#content');
const modal = () => page.locator('.modal-content').last();
async function closeModal() {
  await modal().getByRole('button', { name: /cancel|close/i }).first().click().catch(() => page.keyboard.press('Escape'));
  await sleep(500);
}
/** A section (fieldset) of an object form or view, by its legend. */
const section = name => page.locator('fieldset', { has: page.locator('legend', { hasText: name }) }).first();
const editIcons = scope => scope.locator('svg[data-icon="pen-to-square"], svg[data-icon="edit"], .fa-edit, .fa-pen-to-square');
const palette = () => page.locator('dg-builder-palette #controlWrapper');
const builderSection = name => page.locator('#form-content > section', { hasText: name }).first();
async function step(name, fn) {
  if (ONLY && !ONLY.some(o => name === o || name.startsWith(o + '/'))) return;
  try { await fn(); log.push(`ok   ${name}`); console.log(`ok   ${name}`); }
  catch (e) { const m = e.message.split('\n')[0].slice(0, 200); log.push(`FAIL ${name}: ${m}`); console.log(`FAIL ${name}: ${m} (at ${page.url().replace(BASE, '')})`);
    await page.screenshot({ path: file(`_fail/${name.replace(/\//g, '_')}.png`) }).catch(() => {}); }
  await page.keyboard.press('Escape').catch(() => {});
}

async function login() {
  await page.goto(BASE + '/', { waitUntil: 'networkidle' }).catch(() => {});
  await sleep(1500);
  if (!page.url().includes('/auth')) return;
  await page.locator('input[formcontrolname="username"], input[type="text"]').first().fill(USER);
  await page.locator('input[formcontrolname="password"]').fill(PASS);
  await page.locator('#login-button').click();
  await sleep(4000);
  // Cloud: pick the subscription
  if (await page.locator('ng-select').count()) {
    await page.locator('ng-select').click();
    const opt = SUBSCRIPTION
      ? page.locator('.ng-option', { hasText: new RegExp('^\\s*' + SUBSCRIPTION + '\\s*$', 'i') })
      : page.locator('.ng-option');
    await opt.first().click();
    await page.getByRole('button', { name: /proceed/i }).click();
    await sleep(4000);
  }
  if (STATE) await ctx.storageState({ path: STATE });
}
async function dismissStartAssistant() {
  const cancel = page.locator('.modal button:has-text("Cancel")');
  if (await cancel.count()) { await cancel.first().click(); await sleep(800); }
}

// ------------------------------------------------------------------ shots
await login();
await dismissStartAssistant();

// ---- sign-in page and subscription picker (fresh browser context, nothing stored)
await step('cloud/sign_in', async () => {
  const c = await browser.newContext(ctxOpts);
  const p = await c.newPage();
  guard(p);
  const shotForm = async name => {
    const b = await p.locator('.login-wrapper').boundingBox();
    await p.screenshot({ path: file(name), clip: { x: b.x - 60, y: b.y - 40, width: b.width + 120, height: b.height + 80 } });
  };
  try {
    await p.goto(BASE + '/auth/login', { waitUntil: 'networkidle' }); await p.waitForTimeout(2000);
    await p.mouse.move(1435, 895);
    await shotForm('cloud/cloud_sign_in.png');
    await p.locator('input[formcontrolname="username"]').fill(USER);
    await p.locator('input[formcontrolname="password"]').fill(PASS);
    await p.locator('#login-button').click(); await p.waitForTimeout(4000);
    if (!(await p.locator('ng-select').count())) throw new Error('no subscription picker (single subscription or self-hosted)');
    // The credentials are no longer on screen once the picker shows.
    if (await p.locator('input[formcontrolname="username"]').count()) throw new Error('login form still visible');
    await p.locator('ng-select').click(); await p.waitForTimeout(400);
    await p.locator('.ng-option', { hasText: new RegExp('^\\s*' + (SUBSCRIPTION || '.') + '\\s*$', 'i') }).first().click();
    await p.waitForTimeout(500); await p.mouse.move(1435, 895);
    await shotForm('cloud/cloud_select_subscription.png');
  } finally { await c.close(); }
});

// ---- categories
await step('categories/overview', async () => {
  await go('/framework/category');
  await snap('categories/categories_overview.png', content());
});
await step('categories/sidebar', async () => {
  await go('/framework/category');
  await snap('categories/categories_sidebar.png', page.locator('#sidebar .sb-nav'), { pad: 8 });
});
await step('categories/add', async () => {
  await go('/framework/category/add');
  await snap('categories/categories_add.png', content());
});
await step('categories/edit_tree', async () => {
  await go('/framework/category');
  await page.getByRole('button', { name: /organize/i }).click();
  await settle(1000);
  await snap('categories/categories_edit_tree.png', content());
});
await step('categories/edit_form', async () => {
  await go(`/framework/category/edit/${ID.category}`);
  await snap('categories/categories_edit_form.png', content());
});

// ---- types
async function wide(on = true) {
  // Collapse the sidebar so wide tables do not wrap.
  const collapsed = ((await content().boundingBox())?.x ?? 230) < 150;
  if (collapsed !== on) { await page.locator('#sidebar .sb-toggle').click(); await sleep(800); }
}
await step('types/overview', async () => {
  await go('/framework/type');
  await wide(true);
  await snap('types/types_overview.png', content());
  await wide(false);
});
async function typeStep(n, id = ID.typeServer) {
  await go(`/framework/type/edit/${id}`);
  for (let i = 0; i < n; i++) {
    await page.getByRole('button', { name: /next step/i }).first().click();
    await settle(1200);
  }
}
await step('types/basic', async () => {
  await typeStep(0);
  await snap('types/types_create_basic_information_step.png', content());
});
await step('types/content', async () => {
  await typeStep(1);
  await page.getByText(/^\s*basic controls\s*$/i).first().click().catch(() => {});
  await settle(800);
  await snap('types/types_create_content_step.png', content(), { maxHeight: 900 });
});
await step('types/meta', async () => {
  await typeStep(2);
  await snap('types/types_create_meta_step.png', content());
});
await step('types/acl', async () => {
  await typeStep(3);
  await snap('types/types_create_acl_step.png', content());
});

// ---- an object view (concepts/data-model)
await step('objects/object_view', async () => {
  await go(`/framework/object/view/${ID.switch}`);
  await snap('objects/object_view.png', [page.locator('.object-view-navbar'), page.locator('cmdb-multi-data-section').first()], { pad: 8 });
});

// ---- type ACL (access control)
await step('acl/protected', async () => {
  await typeStep(3);
  await snap('acl/object_type_builder_acl_protected.png', content());
});
async function aclOn() {
  await typeStep(3);
  await page.locator('#acl-activated-button').check({ force: true });
  await settle(600);
}
async function aclRow(group, perms) {
  const row = content().locator('tr', { has: page.locator('ng-select') }).first();
  await row.locator('ng-select').first().click(); await sleep(400);
  await page.locator('.ng-dropdown-panel .ng-option', { hasText: new RegExp(group, 'i') }).first().click(); await sleep(300);
  for (const p of perms) {
    await row.locator('ng-select').nth(1).click(); await sleep(300);
    await page.locator('.ng-dropdown-panel .ng-option', { hasText: new RegExp('^\\s*' + p + '\\s*$', 'i') }).first().click(); await sleep(300);
  }
  await page.keyboard.press('Escape');
  return row;
}
await step('acl/setup', async () => {
  await aclOn();
  await aclRow('user', ['READ', 'CREATE', 'UPDATE']);
  await snap('acl/object_type_builder_acl_setup.png', content());
});
await step('acl/example', async () => {
  await aclOn();
  const row = await aclRow('user', ['READ', 'CREATE', 'UPDATE']);
  await row.locator('button').last().click(); await settle(600);   // the green + adds the row (local only)
  await aclRow('admin', ['READ', 'CREATE', 'UPDATE', 'DELETE']);
  await content().locator('tr', { has: page.locator('ng-select') }).first().locator('button').last().click(); await settle(600);
  await snap('acl/object_type_builder_acl_example.png', content());
});

// ---- objects
const clientList = async () => { await go(`/framework/object/type/${ID.typeClient}`); await content().locator('select').first().selectOption('10').catch(() => {}); await settle(1200); };
const searchBox = () => content().locator('input.form-control-sm:not([type=checkbox])').last();
await step('objects/active_switch', async () => {
  await go(`/framework/object/type/${ID.typeClient}`);
  const sw = page.locator('#active-switch');
  const b = await sw.boundingBox();
  await page.screenshot({ path: file('objects/objects_active_switch.png'), clip: { x: b.x - 260, y: 88, width: 1440 - (b.x - 260), height: 46 } });
});
await step('objects/search_initial', async () => {
  await clientList();
  await snap('objects/object_table_search_initial.png', content());
});
await step('objects/search_result', async () => {
  await clientList();
  await searchBox().fill('hh'); await settle(1500);
  await snap('objects/object_table_search_result.png', content());
});
async function filterRow(i, col, value) {
  const rows = content().locator('thead').nth(1).locator('tr');
  await rows.nth(i).locator('th').nth(col).locator('input').fill(value);
  await settle(1500);
}
await step('objects/filter', async () => {
  await clientList();
  await content().getByRole('button', { name: /filter/i }).click(); await settle(800);
  await filterRow(0, 3, 'nb-');
  await snap('objects/object_table_filter_result.png', content());
});
await step('objects/filter_or', async () => {
  await clientList();
  await content().getByRole('button', { name: /filter/i }).click(); await settle(800);
  await filterRow(0, 3, 'nb-');
  await content().locator('thead').nth(1).locator('.fa-plus').first().click(); await settle(800);
  await filterRow(1, 3, 'hh');
  await snap('objects/object_table_filter_example_1_result.png', content());
});
await step('objects/filter_and', async () => {
  await clientList();
  await content().getByRole('button', { name: /filter/i }).click(); await settle(800);
  await filterRow(0, 3, 'ber');
  await filterRow(0, 2, '38');
  await snap('objects/object_table_filter_example_2_result.png', content());
});
await step('objects/bulk_list', async () => {
  await clientList();
  const boxes = content().locator('tbody input.form-check-input');
  for (const i of [1, 2, 3]) await boxes.nth(i).check();
  await settle(500);
  await snap('objects/objects_bulk_change_list.png', content());
});
await step('objects/bulk_change', async () => {
  await clientList();
  const boxes = content().locator('tbody input.form-check-input');
  for (const i of [1, 2, 3]) await boxes.nth(i).check();
  await content().getByRole('button', { name: /bulk change/i }).click(); await settle(2000);
  const spec = section('Model specifications');
  await spec.locator('input[type=checkbox]').nth(1).check({ force: true }).catch(e => console.log('   ', e.message.split('\n')[0]));
  await sleep(400);
  await spec.locator('input:not([type=checkbox])').nth(1).fill('OptiPlex 7020 Tower').catch(e => console.log('   ', e.message.split('\n')[0]));
  await sleep(400);
  await snap('objects/objects_bulk_change_active.png', content(), { maxHeight: 700 });
  await page.locator('button.next', { hasText: /next step/i }).click(); await settle(1500);
  await snap('objects/objects_bulk_change_preview.png', content(), { maxHeight: 900 });
});

// ---- multi data sections
await step('mds/vs_section', async () => {
  await go(`/framework/object/view/${ID.switch}`);
  await snap('mds/mds_multi_data_section_vs_section.png', [section('Model specifications'), page.locator('cmdb-multi-data-section').first()], { pad: 8 });
});
await step('mds/structure_control', async () => {
  await typeStep(1);
  await page.getByText(/^\s*structure controls\s*$/i).first().click(); await settle(800);
  await snap('mds/mds_structure_control.png', palette(), { pad: 6 });
});
await step('mds/fields', async () => {
  await typeStep(1, ID.typeCompany);
  await page.getByText(/^\s*structure controls\s*$/i).first().click(); await settle(800);
  await snap('mds/mds_add_fields_to_mds.png', builderSection('Contacts'), { pad: 8 });
});
await step('mds/new_object', async () => {
  await go(`/framework/object/add/${ID.typeCompany}`);
  await snap('mds/mds_add_object_with_mds.png', content(), { maxHeight: 1400 });
});

await step('mds/add_entry', async () => {
  await go(`/framework/object/add/${ID.typeCompany}`);
  const mds = page.locator('cmdb-multi-data-section', { hasText: 'Contacts' }).first();
  await mds.getByRole('button', { name: /add/i }).first().click(); await settle(1000);
  await snap('mds/mds_add_mds_entry.png', modal());
  await closeModal();
});
await step('mds/table', async () => {
  await go(`/framework/object/edit/${ID.server}`);
  await snap('mds/mds_tableoverview.png', page.locator('cmdb-multi-data-section').first(), { pad: 8 });
});

// ---- locations
await step('locations/special_control', async () => {
  await typeStep(1);
  await page.getByText(/^\s*special controls\s*$/i).first().click(); await settle(800);
  const loc = builderSection('Location');
  await loc.scrollIntoViewIfNeeded();
  // open the field settings of the location field (first edit icon of its field row)
  await editIcons(loc).nth(1).click().catch(e => console.log('   ', e.message.split('\n')[0]));
  await settle(800);
  await snap('locations/locations_special_control.png', loc, { pad: 8 });
});
await step('locations/fields', async () => {
  await go(`/framework/object/edit/${ID.server}`);
  await snap('locations/locations_added_fields.png', section('Location'), { pad: 8 });
});
await step('locations/dropdown', async () => {
  await go(`/framework/object/edit/${ID.server}`);
  const sec = section('Location');
  await sec.locator('.lts-display').first().click(); await settle(1200);
  await snap('locations/locations_dropdown_selection.png', page.locator('.modal-content').last());
  await page.locator('.modal-content').last().getByRole('button', { name: /cancel/i }).click();
});
await step('locations/sidebar', async () => {
  await go(`/framework/object/view/${ID.rack}`);
  await page.locator('#sidebar').getByText('Navigation', { exact: true }).click(); await settle(1200);
  for (const n of ['Germany', 'Berlin', 'BER-HQ', 'Serverraum', 'BER-R01']) {
    const node = page.locator('#sidebar .tree-node', { has: page.locator('.node-text', { hasText: n }) }).first();
    await node.locator('.expand-toggle').first().click().catch(() => {}); await settle(900);
  }
  await snap('locations/locations_displayed_sidebar.png');
});

// ---- section templates
await step('section_templates/overview', async () => {
  await go('/framework/section_templates');
  await snap('section_templates/section_templates_overview.png', content());
});
await step('section_templates/creation', async () => {
  await go('/framework/section_templates/add');
  await snap('section_templates/section_templates_creation.png', content());
});
await step('section_templates/usage', async () => {
  await typeStep(1, ID.typeCompany);
  await snap('section_templates/section_templates_usage.png', [palette(), builderSection('Interfaces')], { pad: 8, maxHeight: 520 });
});
await step('section_templates/actions', async () => {
  await go('/framework/section_templates');
  const t = content().locator('table').first();
  await snap('section_templates/section_templates_table_actions.png', [t.locator('th', { hasText: 'Type' }), t.locator('tbody tr').last().locator('td').last()]);
});

// ---- relations
await step('nm_relations/overview', async () => {
  await go('/framework/relation');
  await snap('nm_relations/nm_relations_relations_overview.png', content());
});
await step('nm_relations/basic', async () => {
  await go(`/framework/relation/edit/${ID.relation}`);
  await snap('nm_relations/nm_relations_create_basic_info.png', content());
});
await step('nm_relations/content', async () => {
  await go(`/framework/relation/edit/${ID.relation}`);
  await page.locator('button.next:visible').first().click(); await settle(1200);
  await snap('nm_relations/nm_relations_create_content.png', content(), { maxHeight: 800 });
});
const relCard = () => page.locator('cmdb-object-relations .card').first();
await step('nm_relations/add_object_relation', async () => {
  await go(`/framework/object/view/${ID.server}`);
  await snap('nm_relations/nm_relations_add_object_relation.png', [page.locator('.object-view-navbar'), relCard().locator('.card-header').first()], { pad: 8 });
});
await step('nm_relations/select', async () => {
  await go(`/framework/object/view/${ID.server}`);
  await relCard().getByRole('button', { name: /add relation/i }).click(); await settle(1200);
  await snap('nm_relations/nm_relations_select_object_relation.png', page.locator('.modal-content').last());
});
await step('nm_relations/tab', async () => {
  await go(`/framework/object/view/${ID.server}`);
  await relCard().locator('.card-header').getByText(ID.relationTab).click(); await settle(1500);
  await snap('nm_relations/nm_relations_object_relation_overview.png', relCard(), { maxHeight: 500 });
  await relCard().getByText(new RegExp('^\\s*Add ' + ID.relationTab)).first().click(); await settle(1500);
  await snap('nm_relations/nm_relations_object_relation_select_child.png', page.locator('.modal-content').last());
});

// ---- object groups, persons, person groups
await step('object_groups/overview', async () => {
  await go('/framework/object_groups');
  await snap('object_groups/object_groups_overview.png', content());
});
await step('object_groups/create', async () => {
  await go('/framework/object_groups/add');
  await content().locator('input').first().fill('Core switches Berlin');
  await snap('object_groups/object_groups_create.png', content());
});
await step('object_groups/categories', async () => {
  await go('/framework/object_groups/add');
  await content().getByRole('button', { name: /manage categories/i }).click(); await settle(1200);
  await snap('object_groups/object_groups_manage_categories.png', page.locator('.modal-content').last());
});
await step('persons/overview', async () => {
  await go('/framework/persons');
  await snap('persons/persons_overview.png', content());
});
await step('persons/create', async () => {
  await go('/framework/persons/add');
  const inputs = content().locator('input:visible');
  await inputs.nth(0).fill('Jana'); await inputs.nth(1).fill('Albers');
  await settle(400);
  await snap('persons/persons_create.png', content());
});
await step('person_groups/table', async () => {
  await go('/framework/person-groups');
  await snap('person_groups/person_groups_table.png', content());
});
await step('person_groups/create', async () => {
  await go('/framework/person-groups/add');
  await content().locator('input:visible').first().fill('Service Desk');
  await snap('person_groups/person_groups_create.png', content());
});

// ---- users and user groups
await step('users/create', async () => {
  await go('/management/users/add');
  // In the cloud, users are managed in the Service Portal and this form is read-only.
  if (!(await page.locator('#user-form-username-control').isEditable())) throw new Error('user form is read-only here (cloud?) - skipped');
  await page.fill('#user-form-username-control', 'j.albers');
  await page.fill('#user-form-email-control', 'j.albers@example.com');
  await page.fill('#user-form-firstname-control', 'Jana');
  await page.fill('#user-form-lastname-control', 'Albers');
  await settle(800);
  await snap('users/user_create.png', content());
});
await step('user_groups/overview', async () => {
  await go('/management/groups');
  await snap('user_groups/user_groups_overview.png', content());
});
await step('user_groups/create', async () => {
  await go('/management/groups/add');
  const inputs = content().locator('input:visible');
  await inputs.nth(0).fill('helpdesk'); await inputs.nth(1).fill('Helpdesk');
  await settle(400);
  await snap('user_groups/user_groups_create.png', content());
});

// ---- CI Explorer (graph view of the object view)
async function graph() {
  await go(`/framework/object/view/${ID.server}`);
  await page.locator('button[title="Graph View"]').click(); await settle(2500);
  await page.locator('button[title^="Reset View"]').click().catch(() => {}); await settle(1200);
}
/** Union box of every element matching the selector, as a clip for snapClip(). */
async function boxAll(selector, pad = 16) {
  return page.evaluate(([sel, pad]) => {
    const rs = [...document.querySelectorAll(sel)].map(e => e.getBoundingClientRect()).filter(r => r.width && r.height);
    const x = Math.max(0, Math.min(...rs.map(r => r.left)) - pad), y = Math.max(0, Math.min(...rs.map(r => r.top)) - pad);
    return { x, y, width: Math.min(1440, Math.max(...rs.map(r => r.right)) + pad) - x, height: Math.max(...rs.map(r => r.bottom)) + pad - y };
  }, [selector, pad]);
}
async function snapClip(name, selector, pad) {
  const docH = await page.evaluate(() => document.documentElement.scrollHeight);
  if (docH > 900) { await page.setViewportSize({ width: 1440, height: Math.min(docH + 20, 5000) }); await sleep(800); }
  await page.evaluate(() => window.scrollTo(0, 0));
  await parkMouse(); await clearToasts();
  try { await page.screenshot({ path: file(name), clip: await boxAll(selector, pad) }); }
  finally { await page.setViewportSize({ width: 1440, height: 900 }); }
}
await step('ci_explorer/open', async () => {
  await go(`/framework/object/view/${ID.server}`);
  await page.locator('button[title="Graph View"]').hover(); await sleep(800);
  await snap('ci_explorer/ci_explorer_open.png', [page.locator('.object-view-navbar'), page.locator('#object-header')], { pad: 8, hover: true });
});
await step('ci_explorer/overview', async () => {
  await graph();
  await page.locator('button[title^="Maximize"]').click(); await settle(1000);
  await page.locator('button[title^="Reset View"]').click(); await settle(1200);
  await snap('ci_explorer/ci_explorer_overview.png');
});
await step('ci_explorer/context_menu', async () => {
  await graph();
  await page.locator('cmdb-graph-node').first().click({ button: 'right' }); await settle(800);
  await snapClip('ci_explorer/ci_explorer_context_menu.png', '#content cmdb-graph-node, cmdb-graph-context-menu, [class*=context-menu]', 24);
});
await step('ci_explorer/object_details', async () => {
  await graph();
  await page.locator('cmdb-graph-node.root-node').click(); await settle(1500);
  await snap('ci_explorer/ci_explorer_object_details.png', page.locator('.modal-content').last());
});
await step('ci_explorer/relation_details', async () => {
  await graph();
  await page.locator('#content svg path[pointer-events="stroke"]').first().dispatchEvent('click'); await settle(1500);
  await snap('ci_explorer/ci_explorer_relation_details.png', page.locator('.modal-content').last());
});
await step('ci_explorer/profile_manager', async () => {
  await graph();
  await page.locator('button[title^="Maximize"]').click(); await settle(1000);
  await page.locator('button[title="Toggle Filters"]').click(); await settle(1000);
  await page.locator('button[title^="Reset View"]').click(); await settle(1200);
  await snap('ci_explorer/ci_explorer_profile_manager.png');
  await page.getByRole('button', { name: /filter profiles/i }).click(); await settle(1000);
  await page.getByRole('button', { name: /manage profiles/i }).click(); await settle(1200);
  await snap('ci_explorer/ci_explorer_manage_profiles.png', page.locator('.modal-content').last());
});

// ---- Toolbox menu, exports, assistant
async function toolbox(hoverItem) {
  await go('/');
  await page.locator('li.nav-item-toolbox a.nav-link').click(); await settle(800);
  const menu = page.locator('li.nav-item-toolbox .dropdown-menu.show');
  if (hoverItem) { await menu.locator('a.dropdown-icon-item', { hasText: hoverItem }).hover(); await sleep(500); }
  return menu;
}
await step('exports/toolbox', async () => {
  const menu = await toolbox('Exporter');
  await snap('exports/export_objects_toolbox.png', menu, { hover: true });
});
await step('exports/types', async () => {
  await go('/framework/type');
  await wide(true);
  const boxes = content().locator('tbody input.form-check-input');
  for (const i of [0, 1, 2]) await boxes.nth(i).check();
  await content().getByRole('button', { name: /export/i }).first().click(); await settle(800);
  await snap('exports/export_types.png', content(), { maxHeight: 520 });
  await wide(false);
});
await step('exports/objects', async () => {
  await go(`/framework/object/type/${ID.typeRouter}`);
  await wide(true);
  await content().locator('#exportButton').click(); await settle(800);
  await snap('exports/export_objects_raw.png', content(), { maxHeight: 520 });
  await wide(false);
});
await step('dg_assistant/toolbox', async () => {
  const menu = await toolbox('Assistant');
  await snap('dg_assistant/assistant_toolbox.png', menu, { hover: true });
});
await step('dg_assistant/wizard', async () => {
  const menu = await toolbox();
  await menu.locator('a.dropdown-icon-item', { hasText: 'Assistant' }).click(); await settle(1500);
  const modal = page.locator('.modal-content').last();
  // The Start Assistant only runs on a new, empty workspace; elsewhere it says "You're already set up".
  if (await modal.getByText(/already set up/i).count()) throw new Error('Start Assistant not available (workspace already has data) - skipped');
  // pick two branches and go on to the profile step; the wizard is cancelled afterwards, nothing is created
  const checks = modal.locator('input[type=checkbox]');
  if (await checks.count()) { await checks.nth(0).check(); await checks.nth(2).check().catch(() => {}); }
  else { await modal.locator('[class*=card], [class*=option]').first().click().catch(() => {}); }
  await sleep(400);
  await snap('dg_assistant/assistant_branches.png', modal);
  await modal.getByRole('button', { name: /continue|next/i }).first().click(); await settle(1200);
  await snap('dg_assistant/assistant_profiles.png', modal);
  await modal.getByRole('button', { name: /cancel/i }).first().click();
});
await step('dg_assistant/types_table', async () => {
  await go('/framework/type');
  await wide(true);
  await snap('dg_assistant/assistant_types_table.png', content());
  await wide(false);
});
await step('dg_assistant/type_editing', async () => {
  await typeStep(1, ID.typeSwitch);
  await snap('dg_assistant/assistant_type_editing.png', content(), { maxHeight: 700 });
});

// ---- ISMS
await step('isms/overview', async () => {
  await go('/isms');
  await page.evaluate(() => document.activeElement?.blur());
  await snap('isms/isms_overview.png', content());
});
const ismsSteps = [
  ['risk_classes', 'isms_risk_classes_overview', 'isms_risk_classes_create'],
  ['likelihood', 'isms_likelihood_overview', 'isms_likelihood_create'],
  ['impact', 'isms_impact_overview', 'isms_impact_create'],
  ['impact_categories', 'isms_impact_categories_overview', 'isms_impact_categories_create'],
  ['protection_goal', 'isms_protection_goal_overview', null],
  ['risk_matrix', 'isms_risk_matrix_overview', null],
];
for (const [i, [key, overview, create]] of ismsSteps.entries()) {
  await step(`isms/configure_${key}`, async () => {
    await go('/isms/configure');
    for (let n = 0; n < i; n++) { await content().locator('button', { hasText: /next step/i }).last().click(); await settle(1200); }
    if (key === 'risk_matrix' && await content().getByText(/unassigned/i).count())
      throw new Error('risk matrix is not configured on this instance - skipped');
    await snap(`isms/${overview}.png`, content(), { maxHeight: 900 });
    if (create) {
      await content().getByRole('button', { name: /^\s*(\+\s*)?add\s*$/i }).first().click(); await settle(1000);
      await snap(`isms/${create}.png`, modal());
      await closeModal();
    }
  });
}
for (const [key, list, create] of [
  ['threats', 'isms_threats_overview', 'isms_threats_create'],
  ['vulnerabilities', 'isms_vulnerabilities_overview', 'isms_vulnerability_create'],
  ['risks', 'isms_risk_overview', 'isms_risk_create'],
  ['control-measures', 'isms_control_overview', 'isms_control_create'],
]) {
  await step(`isms/${key}`, async () => {
    await go(`/isms/${key}`);
    await snap(`isms/${list}.png`, content(), { maxHeight: 700 });
    await go(`/isms/${key}/add`);
    await snap(`isms/${create}.png`, content());
  });
}
async function rowAction(icon, row = 0) {
  await content().locator('tbody tr').nth(row).locator(`[title*="${icon}" i], .fa-${icon}, svg[data-icon*="${icon}"]`).first().click();
  await settle(2000);
}
await step('isms/risk_example', async () => {
  await go('/isms/risks');
  await rowAction('edit', ID.ismsRiskRow);
  await snap('isms/isms_risk_example.png', content());
});
await step('isms/risk_assessment_open', async () => {
  await go('/isms/risks');
  await rowAction('eye', ID.ismsRiskRow);
  if (await content().getByText(/configuration is incomplete/i).count()) throw new Error('ISMS configuration incomplete - skipped');
  await snap('isms/isms_risk_assessment_open.png', content());
});
await step('isms/control_assignment', async () => {
  await go('/isms/control-measures');
  await rowAction('eye', ID.ismsControlRow);
  await snap('isms/isms_control_assignment.png', content());
});
await step('isms/risk_assessment_form', async () => {
  await go(`/isms/risk-assessments/edit/${ID.ismsAssessment}`);
  if (await content().getByText(/configuration is incomplete/i).count()) throw new Error('ISMS configuration incomplete on this instance - risk assessment form not available');
  await snap('isms/isms_risk_assessment_form_1_5.png', content(), { maxHeight: 900 });
});

// ---- File Explorer, Document Generator, webhooks, reports, automations
const needData = async (what) => {
  if (await content().getByText(/no data to display|no doc templates were found/i).count()) throw new Error(`no ${what} on this instance - skipped`);
};
await step('file_explorer/overview', async () => {
  await go('/filemanager/explorer');
  await snap('file_explorer/file_explorer_overview.png', content());
});
await step('document_generator/object_box', async () => {
  await go('/docapi');
  await needData('document templates');
  await go(`/framework/object/view/${ID.server}`);
  await page.locator('cmdb-object-docs .dropdown-toggle, cmdb-object-docs a, cmdb-object-docs button').first().click(); await settle(800);
  await snap('document_generator/object_template_box.png', [page.locator('cmdb-object-docs'), page.locator('cmdb-object-docs .dropdown-menu')], { pad: 8 });
});
await step('webhooks/overview', async () => {
  await go('/webhooks');
  await needData('webhooks');
  await snap('webhooks/webhooks_overview.png', content());
});
await step('webhooks/create', async () => {
  await go('/webhooks/create');
  await snap('webhooks/webhooks_create.png', content());
});
await step('reports/overview', async () => {
  await go('/reports/overview');
  await needData('reports');
  await snap('reports/reports_overview.png', content());
});
await step('reports/categories', async () => {
  await go('/reports/categories');
  await needData('report categories');
  await snap('reports/reports_categories_overview.png', content());
});
await step('reports/create', async () => {
  await go('/reports/create');
  await content().locator('input:visible').first().fill('Server inventory');
  const pick = async (i, text) => {
    await content().locator('ng-select').nth(i).click(); await sleep(500);
    await page.locator('.ng-dropdown-panel .ng-option', { hasText: text }).first().click(); await sleep(500);
  };
  await pick(0, /general/i).catch(e => console.log('   ', e.message.split('\n')[0]));
  await pick(1, /^\s*Server\s*$/).catch(e => console.log('   ', e.message.split('\n')[0]));
  for (const f of [/^\s*Name/, /Manufacturer/, /Model name/]) { await pick(2, f).catch(() => {}); }
  await page.keyboard.press('Escape'); await settle(600);
  await snap('reports/reports_create.png', content());
});
await step('automation/overview', async () => {
  await go('/automations');
  await needData('automations');
  await snap('automation/automation_overview.png', content());
});
await step('automation/connectors', async () => {
  await go('/automations/connectors');
  await needData('connectors');
  await snap('automation/manage_connectors.png', content());
});

// ---- racks, ports and cabling (3.3)
await step('racks/view', async () => {
  await go(`/framework/object/view/${ID.rack}`);
  await wide(true);
  await page.locator('section.rack-view').scrollIntoViewIfNeeded(); await settle(1000);
  await snap('racks/rack_view.png', page.locator('section.rack-view'));
  await wide(false);
});
await step('racks/add_dialog', async () => {
  await go(`/framework/object/view/${ID.rack}`);
  await page.locator('section.rack-view').getByRole('button', { name: /add to rack/i }).first().click(); await settle(1200);
  await snap('racks/rack_add_entry.png', modal());
  await closeModal();
});
await step('ports/table', async () => {
  await go(`/framework/object/view/${ID.switch}`);
  await wide(true);
  await snap('ports/ports_table.png', page.locator('cmdb-ports-overview').first(), { maxHeight: 520 });
  await wide(false);
});
await step('ports/patch_panel', async () => {
  await go(`/framework/object/view/${ID.patchPanel}`);
  await wide(true);
  await snap('ports/ports_patch_panel_table.png', page.locator('cmdb-ports-overview').first(), { maxHeight: 520 });
  await wide(false);
});
await step('ports/add_wizard', async () => {
  await go(`/framework/object/view/${ID.portless}`);
  const ports = page.locator('cmdb-ports-overview').first();
  await ports.scrollIntoViewIfNeeded();
  await ports.locator('app-button').first().click(); await settle(1200);
  await snap('ports/ports_add_wizard.png', modal());
  await closeModal();
});
await step('ports/cabling', async () => {
  await go(`/framework/object/view/${ID.switch}`);
  await page.locator('button[title="Cabling View"]').click(); await settle(3000);
  const max = page.locator('button[title*="ull screen" i], button[title*="ullscreen" i]').first();
  if (await max.count()) { await max.click(); await settle(1500); }
  await snap('ports/cabling_view.png');
});

async function dnd(src, dst) {
  await src.scrollIntoViewIfNeeded();
  const a = await src.boundingBox(), b = await dst.boundingBox();
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2);
  await page.mouse.down();
  await page.mouse.move(a.x + a.width / 2 + 10, a.y + a.height / 2 + 5, { steps: 5 });
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 15 });
  await sleep(200);
  await page.mouse.up();
}
// ---- tutorial: a new Server type in the type builder (nothing is saved)
await step('types/first_cmdb', async () => {
  await go('/framework/type/add');
  const inputs = content().locator('input:visible');
  await inputs.nth(1).fill('tutorial_server');  // 'server' exists in the sample data
  await content().locator('input:visible').nth(2).fill('Server');
  await settle(500);
  await page.locator('button.next:visible').first().click(); await settle(1200);
  await page.getByText(/^\s*structure controls\s*$/i).first().click(); await settle(600);
  const target = page.locator('#form-content');
  await palette().getByText('Section', { exact: true }).first().dragTo(target); await settle(1000);
  await page.getByText(/^\s*basic controls\s*$/i).first().click(); await settle(600);
  const sec = page.locator('#form-content section').last();
  await sec.locator('input:visible').nth(1).fill('General');
  const labels = ['Hostname', 'IP address', 'Operating system', 'In maintenance', 'Warranty until'];
  for (const [i, ctl] of ['Text', 'Text', 'Select', 'Checkbox', 'Date'].entries()) {
    const empty = sec.locator('.empty-section');
    // first field: the empty drop zone; later ones: drop onto the last field row
    if (await empty.count()) await palette().getByText(ctl, { exact: true }).first().dragTo(empty.first(), { force: true });
    else {
      const rowsBefore = await sec.locator('.card-body .card').count();
      for (let attempt = 0; attempt < 3 && (await sec.locator('.card-body .card').count()) === rowsBefore; attempt++) {
        const last = sec.locator('.card-body .card').last(); const b = await last.boundingBox();
        await palette().getByText(ctl, { exact: true }).first().dragTo(last, { force: true, targetPosition: { x: b.width / 2, y: b.height - 3 } });
        await sleep(600);
      }
    }
    await settle(700);
  }
  // give the fields their labels: open each field's settings, set Label, collapse it again
  const rows = sec.locator('.card-body .card');
  for (let i = 0; i < labels.length; i++) {
    const row = rows.nth(i);
    await editIcons(row.locator('.card-header').first()).first().click(); await sleep(500);
    const lab = row.locator('label', { hasText: /^\s*Label/ }).first().locator('xpath=following::input[1]');
    await lab.fill(labels[i]).catch(e => console.log('   ', e.message.split('\n')[0]));
    await editIcons(row.locator('.card-header').first()).first().click(); await sleep(400);
  }
  await page.locator('#content h1, #content h2').first().click().catch(() => {});
  await snap('types/first_cmdb_content_step.png', content(), { maxHeight: 900 });
});

// ------------------------------------------------------------------ done
console.log('\n' + log.join('\n'));
await browser.close();
