// Full instants use the browser's zone. Source dates without a time stay dates.
function localizeTimestamps(scope = document) {
 const formatter = new Intl.DateTimeFormat(undefined, {
  year: 'numeric', month: 'short', day: 'numeric',
  hour: '2-digit', minute: '2-digit', timeZoneName: 'short'
 });
 const nodes = [...scope.querySelectorAll('time[data-local-time]')];
 if (scope.matches?.('time[data-local-time]')) nodes.unshift(scope);
 for (const node of nodes) {
  const date = new Date(node.getAttribute('datetime'));
  if (!Number.isFinite(date.getTime())) continue;
  const text = formatter.format(date);
  if (node.textContent !== text) node.textContent = text;
  node.title = text;
 }
}
try { localizeTimestamps(); } catch { /* Keep the explicit UTC fallback. */ }
new MutationObserver(records => {
 for (const record of records) {
  for (const node of record.addedNodes) {
   if (node.nodeType !== Node.ELEMENT_NODE) continue;
   try { localizeTimestamps(node); } catch { /* Keep UTC. */ }
  }
 }
}).observe(document.body, { childList: true, subtree: true });
