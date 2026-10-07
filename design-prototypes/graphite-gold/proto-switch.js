(function () {
    const switcher = document.querySelector('.proto-switch');
    if (!switcher) return;

    const buttons = switcher.querySelectorAll('[data-screen]');
    const setScreen = (name) => {
        document.body.dataset.screen = name;
        buttons.forEach((btn) => {
            btn.classList.toggle('active', btn.dataset.screen === name);
        });
    };

    buttons.forEach((btn) => {
        btn.addEventListener('click', () => setScreen(btn.dataset.screen));
    });

    document.querySelectorAll('[data-admin-tab]').forEach((btn) => {
        btn.addEventListener('click', () => {
            const panel = btn.dataset.adminTab;
            const root = btn.closest('.admin-workspace') || document;
            root.querySelectorAll('[data-admin-tab]').forEach((b) => {
                b.classList.toggle('active', b === btn);
            });
            root.querySelectorAll('[data-admin-panel]').forEach((p) => {
                p.classList.toggle('active', p.dataset.adminPanel === panel);
            });
        });
    });

    const params = new URLSearchParams(location.search);
    if (params.get('screen') === 'admin') setScreen('admin');
})();
