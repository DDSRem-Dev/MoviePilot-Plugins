import { computed, onScopeDispose, ref, watch } from 'vue';

export function useTransferPostprocess(api, pluginId) {
  const eventKey = ref('');
  const key = computed(() => eventKey.value.trim().toLowerCase());
  const validKey = computed(() => /^[0-9a-f]{64}$/.test(key.value));
  const record = ref(null);
  const feedback = ref(null);
  const records = ref([]);
  const filter = ref('unfinished');
  const page = ref(1);
  const total = ref(0);
  const pageSize = 20;
  const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));
  const listError = ref('');
  const operation = ref('');
  const busy = computed(() => Boolean(operation.value));
  const canRetry = computed(() => !busy.value && validKey.value
    && record.value?.key === key.value
    && ['pending', 'superseded'].includes(record.value?.state));
  let revision = 0;

  watch(eventKey, () => {
    revision += 1;
    record.value = null;
    feedback.value = null;
  }, { flush: 'sync' });
  onScopeDispose(() => { revision += 1; });

  async function fetchList(requestPage, requestRevision) {
    listError.value = '';
    try {
      const response = await api.get(`plugin/${pluginId}/transfer_postprocess_list`, {
        params: { state: filter.value, page: requestPage, page_size: pageSize }, timeout: 30000,
      });
      if (revision !== requestRevision) return;
      if (response?.code !== 0 || !Array.isArray(response.data?.items)) {
        throw new Error(response?.msg || '记录列表加载失败');
      }
      const lastPage = Math.max(1, Math.ceil(response.data.total / pageSize));
      if (requestPage > lastPage) return await fetchList(lastPage, requestRevision);
      records.value = response.data.items;
      total.value = response.data.total;
      page.value = requestPage;
    } catch (error) {
      if (revision !== requestRevision) return;
      records.value = [];
      total.value = 0;
      page.value = 1;
      listError.value = error.message || '记录列表加载失败，请刷新重试';
    }
  }

  async function loadList(requestPage = 1) {
    if (busy.value) return;
    eventKey.value = '';
    record.value = null;
    feedback.value = null;
    operation.value = 'list';
    try {
      await fetchList(requestPage, revision);
    } finally {
      operation.value = '';
    }
  }

  async function selectRecord(item) {
    if (busy.value) return;
    eventKey.value = item.key;
    await query();
  }

  async function fetchStatus(requestKey) {
    const response = await api.get(`plugin/${pluginId}/transfer_postprocess_status`, {
      params: { key: requestKey }, timeout: 30000,
    });
    if (response?.code !== 0) {
      throw new Error(response?.msg || '查询失败，请稍后重试');
    }
    if (response.data?.key !== requestKey || !response.data?.state) {
      throw new Error('返回的事件状态无效，请重新查询');
    }
    return response.data;
  }

  async function query() {
    if (busy.value || !validKey.value) return;
    const requestKey = key.value;
    const requestRevision = revision;
    operation.value = 'query';
    record.value = null;
    feedback.value = null;
    try {
      const result = await fetchStatus(requestKey);
      if (revision === requestRevision) record.value = result;
    } catch (error) {
      if (revision === requestRevision) {
        feedback.value = { type: 'error', text: error.message || '查询失败，请稍后重试' };
      }
    } finally {
      operation.value = '';
    }
  }

  async function retry() {
    if (!canRetry.value) return;
    const requestKey = key.value;
    const requestRevision = revision;
    operation.value = 'retry';
    feedback.value = null;
    try {
      const response = await api.post(`plugin/${pluginId}/transfer_postprocess_retry`,
        { key: requestKey }, { timeout: 120000 });
      if (revision !== requestRevision) return;
      const result = {
        type: response?.code === 0 ? 'success' : 'warning',
        text: response?.msg || '未能确认处理结果，请查询状态',
      };
      record.value = null;
      try {
        const latest = await fetchStatus(requestKey);
        if (revision !== requestRevision) return;
        record.value = latest;
        feedback.value = result;
      } catch (error) {
        if (revision !== requestRevision) return;
        feedback.value = {
          type: 'warning',
          text: `${result.text}；状态刷新失败（${error.message}），请重新查询后再操作`,
        };
      }
      if (revision === requestRevision) await fetchList(page.value, requestRevision);
    } catch {
      if (revision !== requestRevision) return;
      record.value = null;
      feedback.value = {
        type: 'warning',
        text: '请求中断，后台任务可能仍在执行。请先查询状态，再决定是否重试',
      };
    } finally {
      operation.value = '';
    }
  }

  return {
    eventKey, validKey, record, feedback, operation, busy, canRetry, query, retry,
    records, filter, page, total, pageCount, listError, loadList, selectRecord,
  };
}
