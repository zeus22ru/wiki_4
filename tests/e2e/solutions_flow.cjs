// Real browser + real isolated Flask API. LLM, health and indexing are test doubles.
// Requires Playwright and a Python environment with the application's dependencies.
const {chromium} = require('playwright');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '../..');
const runDir = fs.mkdtempSync(path.join(os.tmpdir(), 'wiki4-solutions-e2e-'));
const readyFile = path.join(runDir, 'ready.json');
const screenshots = process.env.SOLUTIONS_SCREENSHOT_DIR || path.join(runDir, 'screenshots');
fs.mkdirSync(screenshots, {recursive: true});

async function waitReady(child) {
    const deadline = Date.now() + 30000;
    while (Date.now() < deadline) {
        if (fs.existsSync(readyFile)) return JSON.parse(fs.readFileSync(readyFile, 'utf8'));
        if (child.exitCode !== null) throw new Error(`Test backend exited with ${child.exitCode}`);
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    throw new Error('Isolated backend did not become ready');
}

async function json(request, method, url, data) {
    const response = await request[method](url, data === undefined ? {} : {data});
    assert.ok(response.ok(), `${method} ${url}: ${response.status()} ${await response.text()}`);
    return response.json();
}

(async () => {
    let log = '';
    const server = spawn(process.env.SOLUTIONS_PYTHON || 'python', [
        path.join(__dirname, 'solutions_server.py'), '--ready-file', readyFile,
    ], {cwd: root, env: {...process.env, PYTHONPATH: [root, path.join(root, '.venv/Lib/site-packages'), process.env.PYTHONPATH || ''].join(path.delimiter)}, windowsHide: true});
    server.stdout.on('data', data => { log += data.toString(); });
    server.stderr.on('data', data => { log += data.toString(); });
    let browser;
    try {
        const {url, sandbox} = await waitReady(server);
        browser = await chromium.launch({channel: 'chrome', headless: true});
        const context = await browser.newContext({viewport: {width: 1440, height: 960}});
        const errors = [];
        const page = await context.newPage();
        page.on('pageerror', error => errors.push(error.message));
        await page.route('**/*', route => {
            const target = new URL(route.request().url());
            if (target.origin !== url) return route.fulfill({body: '', contentType: 'text/plain'});
            if (target.pathname === '/api/health') return route.fulfill({json: {ollama: true, database: true, status: 'ok'}});
            if (target.pathname === '/api/chat/suggestions') return route.fulfill({json: {suggestions: []}});
            if (target.pathname === '/api/documents/related') return route.fulfill({json: {documents: []}});
            return route.continue();
        });
        const request = context.request;
        const chat = await json(request, 'post', `${url}/api/chats`, {title: 'Тест: восстановление печати'});
        await json(request, 'post', `${url}/api/chats/${chat.id}/messages`, {role: 'user', content: 'Принтер склада не печатает. Что проверить?'});
        const answer = await json(request, 'post', `${url}/api/chats/${chat.id}/messages`, {
            role: 'assistant', content: 'Проверьте подключение и перезапустите службу печати.',
            sources: [{title: 'Инструкция по печати', path: 'uploads/printer-guide.txt'}],
        });
        await page.addInitScript(id => localStorage.setItem('wiki4.activeChatId', String(id)), chat.id);
        await page.goto(url);
        await page.getByRole('button', {name: 'Проблема решена', exact: true}).waitFor();
        assert.equal(await page.locator('.feedback-controls').count(), 1);

        // Remaining interaction assertions use the stable DOM contract below.
        await runFlow({page, request, url, chat, answer, sandbox, screenshots});
        assert.deepEqual(errors, [], `Unexpected browser errors: ${errors.join('; ')}`);
        console.log(JSON.stringify({result: 'PASS', screenshots, sandbox, checks: 'guest confirmation, fallback draft, reload, admin publication, responsive layout, keyboard, no JS errors'}));
    } catch (error) {
        console.error(error);
        console.error(log.slice(-6000));
        process.exitCode = 1;
    } finally {
        if (browser) await browser.close();
        server.kill();
    }
})();

async function runFlow() {
    throw new Error('UI contract pending implementation');
}
