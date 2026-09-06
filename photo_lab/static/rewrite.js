(() => {
  const statusText = { idle: '空闲', running: '运行中', done: '已完成', stopped: '已停止', error: '失败' };
  const cards = [...document.querySelectorAll('[data-category]')];

  async function readStatus(category) {
    const response = await fetch(`api/rewrite/status?category=${encodeURIComponent(category)}`);
    if (!response.ok) throw new Error(`状态读取失败（HTTP ${response.status}）`);
    return response.json();
  }

  function render(card, result) {
    const running = result.status === 'running';
    card.querySelector('[data-status]').textContent = statusText[result.status] || result.status;
    card.querySelector('[data-memory]').textContent = `类别记忆：${result.memory_chars || 0} 字 · 文件：qwen_preference_memory.json`;
    card.querySelector('[data-memory-text]').textContent = result.memory || '暂无类别记忆';
    const button = card.querySelector('[data-action]');
    button.querySelector('span').textContent = running ? '停止任务' : '启动任务';
    button.classList.toggle('is-running', running);
    button.disabled = false;
    const logs = card.querySelector('[data-logs]');
    logs.textContent = result.logs?.length ? result.logs.join('\n') : '暂无日志';
    logs.scrollTop = logs.scrollHeight;
  }

  async function refresh(card) {
    const category = card.dataset.category;
    try {
      const result = await readStatus(category);
      render(card, result);
      if (result.status === 'running') window.setTimeout(() => refresh(card), 1200);
    } catch (error) {
      card.querySelector('[data-logs]').textContent = error.message || '状态读取失败';
    }
  }

  async function toggle(card) {
    const category = card.dataset.category;
    const button = card.querySelector('[data-action]');
    button.disabled = true;
    try {
      const current = await readStatus(category);
      if (current.status === 'running') {
        await fetch('api/rewrite/stop', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ category }) });
      } else {
        const value = (name) => card.querySelector(`[data-field="${name}"]`).value;
        const response = await fetch('api/rewrite/start', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ category, ctx: Number(value('ctx')), batch_size: Number(value('batch')), memory_every: Number(value('every')), image_batch_size: Number(value('image-batch')), prompt_extra: value('extra') })
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || `启动失败（HTTP ${response.status}）`);
      }
    } catch (error) {
      card.querySelector('[data-logs]').textContent = error.message || '操作失败';
    } finally {
      await refresh(card);
    }
  }

  cards.forEach((card) => {
    card.querySelector('[data-action]').addEventListener('click', () => toggle(card));
    refresh(card);
  });
})();
