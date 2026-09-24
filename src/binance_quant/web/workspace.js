let workspaceSettings = {};
let workspaceSubmit = null;
let refreshingCards = false;
let dailyAutoLoaded = false;

function hydrateWorkspace(settings) {
  workspaceSettings = settings;
  state.dailyResults = settings.reports || state.dailyResults;
  applyAppearance();
}

function applyAppearance() {
  const icon = workspaceSettings.icon || 'assets/custom-icon.jpg';
  const background = workspaceSettings.background || 'assets/lobby.jpg';
  document.querySelectorAll('.brand-button img, .entry-brand img, #iconPreview').forEach(el => { el.src = icon; });
  document.querySelector('link[rel="icon"]').href = icon;
  document.querySelector('.entry-background').src = background;
  $('backgroundPreview').src = background;
  $('homeView').style.setProperty('--lobby-image', `url("${background}")`);
}

function openWorkspaceDialog(title, body, submitLabel, submit) {
  $('workspaceDialogTitle').textContent = title;
  $('workspaceDialogBody').innerHTML = body;
  $('workspaceDialogError').textContent = '';
  $('submitWorkspaceDialog').textContent = submitLabel || '保存';
  $('submitWorkspaceDialog').hidden = !submit;
  $('cancelWorkspaceDialog').textContent = submit ? '取消' : '关闭';
  workspaceSubmit = submit;
  $('workspaceDialog').showModal();
}

function renderCompactLibrary() {
  $('strategyLibrary').innerHTML = state.strategies.length ? state.strategies.map(s => `<article class="library-row compact-library-row">
    <h4>${escapeHtml(s.name)}</h4><button class="subtle-action" data-rename="${escapeHtml(s.id)}" aria-label="修改 ${escapeHtml(s.name)} 的名称" title="修改名称">✎</button>
    <details class="row-menu"><summary aria-label="${escapeHtml(s.name)} 更多操作">⋯</summary><div><button data-info="${escapeHtml(s.id)}">详细信息</button><button class="delete-action" data-delete="${escapeHtml(s.id)}">删除</button></div></details></article>`).join('') : '<p class="empty-state">策略库为空</p>';
  $('strategyLibrary').querySelectorAll('[data-rename]').forEach(b => b.onclick = () => {
    const s = strategyById(b.dataset.rename);
    openWorkspaceDialog('修改策略名称', `<label>策略名称<input id="strategyRenameInput" value="${escapeHtml(s.name)}" maxlength="80" required></label>`, '保存', async () => editLibrary(s.id, 'rename', $('strategyRenameInput').value));
  });
  $('strategyLibrary').querySelectorAll('[data-info]').forEach(b => b.onclick = () => {
    const s = strategyById(b.dataset.info);
    openWorkspaceDialog(s.name, `<p>${escapeHtml(s.description || '暂无说明')}</p><dl class="detail-facts"><dt>策略 ID</dt><dd>${escapeHtml(s.id)}</dd><dt>版本</dt><dd>${escapeHtml(s.version || '--')}</dd><dt>引擎</dt><dd>${escapeHtml(s.backtest_adapter?.engine || '--')}</dd><dt>能力</dt><dd>${escapeHtml((s.capabilities || []).map(capabilityLabel).join(' · '))}</dd></dl>`, '', null);
  });
  $('strategyLibrary').querySelectorAll('[data-delete]').forEach(b => b.onclick = () => {
    const s = strategyById(b.dataset.delete);
    openWorkspaceDialog('删除策略', `<p>从策略库删除「${escapeHtml(s.name)}」？已有组合和策略原文件会保留。</p>`, '删除', async () => editLibrary(s.id, 'delete'));
  });
}

async function editLibrary(id, action, name) {
  if (!isDesktop('edit_library_strategy')) throw new Error('请在桌面应用中保存策略变更');
  const result = await callApi('edit_library_strategy', {id, action, name});
  if (!result.ok) throw new Error(result.error);
  state.strategies = result.data;
  renderAll();
}

