(() => {
  'use strict';
  const icon = (name) => `<i class="fa fa-${name}" aria-hidden="true"></i>`;
  const button = (action, title, symbol) => `<button type="button" data-preview-action="${action}" title="${title}" aria-label="${title}">${icon(symbol)}<span>${title}</span></button>`;

  class ImagePreview {
    constructor() {
      this.dialog = document.createElement('dialog');
      this.dialog.className = 'pai-image-preview';
      this.dialog.setAttribute('aria-labelledby', 'pai-preview-title');
      this.dialog.innerHTML = `<header class="pai-preview-header"><div><h2 id="pai-preview-title">图片预览</h2><span class="pai-preview-meta"></span></div>${button('close', '关闭预览', 'xmark')}</header>
        <div class="pai-preview-tools" role="toolbar" aria-label="图片工具">
          <div>${button('zoom-out', '缩小', 'minus')}<output class="pai-preview-scale" aria-label="缩放比例">—</output>${button('zoom-in', '放大', 'plus')}${button('fit', '适应窗口', 'expand')}${button('actual', '原始大小', 'arrows-to-circle')}</div>
          <div>${button('rotate-left', '向左旋转', 'rotate-left')}${button('rotate-right', '向右旋转', 'rotate-right')}${button('copy-image', '复制图片', 'copy')}${button('download', '下载图片', 'download')}</div>
        </div>
        <div class="pai-preview-stage" tabindex="0" aria-label="图片画布，可拖动、滚轮缩放"><img class="pai-preview-image" alt="预览图片" draggable="false" hidden><div class="pai-preview-state" role="status">正在加载原图…</div></div>
        <div class="pai-preview-feedback" role="status" aria-live="polite"></div>
        <footer class="pai-preview-prompt"><div><strong>提示词</strong>${button('copy-prompt', '复制提示词', 'copy')}</div><p tabindex="0"></p></footer>`;
      document.body.append(this.dialog);
      this.stage = this.dialog.querySelector('.pai-preview-stage');
      this.image = this.dialog.querySelector('img');
      this.message = this.dialog.querySelector('.pai-preview-feedback');
      this.loadState = this.dialog.querySelector('.pai-preview-state');
      this.scaleOutput = this.dialog.querySelector('.pai-preview-scale');
      this.sequence = 0;
      this.points = new Map();
      this.dialog.addEventListener('click', (event) => {
        const action = event.target.closest('[data-preview-action]')?.dataset.previewAction;
        if (action) this.action(action);
        else if (event.target === this.dialog) this.dialog.close();
      });
      this.dialog.addEventListener('close', () => {
        document.documentElement.classList.remove('pai-preview-open');
        this.sequence += 1;
        this.controller?.abort();
        this.points.clear();
        this.releaseImage();
        this.opener?.focus?.({ preventScroll: true });
      });
      window.addEventListener('keydown', (event) => {
        if (!this.dialog.open) return;
        if (event.key === 'Escape') { event.preventDefault(); this.dialog.close(); return; }
        if (event.ctrlKey || event.metaKey || event.altKey || event.target.closest('input,textarea')) return;
        const actions = { '+': 'zoom-in', '=': 'zoom-in', '-': 'zoom-out', '0': 'fit', r: 'rotate-right', R: 'rotate-left' };
        if (actions[event.key]) { event.preventDefault(); this.action(actions[event.key]); }
      }, { capture: true });
      this.stage.addEventListener('wheel', (event) => {
        event.preventDefault();
        if (this.ready) this.zoom(this.scale * (event.deltaY < 0 ? 1.12 : 1 / 1.12));
      }, { passive: false });
      this.stage.addEventListener('dblclick', () => { if (this.ready) this.fitted ? this.zoom(1) : this.fit(); });
      this.stage.addEventListener('pointerdown', (event) => {
        if (!this.ready || event.button !== 0) return;
        this.points.set(event.pointerId, { x: event.clientX, y: event.clientY });
        this.stage.setPointerCapture(event.pointerId);
        this.stage.classList.add('is-dragging');
      });
      this.stage.addEventListener('pointermove', (event) => {
        const previous = this.points.get(event.pointerId);
        if (!previous) return;
        const partner = [...this.points.entries()].find(([pointerId]) => pointerId !== event.pointerId)?.[1];
        if (partner) {
          const before = Math.hypot(previous.x - partner.x, previous.y - partner.y);
          const after = Math.hypot(event.clientX - partner.x, event.clientY - partner.y);
          if (before > 5) this.zoom(this.scale * after / before);
        } else {
          this.offsetX += event.clientX - previous.x;
          this.offsetY += event.clientY - previous.y;
          this.render();
        }
        this.points.set(event.pointerId, { x: event.clientX, y: event.clientY });
      });
      for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) {
        this.stage.addEventListener(name, (event) => {
          this.points.delete(event.pointerId);
          if (!this.points.size) this.stage.classList.remove('is-dragging');
        });
      }
      new ResizeObserver(() => { if (this.dialog.open && this.ready && this.fitted) this.fit(); }).observe(this.stage);
    }

    releaseImage() {
      if (this.objectUrl) URL.revokeObjectURL(this.objectUrl);
      this.objectUrl = null;
      this.blob = null;
      this.ready = false;
      this.image.removeAttribute('src');
      this.image.hidden = true;
    }

    async open({ url, prompt = '', filename = '' }) {
      const source = new URL(url, location.href);
      if (!['http:', 'https:', 'blob:', 'data:'].includes(source.protocol)) return;
      this.controller?.abort();
      this.releaseImage();
      const sequence = ++this.sequence;
      this.controller = new AbortController();
      this.opener = document.activeElement;
      this.prompt = String(prompt || '');
      this.filename = String(filename || source.searchParams.get('filename') || source.pathname.split('/').pop() || 'image.png').replace(/[\\/:*?"<>|\x00-\x1f]/g, '_');
      this.angle = 0;
      this.scale = 1;
      this.offsetX = this.offsetY = 0;
      this.fitted = true;
      this.points.clear();
      this.message.textContent = '滚轮缩放 · 拖动移动 · Esc 关闭';
      this.loadState.hidden = false;
      this.loadState.textContent = '正在加载原图…';
      this.scaleOutput.textContent = '—';
      this.dialog.querySelector('.pai-preview-meta').textContent = '';
      this.dialog.querySelector('.pai-preview-prompt p').textContent = this.prompt || '此图片未记录提示词';
      this.dialog.querySelectorAll('button').forEach((control) => { control.disabled = !['close', 'copy-prompt'].includes(control.dataset.previewAction); });
      this.dialog.querySelector('[data-preview-action="copy-prompt"]').disabled = !this.prompt;
      if (!this.dialog.open) this.dialog.showModal();
      document.documentElement.classList.add('pai-preview-open');
      this.dialog.querySelector('[data-preview-action="close"]').focus();
      try {
        const response = await fetch(source.href, { signal: this.controller.signal });
        if (!response.ok) throw new Error(`图片加载失败（${response.status}）`);
        const blob = await response.blob();
        if (sequence !== this.sequence) return;
        if (!blob.type.startsWith('image/')) throw new Error('返回内容不是图片，请重新登录或重试');
        this.blob = blob;
        this.objectUrl = URL.createObjectURL(blob);
        this.image.src = this.objectUrl;
        await this.image.decode();
        if (sequence !== this.sequence) return;
        this.ready = true;
        this.image.hidden = false;
        this.loadState.hidden = true;
        this.dialog.querySelectorAll('button').forEach((control) => { control.disabled = control.dataset.previewAction === 'copy-prompt' && !this.prompt; });
        this.fit();
      } catch (error) {
        if (sequence !== this.sequence || error.name === 'AbortError') return;
        this.loadState.textContent = `${error.message || '图片加载失败'}，请关闭后重试`;
      }
    }

    fit() {
      if (!this.ready) return;
      const rotated = this.angle % 180 !== 0;
      const width = rotated ? this.image.naturalHeight : this.image.naturalWidth;
      const height = rotated ? this.image.naturalWidth : this.image.naturalHeight;
      this.scale = Math.min(Math.max(1, this.stage.clientWidth - 24) / width, Math.max(1, this.stage.clientHeight - 24) / height);
      this.offsetX = this.offsetY = 0;
      this.fitted = true;
      this.render();
    }

    zoom(scale) {
      this.scale = Math.min(8, Math.max(.02, scale));
      this.fitted = false;
      this.render();
    }

    render() {
      this.image.style.width = `${this.image.naturalWidth}px`;
      this.image.style.height = `${this.image.naturalHeight}px`;
      this.image.style.transform = `translate(-50%, -50%) translate(${this.offsetX}px, ${this.offsetY}px) rotate(${this.angle}deg) scale(${this.scale})`;
      this.scaleOutput.textContent = `${Math.round(this.scale * 100)}%`;
      this.dialog.querySelector('.pai-preview-meta').textContent = `${this.image.naturalWidth} × ${this.image.naturalHeight} · ${this.angle}°`;
      this.dialog.querySelector('[data-preview-action="zoom-in"]').disabled = this.scale >= 8;
      this.dialog.querySelector('[data-preview-action="zoom-out"]').disabled = this.scale <= .02;
    }

    png() {
      const canvas = document.createElement('canvas');
      const rotated = this.angle % 180 !== 0;
      canvas.width = rotated ? this.image.naturalHeight : this.image.naturalWidth;
      canvas.height = rotated ? this.image.naturalWidth : this.image.naturalHeight;
      const drawing = canvas.getContext('2d');
      drawing.translate(canvas.width / 2, canvas.height / 2);
      drawing.rotate(this.angle * Math.PI / 180);
      drawing.drawImage(this.image, -this.image.naturalWidth / 2, -this.image.naturalHeight / 2);
      return new Promise((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('图片转换失败')), 'image/png'));
    }

    async action(action) {
      if (action === 'close') { this.dialog.close(); return; }
      if (!this.ready && action !== 'copy-prompt') return;
      if (action === 'fit') { this.fit(); return; }
      if (action === 'actual') { this.offsetX = this.offsetY = 0; this.zoom(1); return; }
      if (action.startsWith('zoom-')) { this.zoom(this.scale * (action === 'zoom-in' ? 1.25 : .8)); return; }
      if (action.startsWith('rotate-')) { this.angle = (this.angle + (action === 'rotate-left' ? 270 : 90)) % 360; this.fit(); return; }
      const control = this.dialog.querySelector(`[data-preview-action="${action}"]`);
      const sequence = this.sequence;
      control.disabled = true;
      this.message.textContent = '正在处理…';
      try {
        if (action === 'copy-prompt') {
          if (!navigator.clipboard?.writeText) throw new Error('当前环境不支持剪贴板，请选中下方提示词手动复制');
          await navigator.clipboard.writeText(this.prompt);
        } else if (action === 'copy-image') {
          if (!navigator.clipboard?.write || !window.ClipboardItem) throw new Error('当前环境不支持复制图片，请使用下载');
          await navigator.clipboard.write([new ClipboardItem({ 'image/png': this.png() })]);
        } else if (action === 'download') {
          const filename = this.angle ? `${this.filename.replace(/\.[^.]+$/, '')}-rotated-${this.angle}.png` : this.filename;
          const blob = this.angle ? await this.png() : this.blob;
          if (sequence !== this.sequence) return;
          const address = URL.createObjectURL(blob);
          const link = document.createElement('a');
          link.href = address;
          link.download = filename;
          document.body.append(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(address), 30000);
        }
        if (sequence === this.sequence) this.message.textContent = { 'copy-prompt': '提示词已复制', 'copy-image': '图片已复制', download: '已发起图片下载' }[action];
      } catch (error) {
        if (sequence === this.sequence) this.message.textContent = error.name === 'NotAllowedError' ? '剪贴板权限被拒绝，请允许后重试，或使用下载' : error.message || '操作失败，请重试';
      } finally {
        if (sequence === this.sequence) control.disabled = false;
      }
    }
  }

  let viewer;
  window.WorkspaceImagePreview = { open(options) { viewer ||= new ImagePreview(); return viewer.open(options); } };
})();
