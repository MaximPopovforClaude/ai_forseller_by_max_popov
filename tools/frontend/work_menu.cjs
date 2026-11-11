// Exercise the real Sidebar with React reconciliation across markets and preferences.
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const {document} = require('./test_dom.cjs');
const base = path.resolve(process.argv[2] || '.'), deps = path.join(base, 'web/frontend/node_modules');
const React = require(path.join(deps, 'react')), {createRoot} = require(path.join(deps, 'react-dom/client'));
const {flushSync} = require(path.join(deps, 'react-dom')), ts = require(path.join(deps, 'typescript'));
global.localStorage = {getItem: () => null, setItem() {}};
const mod = {exports: {}};
new Function('require', 'module', 'exports', ts.transpileModule(fs.readFileSync(path.join(base, 'web/frontend/src/Sidebar.tsx'), 'utf8'),
  {compilerOptions: {jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020}}).outputText)(name => {
  if(name === 'react') return React;
  if(name === 'react/jsx-runtime') return require(path.join(deps, name));
  if(name === './Logo') return {Logo: () => null};
  throw Error(name);
}, mod, mod.exports);
const tab = (key, title, group = 'Управление') => ({key, title, group});
const wb = [tab('home', 'Главная', 'Магазин'), tab('mgr_actions', 'ДействияПоАртикулам'),
  tab('entry_points', 'Точки входа'), tab('photo_funnel', 'Фотоворонка'), tab('mgr_prices', 'ОнлайнЦена')];
const oz = wb.filter(t => !['entry_points', 'photo_funnel'].includes(t.key));
const calls = [], warnings = [], box = document.body.appendChild(document.createElement('main')), root = createRoot(box);
const oldError = console.error; console.error = (...a) => {warnings.push(a.join(' ')); oldError(...a);};
const walk = n => [n, ...n.childNodes.flatMap(walk)], props = n => n[Object.keys(n).find(k => k.startsWith('__reactProps$'))] || {};
const buttons = () => walk(box).filter(n => n.tagName === 'BUTTON');
const find = title => buttons().find(n => props(n).title === title || n.textContent === title);
const click = n => {assert.ok(n); flushSync(() => props(n).onClick());};
let settings = {me: {tabs: wb, user: {email: 'owner@example.invalid'}, workspaces: []}, allTabs: wb, hidden: [],
  open: true, page: 'tab', tab: 'home', theme: 'light', onTab: k => calls.push(k), onPage: p => calls.push(p),
  onToggle() {}, onTheme() {}, onLogout() {}, onHidden: keys => calls.push(keys)};
const render = patch => {settings = {...settings, ...patch}; flushSync(() => root.render(React.createElement(mod.exports.Sidebar, settings)));};
try {
  render({});
  const menu = walk(box).filter(n => ['BUTTON', 'A'].includes(n.tagName));
  const work = ['Действия по артикулам', 'Точки входа', 'Фотоворонка'];
  let previous = menu.indexOf(find('Реклама'));
  for(const name of work) {const b = find(name); assert.ok(menu.indexOf(b) > previous); previous = menu.indexOf(b);}
  const compare = menu.filter(n => props(n).href === '/compare'); assert.equal(compare.length, 1);
  assert.equal(menu.indexOf(compare[0]), previous + 1);
  assert.equal(menu.indexOf(find('Взаимодействия')), previous + 2);
  for(const name of work) assert.equal(buttons().filter(n => props(n).title === name).length, 1);
  assert.ok(!box.textContent.includes('Пригласить друга'));
  assert.ok(find('Пользователи и права'));
  click(find(work[1])); assert.equal(calls.at(-1), 'entry_points');
  render({tab: 'entry_points'}); assert.match(props(find(work[1])).className, / on$/);
  render({page: 'actions'}); assert.ok(!props(find(work[1])).className.endsWith(' on'));
  render({me: {...settings.me, tabs: oz}, allTabs: oz, page: 'tab', tab: 'mgr_actions'});
  assert.ok(find(work[0])); assert.equal(find(work[1]), undefined); assert.equal(find(work[2]), undefined);
  render({me: {...settings.me, tabs: wb.filter(t => t.key !== 'entry_points')}, allTabs: wb, hidden: ['entry_points']});
  assert.equal(find(work[1]), undefined);
  click(find('Какие вкладки показывать в меню'));
  const labels = walk(box).filter(n => n.tagName === 'LABEL');
  const entry = labels.find(n => n.textContent === 'Точки входа'); assert.ok(entry, JSON.stringify(labels.map(n => n.textContent)));
  const input = walk(entry).find(n => n.tagName === 'INPUT'); assert.equal(props(input).checked, false);
  flushSync(() => props(input).onChange({target: {checked: true}})); assert.deepEqual(calls.at(-1), []);
  const group = entry.parentNode; assert.ok(group.textContent.includes('Работа с кабинетом'));
  click(find('Какие вкладки показывать в меню'));
  render({me: {...settings.me, tabs: wb}, hidden: [], compareEnabled: false, open: false});
  assert.equal(walk(box).filter(n => props(n).href === '/compare').length, 0);
  for(const name of work) {assert.ok(find(name)); assert.ok(!find(name).textContent.includes(name));}
  click(find(work[2])); assert.equal(calls.at(-1), 'photo_funnel');
  render({open: true});
  click(buttons().find(n => n.textContent.includes('Работа с кабинетом')));
  assert.equal(find(work[0]), undefined);
  const search=walk(box).find(n=>n.tagName==='INPUT'&&props(n).placeholder==='Найти вкладку…');
  flushSync(()=>props(search).onChange({target:{value:'точки'}}));
  assert.ok(find(work[1]),'search reveals a matching tab in the collapsed work group');
  flushSync(()=>props(search).onChange({target:{value:''}}));
  assert.equal(find(work[0]),undefined,'clearing search keeps the saved collapsed preference');
  click(buttons().find(n => n.textContent.includes('Работа с кабинетом')));
  assert.ok(find(work[0]));
  assert.deepEqual(warnings, []);
  console.log('Sidebar: order, no duplicates, real navigation, market switch, hidden preferences, compact/demo modes OK');
} finally {flushSync(() => root.unmount()); console.error = oldError;}
