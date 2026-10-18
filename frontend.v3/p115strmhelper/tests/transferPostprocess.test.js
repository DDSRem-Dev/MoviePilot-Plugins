import assert from 'node:assert/strict';
import { test } from 'node:test';
import { effectScope } from 'vue';
import { useTransferPostprocess } from '../src/components/composables/useTransferPostprocess.js';

const key = 'a'.repeat(64);
const otherKey = 'b'.repeat(64);
const statusResponse = (state = 'superseded', size = 1000) => ({
  code: 0, data: { key, state, size, cloud_path: '/电影/a.mkv', local_path: '/媒体/a.strm' },
});

function setup(t, api) {
  const scope = effectScope();
  const state = scope.run(() => useTransferPostprocess({ ...api, get: (url, options) => {
    if (url.endsWith('/transfer_postprocess_list')) return { code: 0, data: { items: [], total: 0 } };
    return api.get(url, options);
  } }, 'InstancePlugin'));
  t.after(() => scope.stop());
  state.eventKey.value = key;
  return state;
}

test('invalid input never requests; valid input uses the injected API and plugin ID', async (t) => {
  const calls = [];
  const state = setup(t, { get: async (...args) => {
    calls.push(args);
    return statusResponse('pending', 0);
  } });
  state.eventKey.value = 'invalid';
  await state.query();
  assert.equal(calls.length, 0);
  state.eventKey.value = ` ${key.toUpperCase()} `;
  await state.query();
  assert.deepEqual(calls[0], ['plugin/InstancePlugin/transfer_postprocess_status', {
    params: { key }, timeout: 30000,
  }]);
  assert.equal(state.record.value.size, 0);
  assert.equal(state.canRetry.value, true);
  state.eventKey.value = otherKey;
  assert.equal(state.record.value, null);
  assert.equal(state.canRetry.value, false);
});

test('list pagination and filters clear selection; selecting a row rechecks current status', async (t) => {
  const calls = [];
  const scope = effectScope();
  t.after(() => scope.stop());
  const state = scope.run(() => useTransferPostprocess({ get: async (url, options) => {
    calls.push({ url, options });
    return url.endsWith('_list')
      ? { code: 0, data: { items: [statusResponse().data], total: 21 } }
      : statusResponse('done');
  } }, 'InstancePlugin'));
  await state.loadList();
  assert.deepEqual(calls[0], { url: 'plugin/InstancePlugin/transfer_postprocess_list', options: {
    params: { state: 'unfinished', page: 1, page_size: 20 }, timeout: 30000,
  } });
  assert.equal(state.pageCount.value, 2);
  assert.equal(state.canRetry.value, false);
  await state.selectRecord(state.records.value[0]);
  assert.equal(state.record.value.state, 'done');
  assert.equal(state.canRetry.value, false);
  state.filter.value = 'all';
  await state.loadList(2);
  assert.equal(state.page.value, 2);
  assert.equal(state.record.value, null);
  assert.equal(state.eventKey.value, '');
  assert.equal(calls.at(-1).options.params.state, 'all');
});

test('retry refreshes list and returns to the last page when its final record completes', async (t) => {
  const scope = effectScope();
  t.after(() => scope.stop());
  let completed = false;
  const state = scope.run(() => useTransferPostprocess({
    get: async (url) => url.endsWith('_list')
      ? { code: 0, data: { items: completed ? [] : [statusResponse().data], total: completed ? 20 : 21 } }
      : statusResponse(completed ? 'done' : 'pending'),
    post: async () => { completed = true; return { code: 0, msg: '后处理完成' }; },
  }, 'InstancePlugin'));
  await state.loadList(2);
  await state.selectRecord(state.records.value[0]);
  await state.retry();
  assert.equal(state.page.value, 1);
  assert.equal(state.total.value, 20);
  assert.equal(state.record.value.state, 'done');
  assert.equal(state.feedback.value.type, 'success');
});

test('empty lists, list failures and overlapping loads never leave actionable stale records', async (t) => {
  const scope = effectScope();
  t.after(() => scope.stop());
  let resolve;
  let count = 0;
  const state = scope.run(() => useTransferPostprocess({ get: () => {
    count += 1;
    return new Promise(done => { resolve = done; });
  } }, 'InstancePlugin'));
  const loading = state.loadList();
  await state.loadList();
  await state.selectRecord({ key });
  assert.equal(count, 1);
  resolve({ code: -1, msg: '服务已停止' });
  await loading;
  assert.equal(state.listError.value, '服务已停止');
  assert.equal(state.canRetry.value, false);
  const empty = state.loadList();
  resolve({ code: 0, data: { items: [], total: 0 } });
  await empty;
  assert.equal(state.listError.value, '');
  assert.equal(state.total.value, 0);
  assert.deepEqual(state.records.value, []);
});

