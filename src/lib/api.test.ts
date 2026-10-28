import assert from 'node:assert/strict';
import { afterEach, mock, test } from 'node:test';
import { downloadsApi } from './api';

Object.defineProperty(globalThis, 'localStorage', {
  value: { getItem: () => null }, configurable: true,
});
afterEach(() => mock.restoreAll());

test('retry sends only the stored task ID and never deletes first', async () => {
  const calls: { url: string; method?: string; body?: BodyInit | null }[] = [];
  mock.method(globalThis, 'fetch', async (url: string, options: RequestInit) => {
    calls.push({ url, method: options.method, body: options.body });
    return Response.json({ task_id: 8, status: 'downloading', message: 'Download retry started' });
  });
  assert.equal((await downloadsApi.retryTask(7)).task_id, 8);
  assert.deepEqual(calls, [{ url: '/api/downloads/tasks/7/retry', method: 'POST', body: undefined }]);
});

test('failed retry retains an actionable validation message without another request', async () => {
  const network = mock.method(globalThis, 'fetch', async () => Response.json({
    detail: [{ loc: ['body', 'size_bytes'], msg: 'Field required', type: 'missing',
               input: { private_value: 'must not appear in the toast' } }],
  }, { status: 422 }));
  await assert.rejects(downloadsApi.retryTask(7), { message: 'size_bytes: Field required' });
  assert.equal(network.mock.callCount(), 1);
});

for (const [body, status, expected] of [
  [{ detail: 'Download already active' }, 409, 'Download already active'],
  [{ detail: { message: 'Retry import instead' } }, 400, 'Retry import instead'],
  [{ message: 'Service unavailable' }, 503, 'Service unavailable'],
  [null, 500, 'API request failed: 500'],
  [{ detail: { unexpected: { secret: 'hidden' } } }, 422, 'API request failed: 422'],
] as const) {
  test(`API errors stay readable for status ${status}: ${expected}`, async () => {
    mock.method(globalThis, 'fetch', async () => Response.json(body, { status }));
    await assert.rejects(downloadsApi.retryTask(7), { message: expected });
  });
}

test('non-JSON API failure includes its HTTP status', async () => {
  mock.method(globalThis, 'fetch', async () => new Response('<html>proxy error</html>', { status: 502 }));
  await assert.rejects(downloadsApi.retryTask(7), { message: 'API request failed: 502' });
});

test('retained import failures offer import retry instead of another download', async () => {
  const { canRetryImport } = await import('./download-actions');
  assert.equal(canRetryImport({ state: 'error', import_status: 'failed', download_path: '/downloads/fixture.epub' }), true);
  assert.equal(canRetryImport({ state: 'error', import_status: 'pending', download_path: null }), false);
  assert.equal(canRetryImport({ state: 'downloading', import_status: 'failed', download_path: '/downloads/fixture.epub' }), false);
  assert.equal(canRetryImport({ state: 'complete', import_status: 'imported', download_path: '/bookdrop/fixture.epub' }), false);
  assert.equal(canRetryImport({ state: 'seeding', import_status: 'pending', download_path: '/downloads/fixture.epub' }), true);
});
