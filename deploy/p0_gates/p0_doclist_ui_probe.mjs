/**
 * LIVE UI probe for the deployed document list (real Chrome over CDP).
 *
 * Usage (Chrome already launched with --remote-debugging-port=9222):
 *   node deploy/p0_gates/p0_doclist_ui_probe.mjs <datasetId> <expectedRows> <tokenFile> <tenantId>
 *
 * It signs the browser in by writing the app's own session keys into localStorage,
 * navigates to the real file-list route, and reports what the DOM shows: the rows, the
 * names they carry, the pager's count and whether the empty-state sentence appeared.
 * The token is read from a file so it never enters the repository or this script.
 */
import { readFileSync } from 'node:fs';

const [, , datasetId, expectedArg, tokenFile, tenantId] = process.argv;
const expected = Number(expectedArg);
const token = readFileSync(tokenFile, 'utf8').trim();
const ORIGIN = 'http://127.0.0.1';
const CDP = 'http://127.0.0.1:9222';

const targets = await (await fetch(`${CDP}/json/list`)).json();
const page = targets.find((target) => target.type === 'page');
if (!page) {
  throw new Error('no page target on the CDP endpoint');
}

const socket = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true });
  socket.addEventListener('error', reject, { once: true });
});

let nextId = 1;
const pending = new Map();
const consoleErrors = [];

socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data);
  if (message.id && pending.has(message.id)) {
    const { resolve, reject } = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) reject(new Error(JSON.stringify(message.error)));
    else resolve(message.result);
    return;
  }
  if (message.method === 'Runtime.exceptionThrown') {
    consoleErrors.push(
      String(message.params?.exceptionDetails?.exception?.description ?? '').slice(
        0,
        200,
      ),
    );
  }
  if (message.method === 'Log.entryAdded' && message.params?.entry?.level === 'error') {
    consoleErrors.push(String(message.params.entry.text).slice(0, 200));
  }
});

const send = (method, params = {}) =>
  new Promise((resolve, reject) => {
    const id = nextId++;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });

const evaluate = async (expression) => {
  const result = await send('Runtime.evaluate', {
    expression,
    returnByValue: true,
    awaitPromise: true,
  });
  return result.result?.value;
};

const waitFor = async (expression, timeoutMs = 60000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return null;
};

await send('Runtime.enable');
await send('Log.enable');
await send('Page.enable');

// The origin, so the session keys can be written before the app boots.
await send('Page.navigate', { url: `${ORIGIN}/` });
await waitFor('document.readyState === "complete"', 30000);

await evaluate(`
  localStorage.setItem('Authorization', ${JSON.stringify(token)});
  localStorage.setItem('token', ${JSON.stringify(token)});
  localStorage.setItem('userInfo', ${JSON.stringify(JSON.stringify({ name: 'doclist probe', email: 'probe@local' }))});
  localStorage.setItem('ragflow_active_tenant_id', ${JSON.stringify(tenantId ?? '')});
  localStorage.setItem('ragflow-ui-theme', 'light');
  localStorage.setItem('lng', 'zh');
  'session written'
`);

await send('Page.navigate', { url: `${ORIGIN}/dataset/files/${datasetId}` });

const settled = await waitFor(
  `(() => {
     const rows = document.querySelectorAll('[data-testid="document-row"]').length;
     const text = document.body.innerText || '';
     if (rows > 0) return 'rows';
     if (/暂无数据|No data available|加载失败|Failed to load the file list|没有查看该数据集文件的权限/.test(text)) return 'state';
     return '';
   })()`,
  90000,
);

const summary = await evaluate(`(() => {
  const rows = [...document.querySelectorAll('[data-testid="document-row"]')];
  const text = document.body.innerText || '';
  return {
    path: location.pathname,
    documentIdInPath: location.pathname.split('/').pop(),
    rowCount: rows.length,
    rowNames: rows.map((row) => row.getAttribute('data-doc-name')),
    pagerCount: (text.match(/共\\s*\\d+\\s*条/) || text.match(/Total\\s*\\d+/i) || [null])[0],
    showsEmptyCopy: /暂无数据|No data available/.test(text),
    showsLoadingCopy: /正在加载文件列表|Loading the file list/.test(text),
    showsFailureCopy: /加载失败|Failed to load the file list/.test(text),
    showsForbiddenCopy: /没有查看该数据集文件的权限|do not have permission/.test(text),
    redirectedToLogin: location.pathname.startsWith('/login'),
    bodySample: text.replace(/\\s+/g, ' ').slice(0, 300),
  };
})()`);

console.log(
  JSON.stringify(
    {
      datasetId,
      expectedRows: expected,
      settled,
      ...summary,
      consoleErrors,
      pass:
        summary.rowCount === expected &&
        summary.showsEmptyCopy === false &&
        summary.redirectedToLogin === false,
    },
    null,
    2,
  ),
);

socket.close();
process.exit(0);
