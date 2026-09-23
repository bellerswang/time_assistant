const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../index.html'), 'utf8');
const bootstrapCode = html.slice(html.indexOf('        const DB ='), html.indexOf('        let firebaseAuth ='));
const tokenCode = html.slice(html.indexOf('        function isInvalidFirebaseSession'), html.indexOf('        async function saveTodoToCloud'));
const validationCode = html.slice(html.indexOf('        async function validateFirebaseSession'), html.indexOf('        async function signInToLoomi'));

function harness(statuses, tokenError) {
    const state = { signouts: 0, refreshes: [], requests: 0, started: 0, gate: false };
    const user = { getIdToken: async force => {
        state.refreshes.push(force);
        if (tokenError) throw tokenError;
        return force ? 'renewed' : 'cached';
    } };
    const context = vm.createContext({
        Headers, console, window: { LOOMI_PRIVATE_HOST: false }, firebaseUser: user, appLanguage: 'zh', authGateStickyError: '',
        firebaseAuth: { signOut: async () => { state.signouts++; context.firebaseUser = null; } },
        CONFIG: { BACKEND_URL: 'https://example.invalid' },
        fetch: async () => {
            const status = statuses[state.requests++] || 200;
            return { status, ok: status === 200, text: async () => 'Rejected' };
        },
        updateAuthAccountUi() {}, setAuthGateStatus() {}, showToast() {},
        setAuthGateVisible: value => { state.gate = value; },
        startAuthenticatedApp: () => { state.started++; },
    });
    vm.runInContext(tokenCode + validationCode, context);
    return { state, context, user };
}

test('private page initializes without the public Firebase config script', () => {
    const context = vm.createContext({
        window: { LOOMI_PRIVATE_HOST: true, location: { origin: 'https://loomi.example' } },
        localStorage: { getItem: () => null },
        console,
    });
    vm.runInContext(bootstrapCode + '\nglobalThis.privateBackendUrl = CONFIG.BACKEND_URL;', context);
    assert.equal(context.privateBackendUrl, 'https://loomi.example');
});

test('expired access token refreshes once and succeeds without logout', async () => {
    const { state, context } = harness([401, 200]);
    assert.equal((await context.authFetch('/api/records')).status, 200);
    assert.deepEqual(state.refreshes, [false, true]);
    assert.equal(state.signouts, 0);
});

for (const status of [401, 403]) {
    test(`backend ${status} preserves login but blocks startup`, async () => {
        const { state, context, user } = harness([status, status]);
        await context.validateFirebaseSession(user);
        assert.equal(state.signouts, 0);
        assert.equal(context.firebaseUser, user);
        assert.equal(state.gate, true);
        assert.equal(state.started, 0);
    });
}

test('network error during token refresh preserves login', async () => {
    const { state, context } = harness([], { code: 'auth/network-request-failed' });
    await assert.rejects(context.authFetch('/api/records'));
    assert.equal(state.signouts, 0);
    assert.equal(state.requests, 0);
});

test('invalid Firebase credential signs out and never starts app', async () => {
    const { state, context, user } = harness([], { code: 'auth/user-token-expired' });
    await context.validateFirebaseSession(user);
    assert.equal(state.signouts, 1);
    assert.equal(state.started, 0);
    assert.equal(state.requests, 0);
});

test('account switch during token retrieval prevents request', async () => {
    const { state, context, user } = harness([]);
    user.getIdToken = async () => { context.firebaseUser = null; return 'old'; };
    await assert.rejects(context.authFetch('/api/records'));
    assert.equal(state.requests, 0);
    assert.equal(state.signouts, 0);
});

test('private host uses its session cookie without requesting a Firebase token', async () => {
    const { state, context, user } = harness([200]);
    context.window.LOOMI_PRIVATE_HOST = true;
    user.getIdToken = async () => { throw new Error('Firebase must not be used'); };
    const response = await context.authFetch('/api/records');
    assert.equal(response.status, 200);
    assert.equal(state.requests, 1);
    assert.deepEqual(state.refreshes, []);
});
