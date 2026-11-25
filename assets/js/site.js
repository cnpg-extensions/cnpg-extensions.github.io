const root = document.documentElement;
const media = matchMedia('(prefers-color-scheme: dark)');
let preference = 'system';
try { preference = localStorage.getItem('cnpg-mode') || 'system'; } catch {}
if (!['system', 'light', 'dark'].includes(preference)) preference = 'system';
const favicon = document.getElementById('site-favicon');
function applyFavicon() {
 if (favicon) favicon.href = media.matches ? favicon.dataset.dark : favicon.dataset.light;
}
applyFavicon();
media.addEventListener('change', applyFavicon);
const themeButton = document.querySelector('.theme-switcher');
const themeModes = ['system', 'light', 'dark'];
function applyMode() {
 root.dataset.mode = preference === 'system' ? (media.matches ? 'dark' : 'light') : preference;
 const next = themeModes[(themeModes.indexOf(preference) + 1) % themeModes.length];
 const label = `Theme: ${preference === 'system' ? 'System (automatic)' : preference === 'light' ? 'Light' : 'Dark'}. Switch to ${next === 'system' ? 'System' : next === 'light' ? 'Light' : 'Dark'}.`;
 if (themeButton) {
  themeButton.title = label;
  themeButton.setAttribute('aria-label', label);
  themeButton.querySelectorAll('[data-theme-icon]').forEach(icon => { icon.hidden = icon.dataset.themeIcon !== preference; });
 }
}
applyMode(); media.addEventListener('change', applyMode);
themeButton?.addEventListener('click', () => {
 preference = themeModes[(themeModes.indexOf(preference) + 1) % themeModes.length];
 try { localStorage.setItem('cnpg-mode', preference); } catch {}
 applyMode();
});
window.addEventListener('storage', event => {
 if (event.key !== 'cnpg-mode' && event.key !== null) return;
 preference = ['light', 'dark'].includes(event.newValue) ? event.newValue : 'system';
 applyMode();
});
const menu = document.getElementById('menu-toggle');
menu?.addEventListener('click', () => { const nav = document.getElementById('mobile-nav'); nav.hidden = !nav.hidden; menu.setAttribute('aria-expanded', String(!nav.hidden)); });
async function copyText(text, button, code) {
 let copied = false;
 try { await navigator.clipboard.writeText(text); copied = true; } catch { const field = document.createElement('textarea'); field.value = text; field.style.position = 'fixed'; field.style.opacity = '0'; document.body.append(field); field.select(); try { copied = document.execCommand('copy'); } catch {} field.remove(); button.focus(); }
 const original = button.innerHTML; const label = button.getAttribute('aria-label'); const title = button.title;
 button.disabled = true; button.textContent = copied ? 'Copied' : 'Select and copy';
 button.setAttribute('aria-label', button.textContent); button.title = button.textContent;
 if (!copied) { const range = document.createRange(); range.selectNodeContents(code); const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range); }
 setTimeout(() => { button.innerHTML = original; if (label) button.setAttribute('aria-label', label); else button.removeAttribute('aria-label'); button.title = title; button.disabled = false; }, 1800);
}
document.getElementById('copy')?.addEventListener('click', e => { const code = document.getElementById('alert-query'); copyText(code.textContent, e.currentTarget, code); });
document.querySelectorAll('.prose pre').forEach(pre => {
 const wrapper = document.createElement('div'); wrapper.className = 'code-with-copy';
 pre.before(wrapper); wrapper.append(pre);
 const button = document.createElement('button'); button.type = 'button'; button.className = 'copy-code';
 button.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="8" y="8" width="12" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/></svg>';
 button.title = 'Copy code'; button.setAttribute('aria-label', 'Copy code example');
 button.addEventListener('click', () => copyText(pre.textContent, button, pre)); wrapper.append(button);
});
const search = document.getElementById('extension-search');
if (search) {
 const grid = document.getElementById('catalog-grid'); const cards = [...grid.children];
 const filters = Object.fromEntries(['pg','distro','build','publisher'].map(name => [name, document.getElementById(`filter-${name}`)])); const sort = document.getElementById('catalog-sort');
 const latestBuilds = new Map(cards.map(card => {
  const dates = card.dataset.buildDates.trim().split(/\s+/).map(Date.parse).filter(Number.isFinite);
  return [card, dates.length ? Math.max(...dates) : null];
 }));
 function compareCards(a, b) {
  if (sort.value === 'newest' || sort.value === 'oldest') {
   const first = latestBuilds.get(a);
   const second = latestBuilds.get(b);
   if (first !== second) {
    if (first === null) return 1;
    if (second === null) return -1;
    return sort.value === 'newest' ? second - first : first - second;
   }
  }
  return a.dataset.name.localeCompare(b.dataset.name) * (sort.value === 'reverse' ? -1 : 1);
 }
 function restoreCatalog() {
  const params = new URLSearchParams(location.search);
  search.value = params.get('q') || '';
  Object.entries(filters).forEach(([name,f]) => { const value=params.get(name) || ''; f.value=[...f.options].some(o=>o.value===value)?value:''; });
  const requestedSort = params.get('sort');
  sort.value = [...sort.options].some(option => option.value === requestedSort) ? requestedSort : 'name';
  filter(false);
 }
 function filter(updateURL = true) { const words = search.value.toLowerCase().trim().split(/\s+/).filter(Boolean); let count = 0;
 cards.sort(compareCards).forEach(card => {
 const imageMatches = card.dataset.images.trim().split(/\s+/).some(image => {
  const [pg, distro] = image.split('/');
  return (!filters.pg.value || pg === filters.pg.value) && (!filters.distro.value || distro === filters.distro.value);
 });
 const matches = imageMatches && words.every(w => card.dataset.search.includes(w)) && (!filters.build.value || card.dataset.build === filters.build.value) && (!filters.publisher.value || card.dataset.publisher === filters.publisher.value);
 card.hidden = !matches; if (matches) count++; grid.append(card);
 });
 document.getElementById('result-count').textContent = `${count} ${count === 1 ? 'extension' : 'extensions'}`; document.getElementById('no-results').hidden = count > 0;
 const url = new URL(location.href); [['q',search.value],['sort',sort.value === 'name' ? '' : sort.value],...Object.entries(filters).map(([name,f]) => [name,f.value])].forEach(([k,v]) => v ? url.searchParams.set(k,v) : url.searchParams.delete(k)); if(updateURL) history.replaceState(null,'',url);
 }
 search.addEventListener('input',filter); [...Object.values(filters),sort].forEach(el => el.addEventListener('change',filter));
 document.getElementById('clear-filters').addEventListener('click',()=>{search.value='';Object.values(filters).forEach(f=>f.value='');sort.value='name';filter();search.focus();}); restoreCatalog(); window.addEventListener('popstate',restoreCatalog);
}
requestAnimationFrame(() => requestAnimationFrame(() => root.classList.add('ready')));

