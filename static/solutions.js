/* Confirmed-solution workflow. Uses DOM nodes/textContent for user supplied data. */
(() => {
    const state = {sessionId: null, byMessage: new Map(), active: null, opener: null};
    const $ = (id) => document.getElementById(id);
    const modal = () => $('solutionModal');
    const api = async (url, options = {}) => {
        const response = await fetch(url, {credentials: 'same-origin', ...options});
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(data.error || 'Не удалось выполнить действие');
        return data;
    };
    const setText = (id, value) => { const el = $(id); if (el) el.textContent = value || ''; };
    const setBusy = (busy) => {
        ['solutionPrepareBtn', 'solutionSubmitBtn'].forEach((id) => { if ($(id)) $(id).disabled = busy; });
        setText('solutionMessage', busy ? 'Сохраняем…' : '');
    };
    const statusText = (solution) => ({resolved: 'Отмечено', draft: 'Черновик сохранён', pending: 'На проверке', published: 'Опубликовано, требуется индексация', linked: 'Связано со статьёй', rejected: 'Отклонено'})[solution.status] || solution.status;
    const fields = ['title', 'problem', 'conditions', 'solution', 'verification', 'reason'];
    const fieldId = (name) => name === 'title' ? 'solutionArticleTitle' : `solution${name[0].toUpperCase()}${name.slice(1)}`;
    const fill = (solution) => fields.forEach((name) => { const el = $(fieldId(name)); if (el) el.value = solution[name] || ''; });
    const values = () => Object.fromEntries(fields.map((name) => [name, $(fieldId(name))?.value || '']));
    const selectedKind = () => document.querySelector('input[name="solutionKind"]:checked')?.value || 'answer';
    function open(solution, opener) {
        state.active = solution; state.opener = opener || document.activeElement;
        const node = modal(); if (!node) return;
        fill(solution);
        $('solutionKind').value = solution.resolution_kind || 'answer';
        $('solutionClarification').value = solution.clarification || '';
        $('solutionDraftFields').hidden = solution.status !== 'draft';
        $('solutionPrepareBtn').hidden = solution.status !== 'resolved';
        $('solutionSubmitBtn').hidden = solution.status !== 'draft';
        setText('solutionStatus', statusText(solution)); setText('solutionMessage', 'Проверьте, что в тексте нет персональных данных и секретов.');
        node.hidden = false; document.body.classList.add('solution-modal-open');
        window.setTimeout(() => $('solutionKind')?.focus(), 0);
    }
    function close() {
        const node = modal(); if (!node) return; node.hidden = true; document.body.classList.remove('solution-modal-open');
        state.opener?.focus?.(); state.active = null;
    }
    async function confirm(messageId, button) {
        if (!state.sessionId || !messageId) return;
        button.disabled = true;
        try {
            const data = await api('/api/solutions', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({session_id: state.sessionId, message_id: Number(messageId)})});
            state.byMessage.set(String(messageId), data.solution);
            button.textContent = statusText(data.solution); button.classList.add('is-confirmed');
            open(data.solution, button);
        } catch (error) { button.disabled = false; button.textContent = error.message; }
    }
    async function prepare() {
        if (!state.active) return;
        const kind = selectedKind(), clarification = $('solutionClarification').value;
        setBusy(true);
        try {
            const data = await api(`/api/solutions/${state.active.id}/draft`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({kind, clarification})});
            state.active = data.solution; state.byMessage.set(String(data.solution.message_id), data.solution); fill(data.solution);
            $('solutionDraftFields').hidden = data.solution.status !== 'draft'; $('solutionPrepareBtn').hidden = data.solution.status !== 'resolved'; $('solutionSubmitBtn').hidden = data.solution.status !== 'draft';
            setText('solutionStatus', statusText(data.solution)); setText('solutionMessage', data.notice || 'Черновик готов. Его можно изменить перед отправкой.');
        } catch (error) { setText('solutionMessage', error.message); } finally { setBusy(false); }
    }
    async function submit() {
        if (!state.active) return;
        setBusy(true);
        try {
            let current = state.active;
            const updated = await api(`/api/solutions/${current.id}`, {method: 'PATCH', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({version: current.version, fields: values()})});
            current = updated.solution;
            const submitted = await api(`/api/solutions/${current.id}/submit`, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({version: current.version})});
            state.active = submitted.solution; state.byMessage.set(String(current.message_id), submitted.solution); fill(submitted.solution);
            $('solutionDraftFields').hidden = true; $('solutionSubmitBtn').hidden = true; setText('solutionStatus', statusText(submitted.solution)); setText('solutionMessage', 'Заявка отправлена на проверку.');
        } catch (error) { setText('solutionMessage', error.message); } finally { setBusy(false); }
    }
    async function setSession(sessionId) {
        state.sessionId = sessionId || null; state.byMessage.clear();
        if (!sessionId) return;
        try { const data = await api(`/api/solutions?session_id=${encodeURIComponent(sessionId)}`); (data.solutions || []).forEach((item) => state.byMessage.set(String(item.message_id), item)); document.querySelectorAll('.solution-confirm-btn').forEach((button) => attach(button.closest('.message'), button.dataset.messageId)); } catch (_) { /* confirmation stays available offline/retryable */ }
    }
    function attach(messageEl, messageId) {
        if (!messageEl || !messageId || messageEl.querySelector('.solution-confirm-btn')) return;
        const content = messageEl.querySelector('.message-content'); if (!content) return;
        const button = document.createElement('button'); button.type = 'button'; button.className = 'solution-confirm-btn'; button.dataset.messageId = String(messageId);
        const known = state.byMessage.get(String(messageId)); button.textContent = known ? statusText(known) : 'Проблема решена'; if (known) button.classList.add('is-confirmed');
        button.addEventListener('click', () => { const item = state.byMessage.get(String(messageId)); return item ? open(item, button) : confirm(messageId, button); }); content.appendChild(button);
    }
    function init() {
        $('solutionCloseBtn')?.addEventListener('click', close); $('solutionCancelBtn')?.addEventListener('click', close); $('solutionBackdrop')?.addEventListener('click', close);
        $('solutionPrepareBtn')?.addEventListener('click', prepare); $('solutionSubmitBtn')?.addEventListener('click', submit);
        document.addEventListener('keydown', (event) => { if (event.key === 'Escape' && modal() && !modal().hidden) close(); });
    }
    window.SolutionsUI = {attach, setSession, open};
    document.addEventListener('DOMContentLoaded', init);
})();