test('stale query results are ignored and overlapping queries are blocked', async (t) => {
  let resolve;
  let count = 0;
  const state = setup(t, { get: () => {
    count += 1;
    return new Promise((done) => { resolve = done; });
  } });
  const pending = state.query();
  await state.query();
  state.eventKey.value = otherKey;
  resolve(statusResponse());
  await pending;
  assert.equal(count, 1);
  assert.equal(state.record.value, null);
  assert.equal(state.busy.value, false);
});

test('retry is gated by a queried eligible state', async (t) => {
  let count = 0;
  let result = statusResponse('done');
  const state = setup(t, { get: async () => result, post: async () => { count += 1; } });
  await state.retry();
  await state.query();
  await state.retry();
  result = statusResponse('unknown');
  await state.query();
  await state.retry();
  assert.equal(count, 0);
});

test('successful retry refreshes exact size and blocks duplicate submissions', async (t) => {
  let result = statusResponse();
  let resolve;
  const calls = [];
  const state = setup(t, { get: async () => result, post: (...args) => {
    calls.push(args);
    return new Promise((done) => { resolve = done; });
  } });
  await state.query();
  const pending = state.retry();
  await state.retry();
  assert.equal(state.busy.value, true);
  assert.equal(state.canRetry.value, false);
  result = statusResponse('done', 1024);
  resolve({ code: 0, msg: '后处理完成' });
  await pending;
  assert.deepEqual(calls, [['plugin/InstancePlugin/transfer_postprocess_retry',
    { key }, { timeout: 120000 }]]);
  assert.equal(state.record.value.size, 1024);
  assert.equal(state.canRetry.value, false);
  assert.equal(state.feedback.value.type, 'success');
});

test('backend refusal is shown verbatim and latest state is fetched', async (t) => {
  const state = setup(t, {
    get: async () => statusResponse(),
    post: async () => ({ code: -1, msg: '本地文件已变更，不能恢复' }),
  });
  await state.query();
  await state.retry();
  assert.deepEqual(state.feedback.value, { type: 'warning', text: '本地文件已变更，不能恢复' });
  assert.equal(state.record.value.state, 'superseded');
});

test('interrupted retry requires a fresh query before another attempt', async (t) => {
  let count = 0;
  const state = setup(t, {
    get: async () => statusResponse('pending', null),
    post: async () => { count += 1; throw new Error('timeout'); },
  });
  await state.query();
  assert.equal(state.record.value.size, null);
  await state.retry();
  await state.retry();
  assert.equal(count, 1);
  assert.equal(state.record.value, null);
  assert.equal(state.canRetry.value, false);
  assert.match(state.feedback.value.text, /后台任务可能仍在执行/);
  await state.query();
  assert.equal(state.canRetry.value, true);
});

test('failed refresh clears actionable state but preserves the retry outcome', async (t) => {
  let fail = false;
  const state = setup(t, {
    get: async () => fail ? { code: -1, msg: '服务已停止' } : statusResponse(),
    post: async () => { fail = true; return { code: 0, msg: '后处理完成' }; },
  });
  await state.query();
  await state.retry();
  assert.equal(state.record.value, null);
  assert.equal(state.canRetry.value, false);
  assert.match(state.feedback.value.text, /后处理完成；状态刷新失败（服务已停止）/);
});

test('missing or mismatched records cannot enable retry', async (t) => {
  let result = { code: -1, msg: '后处理事件不存在' };
  const state = setup(t, { get: async () => result });
  await state.query();
  assert.equal(state.feedback.value.text, '后处理事件不存在');
  result = { code: 0, data: { key: otherKey, state: 'pending' } };
  await state.query();
  assert.equal(state.record.value, null);
  assert.equal(state.canRetry.value, false);
});

test('key changes and disposal invalidate in-flight retry results', async (t) => {
  let resolve;
  const scope = effectScope();
  t.after(() => scope.stop());
  const state = scope.run(() => useTransferPostprocess({
    get: async () => statusResponse(),
    post: () => new Promise((done) => { resolve = done; }),
  }, 'InstancePlugin'));
  state.eventKey.value = key;
  await state.query();
  const pending = state.retry();
  state.eventKey.value = otherKey;
  scope.stop();
  resolve({ code: 0, msg: '后处理完成' });
  await pending;
  assert.equal(state.record.value, null);
  assert.equal(state.feedback.value, null);
});