// Enhance ordinary document anchors into tabs; without JS all sections remain readable.
const detail = document.querySelector('.extension-redesign');
if (detail) {
 const nav = detail.querySelector('.detail-view-nav');
 const tabs = [...nav.querySelectorAll('[data-detail-view]')];
 const views = [...detail.querySelectorAll('.detail-view')];
 nav.setAttribute('role','tablist');
 tabs.forEach(tab => { tab.setAttribute('role','tab'); tab.id = `tab-${tab.dataset.detailView}`; tab.setAttribute('aria-controls',tab.dataset.detailView); });
 views.forEach(view => {view.setAttribute('role','tabpanel'); view.setAttribute('aria-labelledby',`tab-${view.id}`);});
 function scrollToTabs() {
  const top = detail.querySelector('.detail-view-start').getBoundingClientRect().top;
  if (top < 0) window.scrollTo({top: window.scrollY + top, behavior:'instant'});
 }
 function showView(id, updateURL = false) {
  const tabTop = detail.querySelector('.detail-view-start').getBoundingClientRect().top;
  const shouldScroll = updateURL && tabTop < 0;
  tabs.forEach(tab => {const selected = tab.dataset.detailView === id;tab.setAttribute('aria-selected',String(selected));tab.tabIndex = selected ? 0 : -1;});
  views.forEach(view => view.hidden = view.id !== id);
  const selectedTab = tabs.find(tab => tab.dataset.detailView === id);
  if (selectedTab) {
   const tabBounds = selectedTab.getBoundingClientRect(), navBounds = nav.getBoundingClientRect();
   if (tabBounds.left < navBounds.left) nav.scrollLeft -= navBounds.left - tabBounds.left;
   else if (tabBounds.right > navBounds.right) nav.scrollLeft += tabBounds.right - navBounds.right;
  }
  detail.querySelector('.inventory-controls').hidden = id === 'documentation' || id === 'versions';
  if (shouldScroll) requestAnimationFrame(() => {
   const top = detail.querySelector('.detail-view-start').getBoundingClientRect().top;
   window.scrollTo({top:window.scrollY + top,behavior:'instant'});
  });
  if(updateURL) { const url = new URL(location.href);url.pathname = new URL(tabs.find(tab => tab.dataset.detailView === id).href).pathname;url.hash = new URL(tabs.find(tab => tab.dataset.detailView === id).href).hash;history.pushState(null,'',url); }
 }
 tabs.forEach((tab,i) => {
  tab.addEventListener('click',e=>{e.preventDefault();showView(tab.dataset.detailView,true);});
  tab.addEventListener('keydown',e=>{let next;if(e.key==='ArrowRight')next=(i+1)%tabs.length;if(e.key==='ArrowLeft')next=(i+tabs.length-1)%tabs.length;if(e.key==='Home')next=0;if(e.key==='End')next=tabs.length-1;if(next!==undefined){e.preventDefault();tabs[next].focus({preventScroll:true});showView(tabs[next].dataset.detailView,true);}});
 });
 detail.querySelectorAll('[data-open-view]').forEach(link => link.addEventListener('click', event => {event.preventDefault();if(link.hasAttribute("data-clear-dependency-filters")){nameFilter.value="";licenseFilter.value="";advisoryFilter.checked=false;filterDependencies();}if(link.hasAttribute("data-filter-advisories")){nameFilter.value="";licenseFilter.value="";advisoryFilter.checked=true;filterDependencies();}showView(link.dataset.openView, true);tabs.find(tab => tab.dataset.detailView === link.dataset.openView)?.focus({preventScroll:true});}));
 const syncView = () => {
  const id = location.pathname.split('/').filter(Boolean).at(-1);
  const known = views.some(view => view.id === id);
  showView(known ? id : detail.dataset.defaultView);
  if (known && !location.hash) requestAnimationFrame(() => scrollToTabs());
 };
 syncView();
 window.addEventListener('popstate',syncView);
 const contents = detail.querySelector('.readme-nav');const contentsNav = contents.querySelector('nav');
 detail.querySelectorAll('.readme-content h2[id], .readme-content h3[id]').forEach(heading=>{const a=document.createElement('a');a.href=`#${heading.id}`;a.textContent=heading.textContent;a.className=heading.tagName==='H3'?'contents-subheading':'';contentsNav.append(a);});
 if(contentsNav.children.length){
  contents.hidden=false;
  const wideReadme=matchMedia('(min-width: 1200px)');
  const adaptContents=()=>{contents.querySelector('details').open=wideReadme.matches;};
  adaptContents();wideReadme.addEventListener('change',adaptContents);
 }
 const imageChoice=document.getElementById('image-choice');const panels=[...detail.querySelectorAll('.inventory-panel')];

 const dependencyFilters=detail.querySelector('.dependency-filters');
 const nameFilter=dependencyFilters.elements.package;
 const licenseFilter=dependencyFilters.elements.license;
 const advisoryFilter=dependencyFilters.elements.advisories;
 function filterDependencies() {
  const panel=detail.querySelector('#dependencies .inventory-panel:not([hidden])');
  const table=panel?.querySelector('.dependency-table');
  dependencyFilters.hidden=!table;
  if(!table)return;
  const scanned=table.dataset.scanned==='true';
  advisoryFilter.disabled=!scanned;
  advisoryFilter.closest('label').title=scanned?'Show packages with one or more Grype or OSV advisory matches':'No scan is available for this image';
  const rows=[...table.querySelectorAll('tbody tr')];
  const name=nameFilter.value.trim().toLowerCase();
  const license=licenseFilter.value.trim().toLowerCase();
  let count=0;
  rows.forEach(row=>{
   const matches=row.dataset.package.toLowerCase().includes(name)&&row.cells[1].textContent.toLowerCase().includes(license)&&(!advisoryFilter.checked||!scanned||Number(row.dataset.advisories)>0);
   row.hidden=!matches;if(matches)count++;
  });
  panel.querySelector('[data-filter-result]').textContent=`${count} of ${rows.length} packages`;
  panel.querySelector('.dependency-table-scroll').hidden=count===0;
  panel.querySelector('.dependency-no-results').hidden=count!==0;
 }
 dependencyFilters.addEventListener('submit',event=>event.preventDefault());
 dependencyFilters.addEventListener('input',filterDependencies);
 dependencyFilters.addEventListener('reset',()=>setTimeout(filterDependencies,0));
 const imageOptions=[...imageChoice.options];
 const firstVariant=imageOptions[0]?.dataset.variant;
 const defaultOption=imageOptions.find(option=>option.dataset.variant===firstVariant&&option.dataset.architecture==='amd64')||imageOptions[0];
 function showImage(updateURL){
  const selected=imageChoice.selectedOptions[0];
  if(!selected)return;
  const {variant,architecture}=selected.dataset;
  panels.forEach(panel=>panel.hidden=panel.dataset.variant!==variant||panel.dataset.architecture!==architecture);
  filterDependencies();
  if(updateURL){const url=new URL(location.href);url.searchParams.set('image',variant);url.searchParams.set('arch',architecture);url.searchParams.delete('dependency');history.replaceState(null,'',url);}
 }
 function restoreImage(){
  const params=new URLSearchParams(location.search);
  const variant=params.get('image')||firstVariant;
  const selected=imageOptions.find(option=>option.dataset.variant===variant&&option.dataset.architecture===(params.get('arch')||'amd64'))||imageOptions.find(option=>option.dataset.variant===variant)||defaultOption;
  if(selected)imageChoice.value=selected.value;
  showImage(false);syncView();
 }
 restoreImage();window.addEventListener('popstate',restoreImage);
 imageChoice.addEventListener('change',()=>showImage(true));
}

