// Videomail — клієнтська логіка під нову модель: НІЯКИХ «Надіслані» у UI.
// Користувач шле відео -> бачить повідомлення "очікуйте" -> перевіряє Inbox.

const API = '/api';
const EP = {
  auth:    `${API}/auth`,
  upload:  `${API}/upload`,
  inbox:   `${API}/inbox`,
  support: `${API}/support`
};

window.VM = (() => {
  const store = {
    get user() { try { return JSON.parse(localStorage.getItem('vm_user')||'null'); } catch { return null; } },
    set user(v){ if (!v) localStorage.removeItem('vm_user'); else localStorage.setItem('vm_user', JSON.stringify(v)); }
  };

  async function fetchJSON(url, opts = {}) {
    const r = await fetch(url, opts);
    const text = await r.text();
    let js = {};
    try { js = text ? JSON.parse(text) : {}; } catch(e) {}
    if (!r.ok) {
      const err = new Error(js.error || `http_${r.status}`);
      err.status = r.status; err.payload = js; err.raw = text;
      throw err;
    }
    return js;
  }

  function escapeHtml(s){ return (s||'').replace(/[&<>"']/g,c=>({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c])); }

  function initUI(){
    const u = store.user;
    const $  = s => document.querySelector(s);
    const on = (el, ev, fn) => el && el.addEventListener(ev, fn);

    const nickEl = $('#nick'), toast = $('#toast'), logoutBtn = $('#logoutBtn');
    const tabs = document.querySelectorAll('.tabs button');
    const panels = Array.from(document.querySelectorAll('[role="tabpanel"]'));

    // Record UI
    const preview = $('#preview'), startBtn = $('#startBtn'), stopBtn = $('#stopBtn'), sendBtn = $('#sendBtn');
    const timerEl = $('#timer'), sendInfo = $('#sendInfo');

    // Inbox
    const inboxList = $('#inboxList');

    // Support
    const supportList = $('#supportList'), supportMsg = $('#supportMsg'), supportSend = $('#supportSend'), supportInfo = $('#supportInfo');

    if (!u || !u.user_key) {
      nickEl && (nickEl.textContent = 'Гість');
      toast && (toast.textContent = 'Ви не авторизовані. Авторизуйтесь, щоб записувати та писати у підтримку.');
    } else {
      nickEl && (nickEl.textContent = u.nickname || u.user_key);
    }

    // Логаут: виносимо сміття і повертаємо на головну
    on(logoutBtn,'click',()=>{
      try { localStorage.removeItem('vm_user'); } catch {}
      try { localStorage.removeItem('user_key'); } catch {}
      try { localStorage.removeItem('nickname'); } catch {}
      try { localStorage.clear(); } catch {}
      location.href = '/';
    });

    tabs.forEach(btn => on(btn, 'click', () => {
      tabs.forEach(b => b.setAttribute('aria-current', String(b===btn)));
      panels.forEach(p => p.hidden = (p.id !== btn.dataset.tab));
      if (btn.dataset.tab === 'inbox') loadInbox();
      if (btn.dataset.tab === 'support') loadSupport();
    }));

    // ---------- Media ----------
    let mediaStream = null, recorder = null, chunks = [], tickTimer = null, startedAt = 0;

    function fmt(sec){ const m=Math.floor(sec/60), s=Math.floor(sec%60); return String(m).padStart(2,'0')+':'+String(s).padStart(2,'0'); }

    function pickMime(){
      const cand = [
        'video/webm;codecs=vp9,opus',
        'video/webm;codecs=vp8,opus',
        'video/webm',
        'video/mp4;codecs=avc1.42E01E,mp4a.40.2'
      ];
      if (!window.MediaRecorder) return '';
      for (const t of cand) { try { if (MediaRecorder.isTypeSupported(t)) return t; } catch{} }
      return '';
    }

    async function startPreview(){
      if (mediaStream && mediaStream.active) return;
      try {
        mediaStream = await navigator.mediaDevices.getUserMedia({
          video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 30 } },
          audio: { echoCancellation: true, noiseSuppression: true }
        });
        if (preview) { preview.srcObject = mediaStream; try { await preview.play(); } catch{} }
        toast && (toast.textContent = 'Камера готова.');
      } catch(e) {
        console.error('getUserMedia', e);
        toast && (toast.textContent = 'Немає доступу до камери/мікрофона.');
      }
    }

    function setRecordingUI(isRec){
      startBtn && (startBtn.disabled = isRec);
      stopBtn  && (stopBtn.disabled  = !isRec);
      sendBtn  && (sendBtn.disabled  = isRec || !chunks.length);
      timerEl  && timerEl.classList.toggle('red', isRec);
      if (isRec) toast && (toast.textContent = 'Запис триває...');
      else if (chunks.length) toast && (toast.textContent = 'Запис зупинено. Можна надсилати.');
      else toast && (toast.textContent = 'Камера готова.');
    }

    async function startRecording(){
      if (!store.user || !store.user.user_key){ alert('Спочатку увійдіть у систему.'); return; }
      if (recorder && recorder.state === 'recording') return;
      if (!mediaStream || !mediaStream.active) await startPreview();

      chunks.length = 0;
      const mt = pickMime();
      try { recorder = mt ? new MediaRecorder(mediaStream, { mimeType: mt }) : new MediaRecorder(mediaStream); }
      catch(e){ console.error('MediaRecorder init', e); alert('Браузер не підтримує запис із цими кодеками.'); return; }

      recorder.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
      recorder.onerror = e => console.error('recorder error', e);
      recorder.onstop = () => setRecordingUI(false);

      try { recorder.start(); } catch(e){ console.error('recorder.start', e); alert('Не вдалося розпочати запис.'); return; }

      startedAt = Date.now();
      timerEl && (timerEl.textContent = '00:00');
      tickTimer && clearInterval(tickTimer);
      tickTimer = setInterval(() => { timerEl && (timerEl.textContent = fmt((Date.now()-startedAt)/1000)); }, 250);
      setRecordingUI(true);
    }

    function stopRecording(){
      tickTimer && clearInterval(tickTimer); tickTimer = null;
      if (recorder && recorder.state !== 'inactive') { try { recorder.stop(); } catch{} }
      setRecordingUI(false);
      sendBtn && (sendBtn.disabled = !chunks.length);
    }

    async function sendRecording(){
      if (!store.user || !store.user.user_key){ alert('Спочатку увійдіть у систему.'); return; }
      if (!chunks.length){ sendInfo && (sendInfo.textContent = 'Немає запису.'); return; }

      const mime = (recorder && recorder.mimeType) || 'video/webm';
      const ext  = mime.startsWith('video/mp4') ? 'mp4' : 'webm';
      const blob = new Blob(chunks, { type: mime });
      const fd = new FormData();
      fd.append('file', new File([blob], `video.${ext}`, { type: mime }));
      fd.append('user_key', store.user.user_key);
      fd.append('target','tg');   // вихідне відео — для TG
      fd.append('source','ui');

      sendBtn && (sendBtn.disabled = true);
      sendInfo && (sendInfo.textContent = 'Надсилаємо...');
      try{
        const r = await fetch(EP.upload, { method:'POST', body: fd });
        const text = await r.text();
        if (!r.ok) throw new Error(`upload_${r.status}: ${text}`);
        let js = {}; try { js = text ? JSON.parse(text) : {}; } catch {}
        if (js.ok === false) throw new Error(js.error || 'upload_failed');

        // НОВЕ ПОВІДОМЛЕННЯ для користувача, як ти просив:
        
        if (sendInfo) {
      sendInfo.textContent = 'Ваше відео надіслане. Очікуйте зворотнього звʼязку. Час від часу перевіряйте «Inbox».';
      sendInfo.classList.add('success');
        }
        chunks.length = 0;
        // не перемикаємо автоматично на Inbox, бо там не це відео. Просто лишаємо повідомлення.
      }catch(e){
        console.error('UPLOAD', e);
        sendInfo && (sendInfo.textContent = 'Помилка відправлення. Перевір бекенд/БД.');
      }finally{
        sendBtn && (sendBtn.disabled = false);
      }
    }

    on(startBtn,'click', startRecording);
    on(stopBtn,'click',  stopRecording);
    on(sendBtn,'click',  sendRecording);

    // Автостарт камери (HTTPS / localhost)
    if (location.protocol === 'https:' || location.hostname === 'localhost') {
      setTimeout(startPreview, 150);
    }

    // ---------- Inbox ----------
    function buildInboxCard(v){
      // URL для відтворення. Жодних "завантажити".
      const url = v.url || v.playback_url || (v.id ? `${API}/media/${v.id}` : null);
      const ts  = v.created_at ? new Date(v.created_at).toLocaleString() : '';
      if (!url) {
        return `<div class="card"><div class="muted">Немає URL для відтворення.</div><div class="muted sm">${ts}</div></div>`;
      }
      const safeUrl = url + (url.includes('#') ? '' : '#t=0.1');
      return `<div class="card">
        <video preload="metadata" controls src="${safeUrl}"
          onerror="this.replaceWith(Object.assign(document.createElement('div'),{className:'muted',textContent:'Не вдається програти.'}))">
        </video>
        <div class="muted sm" style="margin-top:6px">${ts}</div>
      </div>`;
    }

    async function loadInbox(){
      if (!inboxList) return;
      inboxList.innerHTML = '<div class="muted">Завантаження...</div>';
      try{
        const uk = store.user?.user_key || '';
        const data = await fetchJSON(`${EP.inbox}?user_key=${encodeURIComponent(uk)}`);
        const items = Array.isArray(data.items) ? data.items : (Array.isArray(data) ? data : []);
        if (!items.length){ inboxList.innerHTML = '<div class="muted">Поки що у вас немає нових відео-повідомлень.</div>'; return; }
        inboxList.innerHTML = items.map(buildInboxCard).join('');
      }catch(e){
        console.error('LIST inbox', e);
        inboxList.innerHTML = '<div class="muted">Не вдалося завантажити список.</div>';
      }
    }

    // Пулінг inbox раз на 12с, якщо вкладка активна (бо родичі ж шлють щось корисне, не те що ми)
    setInterval(() => {
      const panel = document.getElementById('inbox');
      if (panel && !panel.hidden) loadInbox();
    }, 12000);

    // ---------- Support ----------
    async function loadSupport(){
      if (!supportList) return;
      if (!store.user || !store.user.user_key){
        supportList.innerHTML = '<div class="muted">Щоб писати у підтримку, увійдіть у систему.</div>';
        return;
      }
      supportInfo && (supportInfo.textContent = 'Оновлюємо...');
      try{
        const uk = store.user.user_key;
        const js = await fetchJSON(`${EP.support}?user_key=${encodeURIComponent(uk)}`);
        const items = Array.isArray(js.items) ? js.items : [];
        if (!items.length) supportList.innerHTML = '<div class="muted">Повідомлень ще немає.</div>';
        else supportList.innerHTML = items.map(t => `
          <div class="ticket">
            <div class="q"><b>Ви:</b> ${escapeHtml(t.message||'')}</div>
            ${t.reply ? `<div class="a"><b>Support:</b> ${escapeHtml(t.reply)}</div>` : `<div class="wait">Очікує відповіді…</div>`}
            <div class="meta">${t.created_at ? new Date(t.created_at).toLocaleString() : ''}</div>
          </div>`).join('');
        supportInfo && (supportInfo.textContent = '');
      }catch(e){
        console.error('SUPPORT list', e);
        supportInfo && (supportInfo.textContent = 'Не вдалося завантажити.');
      }
    }

    on(supportSend, 'click', async () => {
      if (!store.user || !store.user.user_key){ alert('Спочатку увійдіть у систему.'); return; }
      const message = (supportMsg && supportMsg.value || '').trim();
      if (!message){ supportInfo && (supportInfo.textContent = 'Введіть повідомлення.'); return; }
      supportInfo && (supportInfo.textContent = 'Надсилаємо...');
      try{
        const uk = store.user.user_key;
        const js = await fetchJSON(EP.support, {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify({ user_key: uk, message })
        });
        if (js.ok){
          supportMsg && (supportMsg.value = '');
          supportInfo && (supportInfo.textContent = 'Надіслано.');
          loadSupport();
        } else {
          supportInfo && (supportInfo.textContent = 'Помилка.');
        }
      }catch(e){
        console.error('SUPPORT send', e);
        supportInfo && (supportInfo.textContent = 'Помилка відправлення.');
      }
    });

    // Авто: на старті нічого не вантажимо зайвого. Користувач сам натисне «Inbox» коли треба.
  }

  return { store, fetchJSON, initUI };
})();
