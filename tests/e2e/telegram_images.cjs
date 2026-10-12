// Run with Node.js and Playwright installed: node tests/e2e/telegram_images.cjs
// Exercises the real Mini App UI with isolated API and Telegram responses.
const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=', 'base64');
const file = {name: 'screen.png', mimeType: 'image/png', buffer: png};

(async () => {
    const browser = await chromium.launch({channel: 'chrome', headless: true});
    try {
        const page = await browser.newPage({viewport: {width: 390, height: 844}});
        const errors = [];
        page.on('pageerror', error => errors.push(error.message));
        let uploads = 0, rejectUpload = false, rejectSend = false, sent;
        const attachment = {id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee', kind: 'image', filename: 'screen.png'};
        await page.route('**/*', async route => {
            const url = new URL(route.request().url());
            const json = (body, status = 200) => route.fulfill({status, json: body});
            if (url.pathname === '/telegram-app') {
                const html = fs.readFileSync(path.join(root, 'templates/telegram_app.html'), 'utf8')
                    .replace(/\{\{ url_for\('static', filename='([^']+)'\) \}\}/g, '/static/$1')
                    .replace('{{ attachment_max_count }}', '3').replace('{{ attachment_max_bytes }}', '5242880')
                    .replace(/{% if not attachments_enabled %}hidden{% endif %}/g, '')
                    .replace('{{ telegram_bot_username|e }}', 'test_bot');
                return route.fulfill({contentType: 'text/html', body: html});
            }
            if (url.pathname.startsWith('/static/')) {
                return route.fulfill({body: fs.readFileSync(path.join(root, url.pathname)), contentType: url.pathname.endsWith('.js') ? 'application/javascript' : 'text/css'});
            }
            if (url.pathname === '/api/telegram/webapp/auth') return json({telegram_user: {first_name: 'Тест'}});
            if (url.pathname === '/api/chats') return json({chats: [{id: 'history', title: 'С картинкой'}]});
            if (url.pathname === '/api/chats/history') return json({messages: [{role: 'user', content: 'Скриншот', metadata: {attachments: [attachment]}}]});
            if (url.pathname === '/api/chat/attachments') {
                uploads++;
                return rejectUpload ? json({error: 'Ошибка загрузки'}, 400) : json({attachments: [attachment]}, 201);
            }
            if (url.pathname.startsWith('/api/chat/attachments/')) return route.fulfill({contentType: 'image/png', body: png});
            if (url.pathname === '/api/chat/stream') {
                sent = route.request().postDataJSON();
                return rejectSend ? json({error: 'Модель недоступна'}, 400) : route.fulfill({contentType: 'text/event-stream', body: 'data: {"type":"done","answer":"Вижу скриншот","chat_id":"history"}\n\n'});
            }
            return route.fulfill({body: '', contentType: 'application/javascript'});
        });
        await page.addInitScript(() => { window.Telegram = {WebApp: {initData: 'test'}}; });
        await page.goto('http://miniapp.test/telegram-app');
        await page.locator('#chatState').waitFor({state: 'visible'});
        const choose = async (files) => {
            await page.locator('#attachmentInput').setInputFiles(files);
            await page.waitForFunction(() => !document.getElementById('attachmentInput').disabled);
        };
        await choose(file);
        assert.equal(await page.locator('#attachmentPreview img').count(), 1);
        await page.locator('#attachmentPreview button').click();
        assert.equal(await page.locator('#attachmentPreview img').count(), 0);

        await choose(file);
        await page.locator('#sendButton').click();
        await page.waitForFunction(() => !document.getElementById('sendButton').disabled);
        assert.equal(sent.message, '');
        assert.deepEqual(sent.attachment_ids, [attachment.id]);
        assert.equal(await page.locator('.tg-message--user img').count(), 1);
        assert.equal(await page.locator('#attachmentPreview img').count(), 0);

        await page.locator('#historyButton').click();
        await page.locator('#chatList button').click();
        await page.waitForFunction(() => !document.getElementById('sendButton').disabled);
        assert.equal(await page.locator('.tg-message--user img').count(), 1);

        rejectUpload = true;
        await choose(file);
        assert.match(await page.locator('#attachmentStatus').textContent(), /Ошибка загрузки/);
        assert.equal(await page.locator('#attachmentPreview img').count(), 0);
        rejectUpload = false;
        await choose(file);
        rejectSend = true;
        await page.locator('#messageInput').fill('Что на картинке?');
        await page.locator('#sendButton').click();
        await page.waitForFunction(() => !document.getElementById('sendButton').disabled);
        assert.equal(await page.locator('#messageInput').inputValue(), 'Что на картинке?');
        assert.equal(await page.locator('#attachmentPreview img').count(), 1);

        await page.locator('#newChatButton').evaluate(button => button.click());
        const before = uploads;
        await choose([file, file, file, file]);
        assert.equal(uploads - before, 3);
        assert.match(await page.locator('#attachmentStatus').textContent(), /не более 3/);
        for (const width of [390, 1024]) {
            await page.setViewportSize({width, height: 844});
            assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
            if (process.env.IMAGE_TEST_SCREENSHOTS) {
                await page.screenshot({path: path.join(process.env.IMAGE_TEST_SCREENSHOTS, `telegram-images-${width}.png`)});
            }
        }
        assert.deepEqual(errors, []);
        console.log('PASS: image-only send, preview/removal, history, upload/send errors, count limit, mobile/desktop layout');
    } finally {
        await browser.close();
    }
})().catch(error => { console.error(error); process.exitCode = 1; });