const extensionBrowser = document.querySelector('.extension-browser');
if (extensionBrowser) {
 const narrow = matchMedia('(max-width: 1000px)');
 const adaptBrowser = () => { extensionBrowser.open = !narrow.matches; };
 adaptBrowser(); narrow.addEventListener('change', adaptBrowser);
 const field = document.getElementById('sidebar-extension-search');
 const links = [...extensionBrowser.querySelectorAll('[data-extension-search]')];
 extensionBrowser.querySelector('.extension-browser-search').hidden = false;
 field.addEventListener('input', () => {
  const words = field.value.toLowerCase().trim().split(/\s+/).filter(Boolean);
  let count = 0;
  links.forEach(link => { link.hidden = !words.every(word => link.dataset.extensionSearch.includes(word)); if (!link.hidden) count++; });
  document.getElementById('sidebar-extension-count').textContent = `${count} ${count === 1 ? 'extension' : 'extensions'}`;
  extensionBrowser.querySelector('.sidebar-empty').hidden = count > 0;
 });
 // Scroll only the list, keeping the page and its deep-link position unchanged.
 const current = extensionBrowser.querySelector('[aria-current="page"]');
 if (current && extensionBrowser.open) {
  const list = extensionBrowser.querySelector('.extension-browser-list');
  list.scrollTop = current.offsetTop - list.offsetTop - list.clientHeight / 2;
 }
}

