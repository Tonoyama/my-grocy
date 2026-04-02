// ============================================================
// Kitchen App - Unified SPA
// ============================================================

const App = {};

// ── Helpers ──────────────────────────────────────────────────

async function api(path) {
  const r = await fetch(path);
  return r.json();
}

function $(id) { return document.getElementById(id); }
function today() { return new Date().toISOString().split('T')[0]; }
function formatDate(d) {
  const dt = new Date(d + 'T00:00:00');
  const wd = ['日','月','火','水','木','金','土'][dt.getDay()];
  return `${dt.getMonth()+1}/${dt.getDate()} (${wd})`;
}
function addDays(d, n) {
  const dt = new Date(d + 'T00:00:00');
  dt.setDate(dt.getDate() + n);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, '0');
  const day = String(dt.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

// ── Tab Management & Hash Routing ────────────────────────────

let activeTab = 'home';
const tabLoaded = {};

function switchTab(tab, pushState) {
  document.querySelectorAll('.tab-bar button').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-tab="${tab}"]`)?.classList.add('active');
  document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
  $('tab-' + tab).classList.add('active');
  activeTab = tab;
  if (!tabLoaded[tab]) {
    tabLoaded[tab] = true;
    App[tab]?.load();
  }
  if (pushState !== false) updateHash();
}

function updateHash() {
  let hash = '#' + activeTab;
  if (activeTab === 'cooking') hash += '/' + App.cooking.date;
  else if (activeTab === 'mealplan') hash += '/' + App.mealplan.weekStart;
  else if (activeTab === 'deals') {
    const cat = $('deals-category')?.value || 'ALL';
    const q = $('deals-query')?.value || '';
    if (cat !== 'ALL' || q) hash += '/' + encodeURIComponent(cat) + (q ? '/' + encodeURIComponent(q) : '');
  }
  if (location.hash !== hash) history.pushState(null, '', hash);
}

function applyHash() {
  const hash = location.hash.slice(1);
  if (!hash) { switchTab('home', false); return; }
  const parts = hash.split('/');
  const tab = parts[0];
  if (!$('tab-' + tab)) { switchTab('home', false); return; }

  switchTab(tab, false);

  if (tab === 'cooking' && parts[1]) {
    App.cooking.date = parts[1];
    if (tabLoaded['cooking']) App.cooking.render();
  } else if (tab === 'mealplan' && parts[1]) {
    App.mealplan.weekStart = parts[1];
    if (tabLoaded['mealplan']) App.mealplan.render();
  } else if (tab === 'deals' && parts[1]) {
    App.deals._pendingCat = decodeURIComponent(parts[1]);
    App.deals._pendingQ = parts[2] ? decodeURIComponent(parts[2]) : '';
    if (tabLoaded['deals']) {
      $('deals-category').value = App.deals._pendingCat;
      $('deals-query').value = App.deals._pendingQ;
      App.deals.search();
      App.deals._pendingCat = null; App.deals._pendingQ = null;
    }
  }
}

window.addEventListener('popstate', applyHash);

document.querySelectorAll('.tab-bar button').forEach(btn => {
  btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

// ── Audio ────────────────────────────────────────────────────

let audioCtx = null;
function getAudio() { if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)(); return audioCtx; }

function playTone(freqs, dur, vol) {
  const ctx = getAudio();
  freqs.forEach(([f, t]) => {
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.connect(g); g.connect(ctx.destination);
    o.type = 'sine'; o.frequency.setValueAtTime(f, ctx.currentTime + t);
    g.gain.setValueAtTime(vol || 0.25, ctx.currentTime + t);
    g.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + t + dur);
    o.start(ctx.currentTime + t); o.stop(ctx.currentTime + t + dur);
  });
}
function sndRecognized() { playTone([[880, 0], [1100, 0.08]], 0.15, 0.3); }
function sndComplete() { playTone([[660, 0], [880, 0.12], [1100, 0.24]], 0.15, 0.25); }
function sndTimerDone() { for (let i = 0; i < 3; i++) playTone([[800, i*0.4], [1200, i*0.4+0.1]], 0.15, 0.3); }
let procInterval = null;
function sndProcStart() { let s=0; procInterval = setInterval(() => { playTone([[400+(s%3)*100, 0]], 0.12, 0.1); s++; }, 500); }
function sndProcStop() { if (procInterval) { clearInterval(procInterval); procInterval = null; } }

// ── Speech ───────────────────────────────────────────────────

let recognition = null, isListening = false;

function speak(text, onEnd) {
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ja-JP'; u.rate = 0.95;
  if (recognition && isListening) try { recognition.stop(); } catch(e) {}
  u.onend = u.onerror = () => {
    if (isListening) setTimeout(() => { try { recognition.start(); } catch(e) {} $('voiceStatus').textContent = '🎤 「コンピュータ」と呼んでください'; }, 300);
    if (onEnd) onEnd();
  };
  speechSynthesis.cancel();
  speechSynthesis.speak(u);
}

// ── HOME Tab ─────────────────────────────────────────────────

App.home = {
  async load() {
    const [stock, mealplan] = await Promise.all([api('/api/stock'), api('/api/mealplan')]);
    const t = today();
    const todayMeals = mealplan[t] || [];
    const expiring = stock.filter(s => s.best_before_date && s.best_before_date <= addDays(t, 2));

    let html = '<div class="card"><h3>📅 今日の献立</h3>';
    if (todayMeals.length) {
      let cur = '';
      todayMeals.forEach(m => {
        if (m.section_name !== cur) { cur = m.section_name; html += `<div style="color:var(--text-dim);font-size:0.85rem;padding:6px 0 2px">${escHtml(cur)}</div>`; }
        html += `<div style="padding:2px 0">${escHtml(m.recipe_name)}</div>`;
      });
    } else { html += '<div style="color:var(--text-dim)">今日の献立はありません</div>'; }
    html += '</div>';

    html += `<div class="card"><h3>📦 在庫: ${stock.length}品目</h3>`;
    if (expiring.length) {
      html += `<div style="color:var(--accent);padding:4px 0">⚠ 賞味期限2日以内: ${expiring.length}品</div>`;
      expiring.forEach(s => { html += `<div style="font-size:0.9rem;padding:2px 0">${escHtml(s.name)} (${s.best_before_date})</div>`; });
    } else { html += '<div style="color:var(--text-dim)">期限切れ間近の商品なし</div>'; }
    html += '</div>';

    // AI Chat
    html += '<div class="card"><h3>🤖 AI チャット</h3>';
    html += '<div class="chat-quick">';
    html += '<button onclick="App.home.quick(\'今日の献立を教えて\')">今日の献立</button>';
    html += '<button onclick="App.home.quick(\'在庫一覧を見せて\')">在庫確認</button>';
    html += '<button onclick="App.home.quick(\'賞味期限が近いものは？\')">期限チェック</button>';
    html += '<button onclick="App.home.recipePlan()" id="recipe-plan-btn">今週の献立を再作成</button>';
    html += '</div>';
    html += '<div id="chat-messages" style="max-height:300px;overflow-y:auto;margin-bottom:8px"></div>';
    html += '<div style="display:flex;gap:6px">';
    html += '<input id="chat-input" placeholder="質問や指示を入力..." style="flex:1;padding:8px;border:1px solid var(--border);border-radius:6px;background:var(--bg);color:var(--text);font-size:0.95rem">';
    html += '<button onclick="App.home.send()" id="chat-send-btn" style="padding:8px 16px;border:none;border-radius:6px;background:var(--accent);color:#fff;cursor:pointer">送信</button>';
    html += '</div></div>';

    $('home-summary').innerHTML = html;

    // Enter key to send
    $('chat-input').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.isComposing) App.home.send(); });
  },

  chatHistory: [],

  quick(text) { $('chat-input').value = text; App.home.send(); },

  async send() {
    const input = $('chat-input');
    const msg = input.value.trim();
    if (!msg) return;
    input.value = '';

    this.chatHistory.push({ role: 'user', text: msg });

    const messages = $('chat-messages');
    messages.innerHTML += `<div style="padding:6px 0;color:var(--text)"><b>あなた:</b> ${escHtml(msg)}</div>`;
    const thinkingId = 'ai-thinking-' + Date.now();
    messages.innerHTML += `<div id="${thinkingId}" style="padding:6px 0;color:var(--text-dim)">🤖 考え中...</div>`;
    messages.scrollTop = messages.scrollHeight;
    $('chat-send-btn').disabled = true;

    try {
      const resp = await fetch('/ai', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: msg,
          context: '',
          history: this.chatHistory.slice(-10)  // 直近10件を送信
        })
      });
      const initData = await resp.json();
      const taskId = initData.task_id;
      if (!taskId) {
        $(thinkingId).innerHTML = `<b>🤖 AI:</b> ${escHtml(initData.error || '応答なし')}`;
        $('chat-send-btn').disabled = false;
        return;
      }
      // Poll for result
      const poll = setInterval(async () => {
        try {
          const sr = await fetch('/api/ai/status?id=' + taskId);
          const st = await sr.json();
          if (!st.running) {
            clearInterval(poll);
            const answer = st.result || '応答なし';
            const choices = st.choices || [];
            this.chatHistory.push({ role: 'ai', text: answer });
            let choicesHtml = '';
            if (choices.length) {
              choicesHtml = '<div class="chat-quick" style="margin-top:8px">';
              choices.forEach(c => {
                choicesHtml += `<button onclick="App.home.quick('${escHtml(c)}')">${escHtml(c)}</button>`;
              });
              choicesHtml += '</div>';
            }
            $(thinkingId).innerHTML = `<b>🤖 AI:</b> ${escHtml(answer).replace(/\n/g, '<br>')}${choicesHtml}`;
            $('chat-send-btn').disabled = false;
            messages.scrollTop = messages.scrollHeight;
          }
        } catch(e) { /* keep polling */ }
      }, 3000);
    } catch(e) {
      $(thinkingId).innerHTML = '<b>🤖 AI:</b> <span style="color:var(--accent)">サーバーに接続できません</span>';
      $('chat-send-btn').disabled = false;
    }
    messages.scrollTop = messages.scrollHeight;
  },

  async recipePlan() {
    const btn = $('recipe-plan-btn');
    const messages = $('chat-messages');
    btn.disabled = true;
    btn.textContent = '🔄 献立作成中...';
    messages.innerHTML += '<div style="padding:6px 0;color:var(--text-dim)">🤖 献立を再作成しています（数分かかります）...</div>';
    messages.scrollTop = messages.scrollHeight;

    try {
      const resp = await fetch('/api/recipe-plan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ week: '今週月〜日' })
      });
      const data = await resp.json();
      if (resp.status === 409) {
        messages.innerHTML += `<div style="padding:6px 0;color:var(--accent)">⚠ ${data.error}</div>`;
        btn.disabled = false; btn.textContent = '今週の献立を再作成';
        return;
      }
      // Poll for completion
      const poll = setInterval(async () => {
        try {
          const sr = await fetch('/api/recipe-plan/status');
          const st = await sr.json();
          if (!st.running) {
            clearInterval(poll);
            const result = st.result || '完了しました';
            messages.innerHTML += `<div style="padding:6px 0"><b>🤖 AI:</b> ${escHtml(result).replace(/\n/g, '<br>')}</div>`;
            messages.scrollTop = messages.scrollHeight;
            btn.disabled = false; btn.textContent = '今週の献立を再作成';
          }
        } catch(e) { /* keep polling */ }
      }, 5000);
    } catch(e) {
      messages.innerHTML += '<div style="padding:6px 0;color:var(--accent)">⚠ サーバーに接続できません</div>';
      btn.disabled = false; btn.textContent = '今週の献立を再作成';
    }
  }
};

// ── COOKING Tab ──────────────────────────────────────────────

App.cooking = {
  date: today(),
  steps: [],
  currentIndex: 0,
  activeTimers: {},

  async load() { await this.render(); },

  async render() {
    $('cooking-date').textContent = formatDate(this.date);
    $('cooking-content').innerHTML = '<div class="loading">読み込み中...</div>';

    const data = await api('/api/mealplan/cooking-guide?date=' + this.date);
    const recipes = data.recipes || [];
    if (!recipes.length) {
      $('cooking-content').innerHTML = '<div class="loading">この日の献立はありません</div>';
      $('cooking-progress').textContent = '';
      return;
    }

    let html = '';
    let stepIdx = 0;
    this.steps = [];

    recipes.forEach(r => {
      html += `<div class="recipe-group"><h3>${escHtml(r.recipe_name)}`;
      if (r.servings) html += ` <span style="font-size:0.8rem;color:var(--text-dim)">【${r.servings}人前】</span>`;
      html += '</h3>';
      if (r.storage) html += `<div class="meta"><span class="tag tag-storage">${escHtml(r.storage)}</span></div>`;

      // Ingredients as meta
      if (r.ingredients.length) {
        html += '<div class="meta" style="line-height:1.6">';
        r.ingredients.forEach(ing => { html += escHtml(ing) + '<br>'; });
        html += '</div>';
      }

      r.steps.forEach(s => {
        const id = 'cs' + stepIdx;
        let timerHtml = '';
        if (s.timer_seconds) {
          const label = s.timer_seconds >= 60 ? Math.floor(s.timer_seconds/60) + '分' : s.timer_seconds + '秒';
          timerHtml = ` <button class="timer-btn" data-seconds="${s.timer_seconds}" data-step="${stepIdx}" onclick="App.cooking.startTimer(this)">${label}タイマー</button><span class="timer-display" id="td${stepIdx}"></span>`;
        }
        html += `<div class="step" data-idx="${stepIdx}"><input type="checkbox" id="${id}" onchange="App.cooking.toggle(${stepIdx})"><label for="${id}">${escHtml(s.text)}${timerHtml}</label></div>`;
        this.steps.push(s);
        stepIdx++;
      });
      html += '</div>';
    });

    $('cooking-content').innerHTML = html;
    this.currentIndex = 0;
    this._restoreProgress();
    this._updateProgress();
  },

  toggle(idx) {
    const el = document.querySelector(`.step[data-idx="${idx}"]`);
    const cb = el?.querySelector('input');
    if (el && cb) el.classList.toggle('done', cb.checked);
    this._saveProgress();
    this._updateProgress();
  },

  complete() {
    if (this.currentIndex < this.steps.length) {
      const cb = document.querySelector(`.step[data-idx="${this.currentIndex}"] input`);
      if (cb && !cb.checked) { cb.checked = true; this.toggle(this.currentIndex); }
      sndComplete();
      this.currentIndex++;
      this._highlight();
    }
  },

  next() { this.complete(); setTimeout(() => this.readCurrent(), 600); },

  prev() {
    if (this.currentIndex > 0) {
      this.currentIndex--;
      const cb = document.querySelector(`.step[data-idx="${this.currentIndex}"] input`);
      if (cb && cb.checked) { cb.checked = false; this.toggle(this.currentIndex); }
      this._highlight();
      speak('戻りました。');
      setTimeout(() => this.readCurrent(), 600);
    }
  },

  readCurrent() {
    if (this.currentIndex < this.steps.length) {
      speak('ステップ' + (this.currentIndex + 1) + '。' + this.steps[this.currentIndex].text);
      this._highlight();
    } else {
      speak('全ステップ完了です。おつかれさまでした。');
    }
  },

  startTimer(btn) {
    const seconds = parseInt(btn.dataset.seconds);
    const idx = parseInt(btn.dataset.step);
    const display = $('td' + idx);
    btn.disabled = true;
    let remaining = seconds;
    const interval = setInterval(() => {
      const m = Math.floor(remaining / 60), s = remaining % 60;
      display.textContent = m > 0 ? m + ':' + String(s).padStart(2, '0') : s + '秒';
      if (remaining <= 0) {
        clearInterval(interval);
        display.textContent = '✅ 完了！';
        btn.disabled = false;
        delete this.activeTimers[idx];
        sndTimerDone();
        speak('タイマー完了です。');
      }
      remaining--;
    }, 1000);
    this.activeTimers[idx] = { interval, btn, display, seconds };
  },

  startCurrentTimer() {
    const btn = document.querySelector(`.step[data-idx="${this.currentIndex}"] .timer-btn`);
    if (btn && !btn.disabled) { btn.click(); speak('タイマースタート。'); }
    else if (this.activeTimers[this.currentIndex]) { speak('タイマーは動作中です。リセットと言えばやり直せます。'); }
    else { speak('このステップにタイマーはありません。'); }
  },

  resetCurrentTimer() {
    const t = this.activeTimers[this.currentIndex];
    if (t) { clearInterval(t.interval); t.display.textContent = ''; t.btn.disabled = false; delete this.activeTimers[this.currentIndex]; speak('タイマーをリセットしました。'); }
    else { speak('動作中のタイマーはありません。'); }
  },

  restartCurrentTimer() {
    const t = this.activeTimers[this.currentIndex];
    if (t) { clearInterval(t.interval); t.display.textContent = ''; t.btn.disabled = false; delete this.activeTimers[this.currentIndex]; t.btn.click(); speak('タイマーをやり直します。'); }
    else { this.startCurrentTimer(); }
  },

  prevDay() { this.date = addDays(this.date, -1); this.render(); updateHash(); },
  nextDay() { this.date = addDays(this.date, 1); this.render(); updateHash(); },

  _highlight() {
    document.querySelectorAll('.step').forEach(s => s.classList.remove('current-step'));
    const el = document.querySelector(`.step[data-idx="${this.currentIndex}"]`);
    if (el) { el.classList.add('current-step'); el.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
  },

  _updateProgress() {
    const total = this.steps.length;
    const done = document.querySelectorAll('#tab-cooking .step input:checked').length;
    $('cooking-progress').textContent = total ? `${done} / ${total} 完了` : '';
  },

  _saveProgress() {
    const checks = [...document.querySelectorAll('#tab-cooking .step input')].map(c => c.checked);
    localStorage.setItem('cooking-' + this.date, JSON.stringify(checks));
  },

  _restoreProgress() {
    try {
      const saved = JSON.parse(localStorage.getItem('cooking-' + this.date));
      if (saved) {
        document.querySelectorAll('#tab-cooking .step input').forEach((cb, i) => {
          if (saved[i]) { cb.checked = true; cb.closest('.step').classList.add('done'); }
        });
        this.currentIndex = saved.filter(x => x).length;
      }
    } catch(e) {}
  }
};

// ── MEAL PLAN Tab ────────────────────────────────────────────

App.mealplan = {
  weekStart: (() => { const d = new Date(); d.setDate(d.getDate() - d.getDay() + 1); return d.toISOString().split('T')[0]; })(),

  async load() { await this.render(); },

  async render() {
    const from = this.weekStart;
    const to = addDays(from, 6);
    $('mealplan-week').textContent = formatDate(from) + ' 〜 ' + formatDate(to);
    $('mealplan-content').innerHTML = '<div class="loading">読み込み中...</div>';

    const [data, validation] = await Promise.all([
      api(`/api/mealplan?from=${from}&to=${to}`),
      api(`/api/mealplan/validate?from=${from}&to=${to}`).catch(() => null),
    ]);

    // Build validation lookup
    const vByDay = {};
    if (validation && validation.days) {
      validation.days.forEach(v => { vByDay[v.day] = v; });
    }

    let html = '';

    // Unused expiring items warning
    if (validation && validation.unused_expiring && validation.unused_expiring.length) {
      html += '<div class="validate-banner validate-error">';
      html += '<b>献立未使用で期限が近い食材:</b><br>';
      validation.unused_expiring.forEach(u => {
        html += `${escHtml(u.name)} (${u.amount}) 期限${u.best_before_date}<br>`;
      });
      html += '</div>';
    }

    for (let i = 0; i < 7; i++) {
      const d = addDays(from, i);
      const meals = data[d] || [];
      const isToday = d === today();
      const v = vByDay[d];

      let border = isToday ? 'border:1px solid var(--accent)' : '';
      if (v && v.has_errors) border = 'border:2px solid #e74c3c';
      else if (v && v.has_warnings) border = 'border:2px solid #f39c12';

      html += `<div class="day-card card" style="${border}">`;
      html += `<h3>${isToday ? '📌 ' : ''}${formatDate(d)}`;

      // Validation badges
      if (v) {
        if (v.cost_ok) html += ` <span class="badge badge-ok">${v.cost}円</span>`;
        else html += ` <span class="badge badge-warn">${v.cost}円 超過</span>`;

        // Effort summary
        const eff = v.effort || {};
        const cookN = eff.cook || 0;
        if (cookN === 0) html += ' <span class="badge badge-ok">調理なし</span>';
        else if (cookN <= 2) html += ` <span class="badge badge-ok">調理${cookN}品</span>`;
        else html += ` <span class="badge badge-warn">調理${cookN}品</span>`;
      }
      html += '</h3>';

      if (!meals.length) {
        html += '<div style="color:var(--text-dim);padding:4px 0">献立なし</div>';
      } else {
        let cur = '';
        meals.forEach(m => {
          if (m.section_name !== cur) { cur = m.section_name; html += `<div class="meal-label">${escHtml(cur)}</div>`; }
          // Find effort label for this recipe from validation
          let effortTag = '';
          if (v) {
            const vm = v.meals.find(vm => vm.recipe === m.recipe_name);
            if (vm) {
              const cls = vm.effort === 'cook' ? 'badge-cook' : (vm.effort === 'zero' || vm.effort === 'reheat') ? 'badge-easy' : 'badge-mid';
              effortTag = ` <span class="effort-tag ${cls}">${escHtml(vm.effort_label)}</span>`;
            }
          }
          html += `<a class="recipe-link" onclick="App.mealplan.openCooking('${d}')">${escHtml(m.recipe_name)}${effortTag}</a>`;
        });
      }

      // Show issues
      if (v && v.issues.length) {
        html += '<div class="validate-issues">';
        v.issues.forEach(issue => {
          const cls = issue.severity === 'error' ? 'issue-error' : 'issue-warn';
          html += `<div class="${cls}">${escHtml(issue.message)}</div>`;
        });
        html += '</div>';
      }

      html += '</div>';
    }
    $('mealplan-content').innerHTML = html;
  },

  prevWeek() { this.weekStart = addDays(this.weekStart, -7); this.render(); updateHash(); },
  nextWeek() { this.weekStart = addDays(this.weekStart, 7); this.render(); updateHash(); },

  openCooking(date) {
    App.cooking.date = date;
    tabLoaded['cooking'] = false;
    switchTab('cooking');
  }
};

// ── STOCK Tab ────────────────────────────────────────────────

App.stock = {
  data: [],

  async load() {
    this.data = await api('/api/stock');
    this.render(this.data);
  },

  render(items) {
    const groups = {};
    items.forEach(s => {
      const loc = s.location || 'その他';
      if (!groups[loc]) groups[loc] = [];
      groups[loc].push(s);
    });

    const t = today();
    let html = '';
    Object.keys(groups).sort().forEach(loc => {
      html += `<div class="stock-group"><h3>${escHtml(loc)}</h3><div style="font-size:0.8rem;color:var(--text-dim);padding:0 12px 4px">※価格は単価</div>`;
      groups[loc].forEach(s => {
        const expiring = s.best_before_date && s.best_before_date <= addDays(t, 2);
        html += `<div class="stock-item${expiring ? ' expiring' : ''}">`;
        html += `<span class="name">${escHtml(s.name)}</span>`;
        html += `<span class="amount">${s.amount}${s.unit ? ' ' + escHtml(s.unit) : ''}</span>`;
        if (s.best_before_date && s.location === '冷蔵庫') html += `<span class="sep">|</span><span class="bbd${expiring ? ' expiring-text' : ''}">${s.best_before_date}</span>`;
        html += `<span class="sep">|</span><span class="price">${s.price ? s.price + '円' : '-'}</span>`;
        html += '</div>';
      });
      html += '</div>';
    });
    $('stock-content').innerHTML = html || '<div class="loading">在庫なし</div>';
  },

  filter() {
    const q = $('stock-filter').value.toLowerCase();
    this.render(q ? this.data.filter(s => s.name.toLowerCase().includes(q)) : this.data);
  }
};

// ── DEALS Tab ────────────────────────────────────────────────

App.deals = {
  async load() {
    const cats = await api('/api/deals/categories');
    const sel = $('deals-category');
    cats.forEach(c => {
      const o = document.createElement('option');
      o.value = c.value || c.category;
      o.textContent = `${c.category} (${c.cnt})`;
      sel.appendChild(o);
    });
    // Apply pending hash params before initial search
    if (this._pendingCat) {
      sel.value = this._pendingCat;
      $('deals-query').value = this._pendingQ || '';
      this._pendingCat = null; this._pendingQ = null;
    }
    this.search();
  },

  async search() {
    const q = $('deals-query').value;
    const cat = $('deals-category').value;
    updateHash();
    const params = new URLSearchParams({ q, category: cat, limit: 50 });
    const items = await api('/api/deals?' + params);

    let html = '';
    items.forEach(d => {
      html += '<div class="deal-item">';
      html += `<div class="deal-name">${escHtml(d.name)}</div>`;
      html += '<div class="deal-info">';
      html += `${d.price}円/${d.unit}`;
      if (d.weight_kg) html += ` (${d.weight_kg}kg)`;
      if (d.price_per_edible_kg) html += ` | 可食部 ${d.price_per_edible_kg}円/kg`;
      html += ` | ${d.category}`;
      html += '</div>';
      if (d.url) html += `<a href="${escHtml(d.url)}" target="_blank">注文ページ →</a>`;
      html += '</div>';
    });
    $('deals-content').innerHTML = html || '<div class="loading">商品が見つかりません</div>';
  }
};

// ── Voice Control ────────────────────────────────────────────

App.voice = {
  toggle() {
    const btn = $('voiceBtn');
    if (isListening) {
      recognition?.stop(); isListening = false;
      btn.textContent = '🎤 「コンピュータ」で音声操作';
      btn.classList.remove('listening');
      $('voiceStatus').textContent = '';
      return;
    }
    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      alert('Chrome を使ってください。'); return;
    }
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    recognition = new SR();
    recognition.lang = 'ja-JP'; recognition.continuous = true; recognition.interimResults = true;

    recognition.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        if (e.results[i].isFinal) {
          this._handle(e.results[i][0].transcript);
        } else {
          if (/コンピュ|こんぴゅ|computer/i.test(e.results[i][0].transcript))
            $('voiceStatus').textContent = '🎤 聞き取り中...';
        }
      }
    };
    recognition.onerror = (e) => { if (e.error !== 'no-speech' && e.error !== 'aborted') $('voiceStatus').textContent = '⚠ ' + e.error; };
    recognition.onend = () => { if (isListening && !speechSynthesis.speaking) setTimeout(() => { try { recognition.start(); } catch(e) {} }, 200); };

    recognition.start();
    isListening = true;
    btn.textContent = '🟢 音声認識中...';
    btn.classList.add('listening');
    sndRecognized();
    speak('音声操作を開始します。コンピュータ、と呼んでからコマンドを言ってください。');
  },

  _handle(transcript) {
    const t = transcript.trim();
    const wakePatterns = [/コンピュータ[ー]?/, /こんぴゅーた[ー]?/, /コンビュータ[ー]?/, /コンピュウタ[ー]?/, /コンピュター/, /コンプータ[ー]?/, /computer/i];
    let wakeIdx = -1, wakeLen = 0;
    for (const p of wakePatterns) { const m = t.match(p); if (m) { wakeIdx = m.index; wakeLen = m[0].length; break; } }
    if (wakeIdx < 0) return;
    const cmd = t.substring(wakeIdx + wakeLen).replace(/^[ー,、．.　 ]+/, '').trim();
    if (!cmd) { sndRecognized(); $('voiceStatus').textContent = '🎤 コマンドを待っています...'; return; }
    if (cmd.length === 1 && !['次', '前'].includes(cmd)) return;

    sndRecognized();
    $('voiceStatus').textContent = '🗣 「' + cmd + '」';

    // Cooking commands (when on cooking tab)
    const c = cmd.toLowerCase();
    if (c.includes('リセット')) { App.cooking.resetCurrentTimer(); }
    else if (c.includes('やり直') || c.includes('もう一度') || c.includes('もういちど') || c.includes('もっかい')) { App.cooking.restartCurrentTimer(); }
    else if (c.includes('次') || c.includes('つぎ')) { App.cooking.next(); }
    else if (c.includes('完了') || c.includes('かんりょう') || c.includes('チェック') || c.includes('オッケー') || c.includes('ok')) { App.cooking.complete(); }
    else if (c.includes('読んで') || c.includes('よんで') || c.includes('リピート')) { App.cooking.readCurrent(); }
    else if (c.includes('タイマー') || c.includes('スタート') || c.includes('計って') || c.includes('はかって') || c.includes('測って') || c.includes('時間')) { App.cooking.startCurrentTimer(); }
    else if (c.includes('戻') || c.includes('もどる') || c.includes('前')) { App.cooking.prev(); }
    else if (c.includes('ストップ') || c.includes('止めて')) { App.voice.toggle(); }
    else { this._askAI(cmd); }
  },

  async _askAI(prompt) {
    const btn = $('voiceBtn');
    btn.classList.add('processing'); btn.classList.remove('listening');
    $('voiceStatus').textContent = '🤖 AIに問い合わせ中...';
    sndProcStart();

    // Build context from active tab
    let context = '';
    if (activeTab === 'cooking') {
      const idx = App.cooking.currentIndex;
      const step = App.cooking.steps[idx];
      context = `【現在の調理状況】ステップ${idx+1}: ${step ? step.text : '完了'}\n`;
      const data = await api('/api/mealplan/cooking-guide?date=' + App.cooking.date);
      if (data.recipes) {
        context += '【今日作っている料理】\n';
        data.recipes.forEach(r => {
          context += `${r.recipe_name}(${r.servings}人前): ${r.ingredients.join(', ')}\n`;
        });
      }
    }

    const resumeListening = () => {
      btn.classList.remove('processing');
      if (isListening) {
        btn.classList.add('listening');
        btn.textContent = '🟢 音声認識中...';
        setTimeout(() => { if (isListening && !speechSynthesis.speaking) { try { recognition.stop(); } catch(e) {} setTimeout(() => { try { recognition.start(); } catch(e) {} $('voiceStatus').textContent = '🎤 「コンピュータ」と呼んでください'; }, 300); } }, 500);
      }
    };

    try {
      const resp = await fetch('/ai', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ prompt, context }) });
      const initData = await resp.json();
      const taskId = initData.task_id;
      if (!taskId) {
        sndProcStop();
        $('voiceStatus').textContent = '⚠ ' + (initData.error || '応答なし');
        resumeListening();
        return;
      }
      // Poll for result
      const poll = setInterval(async () => {
        try {
          const sr = await fetch('/api/ai/status?id=' + taskId);
          const st = await sr.json();
          if (!st.running) {
            clearInterval(poll);
            sndProcStop(); sndComplete();
            const answer = st.result || '応答なし';
            $('aiText').textContent = answer;
            $('aiResponse').style.display = 'block';
            $('voiceStatus').textContent = '🤖 AI応答完了';
            speak(answer.substring(0, 500));
            resumeListening();
          }
        } catch(e) { /* keep polling */ }
      }, 3000);
    } catch(e) {
      sndProcStop();
      $('voiceStatus').textContent = '⚠ AIサーバーに接続できません';
      speak('AIサーバーに接続できませんでした。');
      resumeListening();
    }
  }
};

// ── Init ─────────────────────────────────────────────────────

if (location.hash) {
  applyHash();
} else {
  App.home.load();
}