function renderDailyCards() {
  $('dailyCardGrid').innerHTML = state.dailyCatalog.map(asset => {
    const r = state.dailyResults[asset.id];
    const s = r?.strategy || {};
    const q = r?.quote || {};
    const direction = s.direction_code || 'WAIT';
    return `<button type="button" class="daily-card ${direction.toLowerCase()}" data-open-daily="${escapeHtml(asset.id)}">
      <header><div><h3>${escapeHtml(asset.symbol)}</h3><small>${escapeHtml(asset.name)}</small></div><span class="direction-pill">${escapeHtml(s.direction || '待生成')}</span></header>
      <dl><div><dt>入场区间</dt><dd>${dailyRange(s.entry_low, s.entry_high)}</dd></div><div><dt>止损</dt><dd>${dailyPrice(s.stop_loss)}</dd></div>${[1,2,3].map(i => `<div><dt>目标 ${i}</dt><dd>${dailyPrice(s['tp'+i])}</dd></div>`).join('')}</dl>
      <div class="card-quote"><span>现价</span><strong>${q.price == null ? '--' : money(q.price)}</strong><em class="${resultClass(q.change_pct)}">${q.change_pct == null ? '--' : signed(q.change_pct, '%')}</em></div>
      <p class="card-note">${escapeHtml(s.condition || '点击生成策略，查看判断依据')}</p><footer><span>${r ? dailyTime(r.generated_at) : '尚未生成'}${r?.preview ? ' · 示例' : ''}</span><span>查看详情 ↗</span></footer></button>`;
  }).join('');
  $('dailyCardGrid').querySelectorAll('[data-open-daily]').forEach(b => b.onclick = () => openDailyDetail(b.dataset.openDaily));
}

function showDailyOverview() {
  $('dailyOverview').classList.remove('is-hidden');
  $('dailyDetail').classList.add('is-hidden');
  renderDailyCards();
  if (!dailyAutoLoaded && isDesktop('generate_daily_strategy')) {
    dailyAutoLoaded = true;
    refreshAllDaily();
  }
}

function openDailyDetail(id) {
  if (state.dailyLoading) return;
  $('dailyOverview').classList.add('is-hidden');
  $('dailyDetail').classList.remove('is-hidden');
  selectDailyAsset(id);
  document.querySelector('.daily-evidence').open = true;
  $('workspace').scrollTo({top: 0});
}

async function refreshAllDaily() {
  if (refreshingCards || state.dailyLoading) return;
  refreshingCards = true;
  const button = $('refreshAllDaily');
  button.disabled = true;
  let errors = 0;
  for (let i = 0; i < state.dailyCatalog.length; i++) {
    button.textContent = `更新 ${i + 1} / ${state.dailyCatalog.length}`;
    const asset = state.dailyCatalog[i];
    try {
      const result = await callApi('generate_daily_strategy', {asset_id: asset.id, force: i === 0});
      if (!result.ok) throw new Error(result.error);
      state.dailyResults[asset.id] = result.data;
      renderDailyCards();
      if (state.dailyAssetId === asset.id && !$('dailyDetail').classList.contains('is-hidden')) renderDailyStrategy(result.data);
    } catch (_) { errors++; }
  }
  refreshingCards = false;
  button.disabled = false;
  button.textContent = '刷新全部';
  if (errors) showToast(`${errors} 个标的刷新失败，可进入详情重试`, 'error');
}