const guide = document.querySelector('.guide-page');
if (guide) {
 const outline = guide.querySelector('.guide-outline');
 const nav = outline.querySelector('nav');
 const content = guide.querySelector('.guide-content');
 content.querySelectorAll('h2, h3').forEach(section => {
  if (section.parentElement.closest('details')) return;
  const link = document.createElement('a');
  const anchor = section.id || section.querySelector('[id]')?.id;
  if (!anchor) return;
  link.href = `#${anchor}`;
  link.textContent = section.textContent.trim();
  if (section.tagName === 'H3') link.classList.add('outline-subheading');
  nav.append(link);
 });
 if (nav.children.length) {
  outline.hidden = false;
  const wide = matchMedia('(min-width: 1001px)');
  const adaptOutline = () => { outline.querySelector('details').open = wide.matches; };
  adaptOutline(); wide.addEventListener('change', adaptOutline);
 }
 function revealGuideAnchor() {
  let id; try { id = decodeURIComponent(location.hash.slice(1)); } catch { return; }
  const target = document.getElementById(id);
  if (!target || !content.contains(target)) return;
  for (let node = target; node && node !== content; node = node.parentElement) {
   if (node.matches('details')) node.open = true;
  }
  requestAnimationFrame(() => (target.closest('h2,h3') || target).scrollIntoView({block:'start'}));
 }
 window.addEventListener('hashchange', revealGuideAnchor);
 nav.addEventListener('click', event => {
  const link = event.target.closest('a');
  if (link && link.hash === location.hash) revealGuideAnchor();
 });
 revealGuideAnchor();
}

// Keep navigation within this site in the current tab; isolate offsite pages.
function setLinkTarget(link) {
 const url = new URL(link.getAttribute('href'), document.baseURI);
 const external = ['http:', 'https:'].includes(url.protocol) && url.origin !== location.origin;
 if (external) {
  link.target = '_blank';
  link.relList.add('noopener', 'noreferrer');
 } else {
  link.removeAttribute('target');
  link.relList.remove('noopener', 'noreferrer');
 }
}
document.querySelectorAll('a[href]').forEach(setLinkTarget);
new MutationObserver(records => {
 for (const record of records) {
  if (record.type === 'attributes') setLinkTarget(record.target);
  for (const node of record.addedNodes) {
   if (node.nodeType !== Node.ELEMENT_NODE) continue;
   if (node.matches('a[href]')) setLinkTarget(node);
   node.querySelectorAll('a[href]').forEach(setLinkTarget);
  }
 }
}).observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['href']});