function renderResearchLinks(report) {
  let target = $('researchLinks');
  if (!target) {
    target = document.createElement('section');
    target.id = 'researchLinks';
    target.className = 'research-links';
    document.querySelector('.daily-evidence-body').append(target);
  }
  const symbol = report.asset?.symbol || state.dailyAssetId;
  const quoteUrl = 'https://finance.yahoo.com/quote/' + encodeURIComponent(symbol) + '/';
  const coinGlass = {
    SNDK: ['https://www.coinglass.com/nl/pro/futures/LiquidationHeatMap?coin=SNDK', 'SNDK/USDT 清算热力图'],
    MRVL: ['https://www.coinglass.com/currencies/MRVL', 'MRVL 永续合约数据'],
    SOXL: ['https://www.coinglass.com/currencies/SOXL', 'SOXL 永续合约数据'],
    NBIS: ['https://www.coinglass.com/liquidations/NBIS', 'NBIS 清算数据'],
  }[symbol];
  target.innerHTML = `<h4>查看原始数据</h4><p>流动性区间来自价格结构估算；外部页面用于复核。</p><div class="external-buttons"><a class="button secondary" href="${quoteUrl}" target="_blank" rel="noopener noreferrer">${escapeHtml(symbol)} 行情与新闻 ↗</a>${report.asset?.options_supported ? `<a class="button secondary" href="https://www.cboe.com/delayed_quotes/${encodeURIComponent(symbol)}/quote_table" target="_blank" rel="noopener noreferrer">${escapeHtml(symbol)} 期权链 ↗</a>` : ''}</div><p>CoinGlass：尚未核验到该标的的对应页面。</p>`;
  if (coinGlass) {
    target.lastElementChild.textContent = 'CoinGlass 对应股票永续合约；其清算与持仓数据应和正股行情分别理解。';
    const link = document.createElement('a');
    link.className = 'button secondary';
    link.href = coinGlass[0];
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.textContent = coinGlass[1] + ' ↗';
    const liquidity = [...$('dailyEvidenceModules').querySelectorAll('article')].find(el => el.querySelector('strong')?.textContent.includes('流动性'));
    (liquidity || target.querySelector('.external-buttons')).append(link);
  }
}

async function saveAppearance(kind, dataUrl) {
  if (!isDesktop('save_appearance')) throw new Error('请在桌面应用中保存外观设置');
  const result = await callApi('save_appearance', {kind, data_url: dataUrl});
  if (!result.ok) throw new Error(result.error);
  workspaceSettings = result.data;
  applyAppearance();
  showToast('外观已保存', 'success');
}

function bindWorkspaceEvents() {
  $('backDaily').onclick = showDailyOverview;
  $('refreshAllDaily').onclick = refreshAllDaily;
  $('closeWorkspaceDialog').onclick = $('cancelWorkspaceDialog').onclick = () => $('workspaceDialog').close();
  $('workspaceForm').onsubmit = async event => {
    event.preventDefault();
    if (!workspaceSubmit) return;
    const button = $('submitWorkspaceDialog');
    button.disabled = true;
    try { await workspaceSubmit(); $('workspaceDialog').close(); }
    catch (error) { $('workspaceDialogError').textContent = error.message; }
    finally { button.disabled = false; }
  };
  $('addDailyAsset').onclick = () => openWorkspaceDialog('添加标的', '<label>股票或 ETF 代码<input id="newAssetSymbol" placeholder="例如 AAPL、MU、0700.HK" required maxlength="20" autocomplete="off"></label><p>核验市场后添加到策略总览。</p>', '添加', async () => {
    if (!isDesktop('add_daily_asset')) throw new Error('请在桌面应用中添加标的');
    const previousIds = new Set(state.dailyCatalog.map(asset => asset.id));
    const result = await callApi('add_daily_asset', {symbol: $('newAssetSymbol').value});
    if (!result.ok) throw new Error(result.error);
    state.dailyCatalog = result.data;
    renderDailyAssetPicker();
    renderDailyCards();
    const added = state.dailyCatalog.find(asset => !previousIds.has(asset.id));
    if (added) {
      const report = await callApi('generate_daily_strategy', {asset_id: added.id});
      if (report.ok) state.dailyResults[added.id] = report.data;
      else showToast('标的已添加，策略生成失败，可进入详情重试', 'error');
      renderDailyCards();
    }
  });
  for (const kind of ['icon', 'background']) {
    $(kind + 'Choose').onclick = () => $(kind + 'Upload').click();
    $(kind + 'Upload').onchange = async event => {
      const file = event.target.files[0];
      if (!file) return;
      try {
        if (file.size > 8 * 1024 * 1024) throw new Error('图片不能超过 8 MB');
        const value = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        await saveAppearance(kind, value);
      } catch (error) { showToast(error.message, 'error'); }
      event.target.value = '';
    };
  }
  document.querySelectorAll('[data-reset-image]').forEach(button => button.onclick = () => saveAppearance(button.dataset.resetImage, null).catch(error => showToast(error.message, 'error')));
  document.addEventListener('click', event => document.querySelectorAll('.row-menu[open]').forEach(menu => { if (!menu.contains(event.target)) menu.open = false; }));
}
