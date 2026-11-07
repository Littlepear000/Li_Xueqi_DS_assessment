/* PIA Review - front-end logic (vanilla JS, talks to the FastAPI JSON API). */
'use strict';
const APP_BUILD = window.APP_BUILD || '';   // injected by the server from piaa/__init__.py on disk (no manual bump)

const api = {
  async get(url) { const r = await fetch(url); if (!r.ok) throw new Error(await r.text()); return r.json(); },
  async post(url, body) { const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body || {}) }); if (!r.ok) throw new Error(await r.text()); return r.json(); },
};
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmtUsd = (v) => v == null ? '—' : Number(v).toLocaleString('en-US');
const fmtTs = (s) => s ? s.replace('T', ' ').replace('Z', '') : '';
const fmtDur = (sec) => { if (sec == null || isNaN(sec)) return '—'; sec = Math.max(0, sec); if (sec < 60) return sec.toFixed(sec < 10 ? 1 : 0) + ' s';
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), x = Math.floor(sec % 60); const mm = String(m).padStart(2, '0'), ss = String(x).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`; };
const isoDur = (a, b) => (a && b ? (Date.parse(b) - Date.parse(a)) / 1000 : null);
// live timer of the running job (updates one element every second, no page re-render)
function jobNow(j) { return Date.now() / 1000 - (j._offset || 0); }
// projects running right now (several when the run is parallel)
function jobRunning(j) { return j && j.status === 'running' ? (j.running && j.running.length ? j.running : (j.current ? [j.current] : [])) : []; }
function tickJobTimer() {
  const el = document.getElementById('jobTimer'); const j = state.review && state.review.job;
  if (!el || !j || j.status !== 'running') return;
  const now = jobNow(j);
  const cur = state.review.cur; const st = (j.running_started || {})[cur] || (j.current === cur ? j.current_started_ts : null);
  const nRun = jobRunning(j).length;
  el.textContent = `${st ? 'this project ' + fmtDur(now - st) + ' · ' : ''}${nRun > 1 ? nRun + ' running in parallel · ' : ''}total ${fmtDur(now - j.started_ts)}`;
}
setInterval(tickJobTimer, 1000);
function jobReportHtml(j) {
  const rows = Object.entries(j.results || {}); const cnt = {}; rows.forEach(([, v]) => { cnt[v] = (cnt[v] || 0) + 1; });
  const total = j.ended_ts && j.started_ts ? j.ended_ts - j.started_ts : null; const timed = rows.filter(([pid]) => j.durations && j.durations[pid] != null);
  const avg = timed.length ? timed.reduce((t, [pid]) => t + j.durations[pid], 0) / timed.length : null;
  const pillOf = (v) => `<span class="pill ${v === 'done' ? 'p-ok' : v === 'reused' ? 'p-muted' : v === 'cancelled' ? 'p-warn' : 'p-bad'}">${esc(v)}</span>`;
  return `<div class="runreport"><div class="toolbar"><b>${j.status === 'finished' ? '✔ Run finished' : j.status === 'cancelled' ? '■ Run stopped' : '⚠ Run ended: ' + esc(j.status)}</b>
    <span>in <b>${fmtDur(total)}</b> · ${rows.length} project${rows.length === 1 ? '' : 's'}${Object.entries(cnt).map(([k, v]) => ` · ${v} ${esc(k)}`).join('')}${avg != null ? ` · avg ${fmtDur(avg)} per project run` : ''}</span>
    <button class="btn sm ghost right" id="btnCloseReport">×</button></div>
    <details class="rrdet"><summary>Per-project times (${rows.length})</summary>
    <table><tr><th>Project</th><th>Result</th><th>Time</th></tr>${rows.map(([pid, v]) => `<tr class="rrrow" data-jump="${esc(pid)}" title="open ${esc(pid)}"><td class="mono">${esc(pid)}</td><td>${pillOf(v)}</td><td>${v === 'reused' ? '<span class="muted">cached</span>' : fmtDur((j.durations || {})[pid])}</td></tr>`).join('')}</table></details></div>`;
}
const STATUS_PILL = { pushed: 'p-lock', reviewed: 'p-rev', generated: 'p-gen', 'no documents': 'p-bad', 'not run': 'p-muted', failed: 'p-bad', 'out of scope': 'p-muted' };
const pill = (s) => `<span class="pill ${STATUS_PILL[s] || 'p-muted'}">${esc(t('s.' + s, s))}</span>`;


// ---------------------------------------------------------------- i18n (English / 中文 toggle; dynamic data stays English)
const I18N = {
  'nav.database': ['Database', '数据库'], 'nav.analytics': ['Analytics', '分析'], 'nav.review': ['Approach Spot', '方法识别'], 'nav.patterns': ['Patterns', '模式分析'], 'nav.workflow': ['Workflow', '工作流'], 'nav.setup': ['Setup', '设置'],
  'db.groupby': ['Group by', '分组'], 'db.fields': ['⚙ Fields', '⚙ 字段'], 'db.exportPushed': ['Export pushed ↓', '导出已推送 ↓'], 'db.exportAll': ['Export all ↓', '导出全部 ↓'],
  'an.sub': ['current values in the database', '数据库当前值'], 'rv.new': ['Choose other projects', '换一批项目'], 'rv.hint': ['One page per project · progress is shown on the heat map', '每个项目一页 · 进度显示在热力图上'], 'rv.current': ['Current session', '当前会话'], 'rv.none': ['Configure the projects on the left, pick a workflow on the right, then start.', '左侧配置项目，右侧选择工作流，然后开始。'], 'rv.start': ['▶ Extract approaches', '▶ 提取 Approaches'],
  'wf.sub': ['one folder per version · defined in code', '每个版本一个文件夹 · 由代码定义'], 'wf.legendPy': ['Python step', 'Python 步骤'], 'wf.legendLlm': ['LLM step', 'LLM 步骤'], 'wf.legendData': ['data', '数据'],
  'wf.clickHint': ['Click a step to see its code, prompt files and inputs / outputs.', '点击步骤查看代码、prompt 文件和输入/输出。'],
  'wf.compare': ['Compare two versions', '对比两个版本'], 'wf.compareBtn': ['Generate comparison report', '生成对比报告'], 'su.sub': ['data sources & engine', '数据源与引擎'],
  // column headers
  'col.project_id': ['Project', '项目'], 'col.n': ['# Approaches', '方法数'], 'col.approaches': ['Approaches', '方法'], 'col.project_name': ['Name', '名称'], 'col.country': ['Country', '国家'], 'col.region': ['Region', '区域'],
  'col.vertical': ['Vertical', 'Vertical'], 'col.lead_practice': ['Lead practice', '牵头部门'], 'col.status': ['Status', '项目状态'], 'col.approval_date': ['Approval', '批准日期'], 'col.commitment_usd': ['Commitment USD', '承诺额 USD'],
  'col.sectors': ['Sectors', '部门'], 'col.themes': ['Themes', '主题'], 'col.innovative': ['Innovative?', '是否创新'], 'col.mentioned': ['Mentioned only', '仅提及'], 'col.review_status': ['Review', '审核状态'], 'col.last_change': ['Last change', '最近变更'],
  // field labels
  'f.name': ['Approach name', '方法名称'], 'f.category': ['Category', '类别'], 'f.solution': ['Solution', '解决方案'], 'f.sector': ['Sector', '部门'], 'f.theme': ['Theme', '主题'],
  'f.adoption': ['Adoption', '采用情况'], 'f.repeated': ['Repeated from another project', '与其他项目重复'], 'f.source': ['Source paragraph', '原文句子'], 'f.desc': ['Description & rationale', '说明与理由'],
  'f.other': ['Other coded sentences', '其他编码句子'], 'f.history': ['History', '历史'], 'f.review': ['Review in context', '查看上下文'],
  'f.applied': ['applied', '已采用'], 'f.mentioned': ['mentioned', '仅提及'], 'f.apply': ['apply', '已采用'], 'f.prospect': ['prospect', '展望/未来'], 'f.discuss': ['discuss', '仅讨论'],
  'm.future_plan': ['future plan', '未来计划'], 'm.aspiration_or_vision': ['aspiration / vision', '愿景或期望'], 'm.other_program': ['other programme', '其他项目/背景'], 'm.lesson_or_reference': ['lesson / reference', '经验或引用'],
  'm.option_considered': ['option considered', '设计中考虑的选项'], 'm.parent_or_prior': ['parent / prior project', '母项目或既有系统'], 'm.unclear': ['unclear', '不明确'],
  // statuses
  's.pushed': ['pushed', '已推送'], 's.reviewed': ['reviewed', '已审核'], 's.generated': ['generated', '已生成'], 's.no documents': ['no documents', '无文档'], 's.not run': ['not run', '未运行'], 's.failed': ['failed', '失败'], 's.out of scope': ['out of scope', '范围外'],
  // context viewer
  'cx.title': ['Review in context', '原文上下文'], 'cx.pages': ['Pages', '页数'], 'cx.generating': ['Rebuilding the document around this sentence…', '正在重建该句周围的原文…'],
  'cx.legend': ['evidence · other coded sentence · approach keyword · ▌aspiration wording · ▌commitment wording', '证据句 · 其他编码句 · 方法关键词 · ▌愿景/期望措辞 · ▌承诺/实施措辞'],
  'cx.position': ['position in document', '在文档中的位置'], 'cx.coded': ['coded sentences in window', '窗口内编码句'],
  // compare report
  'cmp.steps': ['Steps', '步骤'], 'cmp.onlyA': ['only in', '仅在'], 'cmp.shared': ['shared', '共有'], 'cmp.prompts': ['Prompts', 'Prompt 文件'], 'cmp.config': ['Config differences', '配置差异'], 'cmp.results': ['Results in this database', '本数据库中的结果'],
  'cmp.same': ['same', '相同'], 'cmp.changed': ['changed', '已修改'], 'cmp.projects': ['projects run', '已运行项目'], 'cmp.headline': ['headline approaches', '计入统计的方法'], 'cmp.changelog': ['Changelog', '变更记录'],
  'cmp.summary': ['Summary', '摘要'],
  'db.export': ['Export', '导出'],
  'sp.config': ['Configuration', '配置'], 'sp.workflow': ['Workflow', '工作流'], 'sp.method': ['Methodology (workflow.html)', '方法说明 (workflow.html)'], 'sp.code': ['code', '代码'],
  'sp.fromDb': ['from database', '来自数据库'], 'sp.ids': ['project IDs', '个项目 ID'], 'sp.workflowLbl': ['workflow', '工作流'],
  'cd.steps': ['Steps', '步骤'], 'cd.files': ['Workflow folder', '工作流文件夹'], 'cd.modules': ['Package modules used', '引用的包模块'], 'cd.prev': ['Previous step', '上一步'], 'cd.next': ['Next step', '下一步'],
  'cd.function': ['Function', '函数'], 'cd.file': ['Defined in', '定义位置'], 'cd.inputs': ['Inputs', '输入'], 'cd.outputs': ['Outputs', '输出'], 'cd.prompts': ['Prompt files', 'Prompt 文件'], 'cd.source': ['Python source', 'Python 源码'],
  'cd.shared': ['inherited', '继承'], 'cd.imports': ['Imports from the package', '从包中引用'],
  'pt.sub': ['replication & scaling across the portfolio', '全组合的复制与扩展'], 'pt.result': ['Result', '结果'], 'pt.workflow': ['Workflow', '工作流'], 'pt.run': ['▶ Run pattern analysis', '▶ 运行模式分析'],
  'pt.tabRep': ['Replication', '复制 (Replication)'], 'pt.tabScale': ['Scaling', '扩展 (Scaling)'], 'pt.provisional': ['provisional', '暂定'],
  'pt.s1': ['Which approaches were reused most?', '哪些方法被重复使用最多？'], 'pt.s2': ['Replication by sector', '按行业的复制情况'], 'pt.s3': ['Over time: first use vs reuse', '随时间：首次使用 vs 复用'], 'pt.s4': ['By region', '按区域'],
  'pt.f3c': ['approaches judged by the model', '模型判断的方法数'], 'pt.f3cs': ['same-approach links verified', '确认为同一方法的链接'], 'pt.confirmed': ['confirmed', '确认'], 'pt.likely': ['likely', '可能'],
  'pt.srcIn': ['source in portfolio', '来源在样本内'], 'pt.scaleS3': ['same approach earlier · same country + sector', '同一方法更早出现 · 同国家 + 同部门'],
  'pt.s0': ['Replication and scaling per approach', '每个方法的复制与扩展'], 'pt.s0n': ['approaches flagged', '个方法被标记'], 'pt.s0flag': ['Flagged only', '只看被标记的'], 'pt.s0all': ['Show all approaches', '显示全部方法'],
  'pt.s0h': ['Replication: confirmed = the passages state the project replicated / learned from an earlier project (source named or identifiable); likely = earlier experience mentioned without a name, and the same approach exists in an earlier project of another country. Scaling: the same approach was verified in an earlier project of the same country and sector. Hover a level for the model\'s reason.', '复制：确认 = 原文明确说明本项目复制/借鉴了更早的项目（来源有名字或可识别）；可能 = 原文提到借鉴以往经验但未点名，且在另一国家更早的项目中存在同一方法。扩展：同一方法在同一国家、同一部门更早的项目中已被确认。悬停在等级上可查看模型理由。'],
  'pt.srcNone': ['source not identified', '来源未识别'], 'pt.rules': ['The model did not run (no API key for the selected provider, or the provider is mock), so the results below come from <b>rules only</b>: explicit project references and cue language for replication, similarity above the rule threshold for scaling. Set the key in Setup and re-run for model judgements.', '模型未运行（所选 provider 没有 API key，或 provider 为 mock），以下结果<b>仅来自规则</b>：复制看显式项目引用和线索语言，扩展看超过规则阈值的相似度。在 Setup 设置 key 后重跑可得到模型判断。'], 'pt.approach': ['Approach', '方法'], 'pt.sameOnly': ['same approach, no link type', '同一方法，未定类型'],
  'pt.kApproaches': ['validated approaches', '已验证方法'], 'pt.kPatterns': ['replicated approaches', '被复制的方法'], 'pt.kReuse': ['reuse events', '复用次数'], 'pt.kShare': ['of approaches are part of a replicated pattern', '的方法属于被复制的模式'], 'pt.kScale': ['scaling candidates', '扩展候选'],
  'pt.origin': ['origin', '首创'], 'pt.rep': ['Replication', '复制'], 'pt.scale': ['Scaling', '扩展'], 'pt.both': ['Both', '全部'],
  'pt.f1': ['validated approaches', '已验证方法'], 'pt.f2': ['candidate pairs', '候选配对'], 'pt.f3': ['verified same approach', '验证为同一方法'],
  'pt.repS': ['same approach, different country', '同一方法，不同国家'], 'pt.scaleS': ['same approach, same country', '同一方法，同一国家'],
  'pt.kf': ['Key findings', '关键发现'], 'pt.s5': ['Verification log', '验证记录'], 'pt.s4': ['Countries', '国家'], 'pt.s3': ['Over time', '时间趋势'], 'pt.s2': ['By sector', '按行业'],
  'pt.s1': ['Which approaches were repeated most?', '哪些方法重复最多？'], 'pt.runV': ['Run', '运行'], 'pt.reuse': ['reuse', '复用'], 'pt.first': ['first use', '首次使用'], 'pt.allSectors': ['All sectors', '全部行业'], 'pt.allRegions': ['All regions', '全部区域'], 'f.stage': ['Stage', '阶段'], 'f.repeatedS': ['Repeated from', '重复来源'],
  'st.mentioned': ['Mentioned', '仅提及'], 'st.planned': ['Planned', '计划中'], 'st.implemented': ['Implemented', '已实施'],
  'st.mentionedB': ['mentioned, not adopted by the project', '仅提及，项目未采用'], 'st.implB': ['evidence in', '证据来自'], 'st.planB': ['design documents only', '仅见于设计文件'], 'db.addFilter': ['Filter', '筛选'], 'db.reset0': ['Reset', '重置'], 'db.addFilter2': ['Add filter', '添加筛选'], 'db.exportAllP': ['All projects', '全部项目'], 'db.exportAllH': ['Every project in the database', '数据库中的所有项目'],
  'db.exportPushedP': ['Pushed projects only', '仅已推送项目'], 'db.exportPushedH': ['Signed-off results only', '仅已确认的结果'],
  'db.search': ['Search ID, name, country, approach…', '搜索 ID、名称、国家、方法…'], 'db.clearAll': ['Clear all', '清除全部'], 'db.clear': ['Clear', '清除'],
  'db.anyOf': ['is any of', '属于其一'], 'db.find': ['Find…', '查找…'], 'db.noMatch': ['No match', '无匹配'], 'db.fieldsLbl': ['Fields', '字段'],
  'db.showFields': ['Show fields', '显示字段'], 'db.reset': ['Reset to default', '恢复默认'], 'db.remember': ['Remembered in this browser.', '在此浏览器中记住。'],
  'db.empty': ['No projects match the current filters.', '没有符合当前筛选条件的项目。'], 'col.repeated': ['Repeated', '重复'],
  'fl.vertical': ['Vertical', 'Vertical'], 'fl.region': ['Region', '区域'], 'fl.country': ['Country', '国家'], 'fl.sector': ['Sector', '部门'], 'fl.theme': ['Theme', '主题'],
  'fl.innovative': ['Innovative?', '是否创新'], 'fl.ap': ['# Approaches', '方法数'], 'fl.repeated': ['Repeated', '重复'], 'fl.review': ['Review', '审核状态'], 'fl.status': ['Status', '项目状态'],
  'gb.none': ['None', '不分组'], 'gb.vertical': ['Vertical', 'Vertical'], 'gb.region': ['Region', '区域'], 'gb.country': ['Country', '国家'], 'gb.lead_practice': ['Lead practice', '牵头部门'], 'gb.status': ['Status', '项目状态'], 'gb.review': ['Review status', '审核状态'],
  'rp.verify': ['Verify', '核对'], 'rp.title': ['Verify replication', '核对重复方法'], 'rp.this': ['This project', '本项目'], 'rp.other': ['Other project', '对方项目'], 'rp.confirm': ['Confirm link', '确认重复'], 'rp.reject': ['Reject link', '否决'], 'rp.open': ['Open other project', '打开对方项目'], 'rp.verdict': ['Verdict', '核对结论'],
};
let LANG = 'en';
try { LANG = localStorage.getItem('pia_lang') || 'en'; } catch (e) { /* ignore */ }
function t(key, fallback) { const e = I18N[key]; if (!e) return fallback != null ? fallback : key; return LANG === 'zh' ? e[1] : e[0]; }
function applyLang() {
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = t(el.dataset.i18n, el.textContent); });
  $('langToggle').textContent = LANG === 'zh' ? 'English' : '中文';
}
function toggleLang() { LANG = LANG === 'zh' ? 'en' : 'zh'; try { localStorage.setItem('pia_lang', LANG); } catch (e) { /* ignore */ } applyLang(); const v = document.querySelector('.nav button.active').dataset.view; go(v); if (document.body.classList.contains('drawer-open')) renderDrawer(); }

const state = { projects: [], setup: null, workflows: [], quick: { vertical: new Set(), status: new Set(), ap: new Set(), review: new Set() }, groupBy: 'vertical',
  visible: null, drawer: { id: null, ap: 0, data: null }, review: { session: null, ids: [], cur: null, filter: 'all', job: null, data: null, ap: 0 }, taxonomy: null };

const FIELDS = [['project_id', 'Project', 1], ['n', '# Approaches', 1], ['approaches', 'Approaches', 1], ['country', 'Country', 1], ['sectors', 'Sectors', 1],
  ['innovative', 'Innovative?', 1], ['themes', 'Themes', 1], ['repeated', 'Repeated', 1], ['mentioned', 'Mentioned only', 1],
  ['project_name', 'Name', 0], ['region', 'Region', 0], ['vertical', 'Vertical', 0], ['lead_practice', 'Lead practice', 0], ['status', 'Status', 0],
  ['approval_date', 'Approval', 0], ['commitment_usd', 'Commitment USD', 0], ['review_status', 'Review', 0], ['last_change', 'Last change', 0]];
function defaultFields() { return Object.fromEntries(FIELDS.map((f) => [f[0], !!f[2]])); }
state.visible = defaultFields();
try { const v = localStorage.getItem('pia_fields_v2'); if (v) Object.assign(state.visible, JSON.parse(v)); } catch (e) { /* ignore */ }
try { const g = localStorage.getItem('pia_groupby'); if (g != null) state.groupBy = g; } catch (e) { /* ignore */ }

// ---------------------------------------------------------------- navigation
function go(v) {
  if (v === 'workflow') v = 'review';   // the workflow page now lives inside Approach Spot
  closeDrawer(); closeHist(); closePop();
  document.querySelectorAll('.view').forEach((e) => e.classList.remove('active'));
  $('view-' + v).classList.add('active');
  const navV = v === 'code' ? ((state.code || {}).back || 'review') : v;
  document.querySelectorAll('.nav button').forEach((b) => b.classList.toggle('active', b.dataset.view === navV));
  window.scrollTo(0, 0);
  if (v === 'database') { state.newSince = undefined; markDbSeen(); loadProjects(); }
  if (v === 'analytics') loadAnalytics();
  if (v === 'patterns') loadPatterns();
  if (v === 'setup') { loadSetup(); loadExamples(); }
  if (v === 'review') { renderReview(); loadWorkflows(); }
}
document.querySelectorAll('.nav button').forEach((b) => b.addEventListener('click', () => go(b.dataset.view)));
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closePop(); $('exportMenu').classList.remove('open'); closeDrawer(); closeHist(); } });

// ---------------------------------------------------------------- database
// Toolbar: search + filter fields (each opens a popover) + group-by + fields chooser, all in one row above the table.
const FILTERS = [
  { key: 'vertical', label: 'Vertical', get: (p) => p.vertical, primary: 1 },
  { key: 'region', label: 'Region', get: (p) => p.region },
  { key: 'country', label: 'Country', get: (p) => p.country, primary: 1 },
  { key: 'sector', label: 'Sector', get: (p) => (p.sectors || []).map((s) => s.name), primary: 1 },
  { key: 'theme', label: 'Theme', get: (p) => (p.themes || []).map((s) => s.name) },
  { key: 'innovative', label: 'Innovative?', get: (p) => p.innovative || '—', primary: 1 },
  { key: 'ap', label: '# Approaches', get: (p) => { const n = nOf(p); return n == null ? 'not run' : (n >= 2 ? '2+' : String(n)); }, order: ['0', '1', '2+', 'not run'], primary: 1 },
  { key: 'repeated', label: 'Repeated', get: (p) => (nRepeated(p) ? 'Yes' : 'No'), order: ['Yes', 'No'] },
  { key: 'review', label: 'Review', get: (p) => p.review_status, order: ['not run', 'generated', 'reviewed', 'pushed', 'no documents', 'failed', 'out of scope'] },
  { key: 'status', label: 'Status', get: (p) => p.status },
];
FILTERS.forEach((f) => { state.quick[f.key] = state.quick[f.key] || new Set(); });
const shownExtra = new Set(); // secondary filters added via "+ Filter"
const GROUPS = [['', 'None'], ['vertical', 'Vertical'], ['region', 'Region'], ['country', 'Country'], ['lead_practice', 'Lead practice'], ['status', 'Status'], ['review', 'Review status']];
// column widths (px); the Approaches column takes the remaining space
const COLW = { project_id: 86, n: 64, project_name: 220, country: 108, region: 84, vertical: 104, lead_practice: 130, status: 80, approval_date: 92,
  commitment_usd: 118, sectors: 150, themes: 150, innovative: 88, repeated: 84, mentioned: 84, review_status: 104, last_change: 140 };
const AP_MIN = 340;
const TH_SHORT = { n: ['# Appr.', '方法数'], mentioned: ['Mentioned', '仅提及'] };

async function loadProjects() { try { state.projects = await api.get('/api/projects'); } catch (e) { $('dbtable').innerHTML = `<tr><td class="muted">Could not load projects: ${esc(e.message)}</td></tr>`; return; } renderTable(); }

function nOf(p) { return p.n_approaches; }
function nRepeated(p) { return (p.approaches || []).filter((a) => (a.replication || []).length).length; }
const asList = (v) => (Array.isArray(v) ? v : [v]).filter((x) => x != null && x !== '');
function filtered(skipKey) {
  const q = ($('q').value || '').trim().toLowerCase();
  return state.projects.filter((p) => {
    for (const f of FILTERS) {
      if (f.key === skipKey) continue;
      const sel = state.quick[f.key]; if (!sel.size) continue;
      if (!asList(f.get(p)).some((v) => sel.has(v))) return false;
    }
    if (q) {
      const hay = [p.project_id, p.project_name, p.country, ...(p.approaches || []).map((a) => a.name)].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}
const chips = (arr, max) => {
  const s = [...(arr || [])].sort((a, b) => (b.pct || 0) - (a.pct || 0));
  const tip = s.map((x) => `${x.name}${x.pct != null ? ' ' + Math.round(x.pct) + '%' : ''}`).join('\n');
  return `<div class="chipcell" title="${esc(tip)}">` + s.slice(0, max).map((x) => `<span class="schip">${esc(x.name)}${x.pct != null ? ` <b>${Math.round(x.pct)}%</b>` : ''}</span>`).join('') +
    (s.length > max ? `<span class="more">+${s.length - max}</span>` : '') + '</div>';
};
function cell(p, k) {
  switch (k) {
    case 'project_id': return `<b title="${esc(p.project_name || '')}">${p.project_id}</b>${state.newSince && p.last_change && p.last_change.at && p.last_change.at > state.newSince ? '<span class="rownew">New</span>' : ''}`;
    case 'n': { const n = nOf(p); return `<span class="${n == null ? 'muted' : (n === 0 ? 'ncount zero' : 'ncount')}">${n == null ? '—' : n}</span>`; }
    case 'approaches': {
      if (p.review_status === 'no documents' || p.review_status === 'not run' || p.review_status === 'out of scope') return `<span class="muted">${esc(t('s.' + p.review_status, p.review_status))}</span>`;
      if (!p.approaches.length) return '<span class="muted">— none at L2/L3</span>';
      const MAX = 3; const list = p.approaches;
      return `<ol class="aplist" title="${esc(list.map((x, i) => (i + 1) + '. ' + x.name).join('\n'))}">` + list.slice(0, MAX).map((x) => `<li>${esc(x.name)}</li>`).join('') + '</ol>' +
        (list.length > MAX ? `<span class="more">+${list.length - MAX} more</span>` : '');
    }
    case 'sectors': return chips(p.sectors, 2);
    case 'themes': return chips(p.themes, 2);
    case 'commitment_usd': return `<span class="num">${fmtUsd(p.commitment_usd)}</span>`;
    case 'innovative': return p.innovative ? `<span class="pill ${p.innovative === 'Yes' ? 'p-ok' : p.innovative === 'No' ? 'p-muted' : 'p-warn'}">${esc(p.innovative)}</span>` : '<span class="muted">—</span>';
    case 'repeated': {
      const r = (p.approaches || []).filter((a) => (a.replication || []).length); if (!r.length) return '<span class="muted">0</span>';
      const ok = r.filter((a) => a.replication_verdict === 'confirmed').length;
      const tip = r.map((a) => `${a.name} ← ${a.replication.map((l) => l.other_project_id).join(', ')}${a.replication_verdict ? ' [' + a.replication_verdict + ']' : ''}`).join('\n');
      return `<span class="pill p-info" title="${esc(tip)}">${r.length}</span>${ok ? ` <span class="muted" style="font-size:11px">✓${ok}</span>` : ''}`;
    }
    case 'mentioned': return p.n_mentioned_only ? `<span class="pill p-warn">${p.n_mentioned_only}</span>` : '<span class="muted">0</span>';
    case 'review_status': return pill(p.review_status);
    case 'last_change': return p.last_change && p.last_change.at ? `${fmtTs(p.last_change.at).slice(0, 16)} <span class="muted">${p.last_change.source}${p.last_change.workflow ? ' ' + p.last_change.workflow : ''}</span>` : '—';
    default: return p[k] ? `<span class="ell" title="${esc(p[k])}">${esc(p[k])}</span>` : '<span class="muted">—</span>';
  }
}
function renderTable() {
  const rows = filtered(); const g = state.groupBy; const cols = FIELDS.filter((f) => state.visible[f[0]]);
  const hasAp = cols.some((f) => f[0] === 'approaches');
  const minW = cols.reduce((a, f) => a + (f[0] === 'approaches' ? AP_MIN : (COLW[f[0]] || 120)), 0);
  let h = '<colgroup>' + cols.map((f) => `<col${f[0] === 'approaches' ? '' : ` style="width:${COLW[f[0]] || 120}px"`}>`).join('') + '</colgroup>';
  h += '<thead><tr>' + cols.map((f) => `<th class="c-${f[0]}" title="${esc(t('col.' + f[0], f[1]))}">${TH_SHORT[f[0]] ? TH_SHORT[f[0]][LANG === 'zh' ? 1 : 0] : t('col.' + f[0], f[1])}</th>`).join('') + '</tr></thead><tbody>';
  const groups = {};
  rows.forEach((p) => { const key = g ? (g === 'review' ? p.review_status : (p[g] || 'Unspecified')) : ''; (groups[key] = groups[key] || []).push(p); });
  Object.keys(groups).sort().forEach((key, gi) => {
    const list = groups[key];
    if (g) { const run = list.filter((p) => nOf(p) != null).length; const sum = list.reduce((a, p) => a + (nOf(p) || 0), 0);
      h += `<tr class="ghead" data-gi="${gi}"><td colspan="${cols.length}"><span class="caret">▾</span> ${esc(key)}<span class="cnt">${list.length} projects</span><span class="sum">${run} run · ${sum} approaches</span></td></tr>`; }
    list.forEach((p) => { h += `<tr class="clickable" data-gi="${gi}" data-pid="${p.project_id}">` + cols.map((f) => `<td class="c-${f[0]}">${cell(p, f[0])}</td>`).join('') + '</tr>'; });
  });
  if (!rows.length) h += `<tr><td colspan="${cols.length}" class="muted" style="text-align:center;padding:28px">${t('db.empty', 'No projects match the current filters.')}</td></tr>`;
  const tb = $('dbtable'); tb.innerHTML = h + '</tbody>';
  // table fits the page; only when many columns are switched on does it get a minimum width (and scroll)
  tb.style.minWidth = (hasAp ? minW : minW) + 'px';
  tb.querySelectorAll('tr.clickable').forEach((tr) => tr.addEventListener('click', () => openDrawer(tr.dataset.pid)));
  tb.querySelectorAll('tr.ghead').forEach((tr) => tr.addEventListener('click', () => { tr.classList.toggle('closed'); tb.querySelectorAll(`tr.clickable[data-gi="${tr.dataset.gi}"]`).forEach((r) => r.style.display = tr.classList.contains('closed') ? 'none' : ''); }));
  $('dbCount').textContent = `· ${rows.length} of ${state.projects.length} projects`;
  renderDbBar();
}

// --- toolbar buttons
function renderDbBar() {
  $('q').placeholder = t('db.search', 'Search ID, name, country, approach…');
  const vis = FILTERS.filter((f) => f.primary || shownExtra.has(f.key) || state.quick[f.key].size);
  let h = vis.map((f) => {
    const sel = [...state.quick[f.key]];
    const val = sel.length === 1 ? `: <b>${esc(sel[0])}</b>` : sel.length > 1 ? `: <b>${sel.length}</b>` : '';
    return `<button class="fbtn ${sel.length ? 'on' : ''} ${popState.anchor === 'f:' + f.key ? 'open' : ''}" data-pop="f:${f.key}">${esc(t('fl.' + f.key, f.label))}${val} <span class="cv">▾</span></button>`;
  }).join('');
  const n = FILTERS.reduce((a, f) => a + state.quick[f.key].size, 0);
  if (vis.length < FILTERS.length) h += `<button class="fbtn add ${popState.anchor === 'more' ? 'open' : ''}" data-pop="more">＋ ${t('db.addFilter', 'Filter')}</button>`;
  if (n || $('q').value) h += `<button class="fbtn link" id="clearQ" title="${t('db.clearAll', 'Clear all')}">✕ ${t('db.reset0', 'Reset')}</button>`;
  $('dbFilters').innerHTML = h;
  const gl = (GROUPS.find((x) => x[0] === state.groupBy) || GROUPS[0])[1];
  $('btnGroup').innerHTML = `☰ ${state.groupBy ? `<b>${esc(t('gb.' + state.groupBy, gl))}</b>` : t('db.groupby', 'Group by')} <span class="cv">▾</span>`; $('btnGroup').title = t('db.groupby', 'Group by');
  $('btnGroup').classList.toggle('on', !!state.groupBy);
  const hidden = FIELDS.filter((f) => !state.visible[f[0]]).length;
  $('btnFields').innerHTML = `⚙ ${t('db.fieldsLbl', 'Fields')}${hidden ? ` <span class="muted">(${FIELDS.length - hidden}/${FIELDS.length})</span>` : ''} <span class="cv">▾</span>`;
  $('dbFilters').querySelectorAll('[data-pop]').forEach((b) => b.addEventListener('click', (e) => { e.stopPropagation(); togglePop(b.dataset.pop, b); }));
  const cq = $('clearQ'); if (cq) cq.addEventListener('click', () => { FILTERS.forEach((f) => state.quick[f.key].clear()); shownExtra.clear(); $('q').value = ''; closePop(); renderTable(); });
}

// --- single shared popover, anchored under the clicked button
const popState = { anchor: null, search: '' };
function closePop() { popState.anchor = null; popState.search = ''; $('dbPop').classList.remove('open'); document.querySelectorAll('.fbtn.open').forEach((b) => b.classList.remove('open')); }
function togglePop(anchor, btn) {
  if (popState.anchor === anchor) { closePop(); return; }
  closePop(); popState.anchor = anchor; btn.classList.add('open');
  const pop = $('dbPop'); const bar = $('dbbar').getBoundingClientRect(); const r = btn.getBoundingClientRect();
  pop.classList.add('open'); fillPop();
  const w = pop.offsetWidth; let left = r.left - bar.left; if (left + w > bar.width) left = Math.max(0, r.right - bar.left - w);
  pop.style.left = left + 'px'; pop.style.top = (r.bottom - bar.top + 6) + 'px';
}
function fillPop() {
  const pop = $('dbPop'); const a = popState.anchor; if (!a) return;
  if (a.startsWith('f:')) {
    const f = FILTERS.find((x) => x.key === a.slice(2)); const sel = state.quick[f.key];
    const counts = {}; filtered(f.key).forEach((p) => new Set(asList(f.get(p))).forEach((v) => { counts[v] = (counts[v] || 0) + 1; }));
    const all = new Set(); state.projects.forEach((p) => asList(f.get(p)).forEach((v) => all.add(v)));
    let vals = f.order ? f.order.filter((v) => all.has(v) || sel.has(v)) : [...all].sort((x, y) => String(x).localeCompare(String(y)));
    const showSearch = vals.length > 8; const q = popState.search.toLowerCase();
    if (q) vals = vals.filter((v) => String(v).toLowerCase().includes(q));
    pop.innerHTML = `<div class="ph"><b>${esc(t('fl.' + f.key, f.label))}</b><span class="muted">${t('db.anyOf', 'is any of')}</span>${sel.size ? `<a href="#" id="popClear">${t('db.clear', 'Clear')}</a>` : ''}</div>` +
      (showSearch ? `<input type="search" id="popQ" class="popq" placeholder="${t('db.find', 'Find…')}" value="${esc(popState.search)}">` : '') +
      `<div class="plist">${vals.map((v) => `<label class="opt"><input type="checkbox" data-v="${esc(v)}" ${sel.has(v) ? 'checked' : ''}><span class="ol">${esc(f.key === 'review' ? t('s.' + v, v) : v)}</span><span class="oc">${counts[v] || 0}</span></label>`).join('') || `<div class="muted" style="padding:6px 4px">${t('db.noMatch', 'No match')}</div>`}</div>`;
    pop.querySelectorAll('input[type=checkbox]').forEach((i) => i.addEventListener('change', () => { i.checked ? sel.add(i.dataset.v) : sel.delete(i.dataset.v); renderTable(); fillPop(); }));
    const pc = $('popClear'); if (pc) pc.addEventListener('click', (e) => { e.preventDefault(); sel.clear(); renderTable(); fillPop(); });
    const pq = $('popQ'); if (pq) { pq.addEventListener('input', () => { popState.search = pq.value; fillPop(); }); if (document.activeElement !== pq && popState.search !== null) { pq.focus(); pq.setSelectionRange(pq.value.length, pq.value.length); } }
  } else if (a === 'more') {
    const rest = FILTERS.filter((f) => !(f.primary || shownExtra.has(f.key) || state.quick[f.key].size));
    pop.innerHTML = `<div class="ph"><b>${t('db.addFilter2', 'Add filter')}</b></div><div class="plist">` + rest.map((f) => `<div class="opt single" data-add="${f.key}"><span class="ol">${esc(t('fl.' + f.key, f.label))}</span></div>`).join('') + '</div>';
    pop.querySelectorAll('[data-add]').forEach((d) => d.addEventListener('click', () => { shownExtra.add(d.dataset.add); closePop(); renderDbBar(); const b = $('dbFilters').querySelector(`[data-pop="f:${d.dataset.add}"]`); if (b) togglePop('f:' + d.dataset.add, b); }));
  } else if (a === 'group') {
    pop.innerHTML = `<div class="ph"><b>${t('db.groupby', 'Group by')}</b></div><div class="plist">` + GROUPS.map(([k, l]) => `<div class="opt single ${state.groupBy === k ? 'on' : ''}" data-g="${k}"><span class="ol">${esc(t('gb.' + (k || 'none'), l))}</span><span class="oc">${state.groupBy === k ? '✓' : ''}</span></div>`).join('') + '</div>';
    pop.querySelectorAll('[data-g]').forEach((d) => d.addEventListener('click', () => { state.groupBy = d.dataset.g; try { localStorage.setItem('pia_groupby', state.groupBy); } catch (e) { /* ignore */ } closePop(); renderTable(); }));
  } else if (a === 'fields') {
    pop.innerHTML = `<div class="ph"><b>${t('db.showFields', 'Show fields')}</b><a href="#" id="popReset">${t('db.reset', 'Reset')}</a></div><div class="plist">` +
      FIELDS.map((f) => `<label class="opt"><input type="checkbox" data-f="${f[0]}" ${state.visible[f[0]] ? 'checked' : ''} ${f[0] === 'project_id' ? 'disabled' : ''}><span class="ol">${t('col.' + f[0], f[1])}</span></label>`).join('') +
      `</div><div class="muted" style="font-size:11px;padding:6px 4px 0">${t('db.remember', 'Remembered in this browser.')}</div>`;
    pop.querySelectorAll('input[data-f]').forEach((i) => i.addEventListener('change', () => { state.visible[i.dataset.f] = i.checked; saveFields(); renderTable(); }));
    $('popReset').addEventListener('click', (e) => { e.preventDefault(); state.visible = defaultFields(); saveFields(); renderTable(); fillPop(); });
  }
}
function saveFields() { try { localStorage.setItem('pia_fields_v2', JSON.stringify(state.visible)); } catch (e) { /* ignore */ } }

// ---------------------------------------------------------------- drawer (database detail)
let drawerReq = 0;
async function openDrawer(pid) {
  const req = ++drawerReq;
  state.drawer.id = pid; state.drawer.ap = 0;
  let data;
  try { data = await api.get('/api/projects/' + pid); } catch (e) { alert('Could not load ' + pid + ': ' + e.message); return; }
  // ignore stale responses (the user navigated away or opened another project meanwhile)
  if (req !== drawerReq || !$('view-database').classList.contains('active')) return;
  state.drawer.data = data; state.taxonomy = data.taxonomy;
  document.body.classList.add('drawer-open');
  renderDrawer();
}
function closeDrawer() { drawerReq++; document.body.classList.remove('drawer-open'); }
function stepDrawer(d) { const list = filtered(); const i = list.findIndex((p) => p.project_id === state.drawer.id); if (i < 0 || !list.length) return; openDrawer(list[(i + d + list.length) % list.length].project_id); }

function basicInfo(p) {
  return `<details class="basic" open><summary>▾ Basic info <span class="muted" style="font-weight:400">from projects.csv</span></summary><dl class="kv">
    <dt>Project ID</dt><dd>${p.project_id}</dd><dt>Status</dt><dd>${esc(p.status)}</dd>
    <dt>Name</dt><dd>${esc(p.project_name)}</dd><dt>Approval date</dt><dd>${esc(p.approval_date)} <span class="muted">${p.approval_fy ? '(FY' + p.approval_fy + ')' : ''}</span></dd>
    <dt>Country</dt><dd>${esc(p.country)}</dd><dt>Region</dt><dd>${esc(p.region)}</dd>
    <dt>Vertical</dt><dd>${esc(p.vertical)}</dd><dt>Lead practice</dt><dd>${esc(p.lead_practice)}</dd>
    <dt>Commitment</dt><dd>USD ${fmtUsd(p.commitment_usd)}</dd><dt></dt><dd></dd>
    <dt class="full">Sectors</dt><dd class="full">${fullChips(p.sectors)}</dd>
    <dt class="full">Themes</dt><dd class="full">${themeTree(p.themes)}</dd>
    <dt class="full">Documents</dt><dd class="full">${p.documents.length ? p.documents.map((d) => `${d.doc_type} ${d.doc_date}${d.source === 'api' ? ' <span class="pill p-purple">API</span>' : ''}`).join(' · ') : '<span class="pill p-bad">none</span>'}</dd>
  </dl></details>`;
}
// Generated result of the latest run (+ reviewer override of "Innovative?") - kept apart from the projects.csv facts.
function resultSummary(p) {
  const ran = !(p.review_status === 'not run' || p.review_status === 'no documents');
  const live = ran ? p.approaches.filter((a) => !['rejected', 'mentioned_only', 'referenced_only'].includes(a.status)).length : null;
  const ment = ran ? p.approaches.filter((a) => a.status === 'mentioned_only').length : 0;
  const lr = p.last_record || {}; const run = (p.runs || [])[0];
  const cell = (label, val, sub) => `<div class="rcell"><div class="rlab">${label}</div><div class="rval">${val}</div>${sub ? `<div class="rsub">${sub}</div>` : ''}</div>`;
  return `<div class="resultbar"><div class="rhead">Assessment result <span class="muted">generated by the workflow · reviewer can override</span></div><div class="rgrid">
    ${cell('Innovative?', `${innovSelect(p)} <button class="btn sm ghost" data-hist="innovative">History</button>`)}
    ${cell('Approaches', live == null ? '<span class="muted">—</span>' : `<b>${live}</b>`, ment ? `+ ${ment} mentioned only` : '')}
    ${cell('Innovation tier', lr.innovation_tier ? esc(lr.innovation_tier) : '<span class="muted">—</span>', lr.innovation_keyword_hits != null && lr.innovation_tier ? `${lr.innovation_keyword_hits} distinct keyword hits` : '')}
    ${cell('Review status', pill(p.review_status))}
    ${cell('Latest run', run ? `<b>${esc(run.workflow_tag || run.workflow)}</b>` : '<span class="muted">not run</span>', run ? `${fmtTs(run.started_at).slice(0, 16)} UTC · ${fmtDur(isoDur(run.started_at, run.ended_at))}` : '')}
  </div></div>`;
}
function fullChips(arr) {
  const s = [...(arr || [])].sort((a, b) => (b.pct || 0) - (a.pct || 0));
  return s.length ? `<div class="fchips">${s.map((x) => `<span class="schip">${esc(x.name)}${x.pct != null ? ` <b>${Math.round(x.pct)}%</b>` : ''}</span>`).join('')}</div>` : '<span class="muted">—</span>';
}
// themes grouped under their level-1 parent: one line per parent, children as chips
function themeTree(arr) {
  const groups = {};
  [...(arr || [])].sort((a, b) => (b.pct || 0) - (a.pct || 0)).forEach((x) => {
    const parts = String(x.name).split(' > '); const parent = parts.length > 1 ? parts[0] : ''; const leaf = parts.length > 1 ? parts.slice(1).join(' › ') : x.name;
    (groups[parent] = groups[parent] || []).push({ ...x, leaf });
  });
  const keys = Object.keys(groups); if (!keys.length) return '<span class="muted">—</span>';
  return keys.map((k) => `<div class="tgroup">${k ? `<span class="tparent">${esc(k)} ›</span>` : ''}${groups[k].map((x) => `<span class="schip">${esc(x.leaf)}${x.pct != null ? ` <b>${Math.round(x.pct)}%</b>` : ''}</span>`).join('')}</div>`).join('');
}
// Stage of an approach: Mentioned (adoption = mentioned), Implemented (evidence from implementation reports), else Planned (design documents only)
const IMPL_DOCS = ['ISR', 'ICR', 'ICRR', 'PPAR', 'IEG'];
function approachStage(a) {
  if (['mentioned', 'prospect', 'discuss'].includes(a.adoption) || a.status === 'mentioned_only') return { key: 'mentioned', cls: 'p-warn', basis: a.mention_for ? t('m.' + a.mention_for, a.mention_for) : (a.adoption === 'prospect' ? t('f.prospect', 'prospect') : a.adoption === 'discuss' ? t('f.discuss', 'discuss') : t('st.mentionedB', 'mentioned, not adopted by the project')) };
  const evs = [a.evidence || {}, ...(a.extra_evidence || [])].filter((e) => e && e.doc_type);
  const impl = evs.filter((e) => IMPL_DOCS.includes(String(e.doc_type).toUpperCase()));
  if (impl.length) { const d = impl.map((e) => e.doc_date || '').sort().pop(); return { key: 'implemented', cls: 'p-ok', basis: `${t('st.implB', 'evidence in')} ${impl[0].doc_type}${d ? ' ' + d : ''}` }; }
  const docs = [...new Set(evs.map((e) => e.doc_type))].join(', ');
  return { key: 'planned', cls: 'p-info', basis: `${t('st.planB', 'design documents only')}${docs ? ' (' + docs + ')' : ''}` };
}
function innovSelect(p) {
  const v = p.innovative || '';
  return `<select data-edit-project="innovative" style="width:auto;display:inline-block;padding:2px 26px 2px 8px;background-position:right 8px center">${['', 'Yes', 'No', 'Unclear'].map((o) => `<option ${o === v ? 'selected' : ''}>${o || '—'}</option>`).join('')}</select>`;
}
function sel(opts, cur, attrs) { const list = [...new Set([cur, ...opts].filter((x) => x != null))]; return `<select ${attrs}>${list.map((o) => `<option ${o === cur ? 'selected' : ''}>${esc(o || '')}</option>`).join('')}</select>`; }
function fld(label, inner, histKey, aid, src) { return `<div class="field" style="margin-bottom:8px"><div class="fh"><b>${label}</b><button class="btn sm ghost" data-hist="${histKey}" data-aid="${aid || ''}">History</button></div>${inner}${src ? `<div class="src">${src}</div>` : ''}</div>`; }
function lastSrc(p, aid, field) {
  const h = p.history.filter((x) => (x.approach_id || '') === (aid || '') && x.field === field);
  const last = h[h.length - 1]; if (!last) return '';
  return last.source === 'manual' ? `<span class="m">manual</span> · ${fmtTs(last.at).slice(0, 16)}${last.reason ? ' · "' + esc(last.reason) + '"' : ''}` : `<span class="r">run ${last.workflow || ''}</span> · ${fmtTs(last.at).slice(0, 16)}${last.confidence != null ? ' · conf ' + Number(last.confidence).toFixed(2) : ''}`;
}
const V4_CATS = ['Operational', 'Technological', 'Financial', 'Collaborative'];   // workflow v4 categories
function approachPane(p, a, i, mode) {
  const tax = state.taxonomy || { pillars: [], solutions: [] };
  const pillars = tax.pillars.map((x) => x.name); const sols = tax.solutions.map((x) => x.title).concat(['none']);
  const sectors = p.sectors.map((x) => x.name); const themes = p.themes.map((x) => x.name);
  const ev = a.evidence || {}; const rep = a.replication || [];
  const edit = (f) => `data-edit="${f}" data-aid="${a.approach_id}"`;
  const mentionOpts = ['', 'future_plan', 'aspiration_or_vision', 'other_program', 'lesson_or_reference', 'option_considered', 'parent_or_prior', 'unclear'];
  const code = (a.approach_id || '').split('-').pop();
  const ctxBtn = (e, idx) => (e && e.guid && e.char_start >= 0) ? `<button class="btn sm" data-ctx="${idx}" data-aid="${a.approach_id}">🔍 ${t('f.review')}</button>` : '';
  const prow = (label, inner, histKey, src) => `<div class="prow"><div class="pl">${label}</div><div class="pv">${inner}${src ? `<div class="src">${src}</div>` : ''}</div><button class="btn sm ghost ph" data-hist="${histKey}" data-aid="${a.approach_id}" title="${t('f.history')}">${t('f.history')}</button></div>`;
  const st = approachStage(a);
  const stageInner = `<div class="pline"><span class="pill ${st.cls} stagepill">${t('st.' + st.key)}</span><span class="muted" style="font-size:12px">${esc(st.basis)}</span></div>
      <div class="pline" style="margin-top:6px"><span class="muted" style="font-size:11px">${t('f.adoption')}:</span>
        <select ${edit('adoption')} class="csel">${['', 'apply', 'prospect', 'discuss', 'applied', 'mentioned'].filter((o) => !['applied', 'mentioned'].includes(o) || o === (a.adoption || '')).map((o) => `<option value="${o}" ${o === (a.adoption || '') ? 'selected' : ''}>${o ? t('f.' + o, o) : '— auto —'}</option>`).join('')}</select>
        ${a.adoption === 'mentioned' || a.mention_for ? `<select ${edit('mention_for')} class="csel">${mentionOpts.map((o) => `<option value="${o}" ${o === (a.mention_for || '') ? 'selected' : ''}>${o ? t('m.' + o) : '— mention for —'}</option>`).join('')}</select>` : ''}</div>`;
  const repInner = (rep.length ? rep.map((l, k) => `<div class="pline" style="margin-bottom:3px"><a href="#" data-open="${l.other_project_id}">${l.other_project_id}</a> <span class="muted" style="font-size:12px">${l.kind.replace('_', ' ')} · ${Number(l.score).toFixed(2)} · ${l.direction}</span> <button class="btn sm" data-rep="${k}" data-aid="${a.approach_id}">🔍 ${t('rp.verify')}</button></div>${l.evidence && l.kind === 'similar_approach' ? `<div class="muted" style="font-size:12px;margin-bottom:4px">${esc(l.evidence)}</div>` : ''}`).join('') : '<span class="muted">no link found</span>') +
    (rep.length ? `<div class="pline" style="margin-top:4px"><span class="muted" style="font-size:11px">${t('rp.verdict')}:</span><select ${edit('replication_verdict')} class="csel">${['', 'confirmed', 'rejected', 'unsure'].map((o) => `<option value="${o}" ${o === (a.replication_verdict || '') ? 'selected' : ''}>${o || '—'}</option>`).join('')}</select>${a.replication_verdict ? `<span class="pill ${a.replication_verdict === 'confirmed' ? 'p-ok' : a.replication_verdict === 'rejected' ? 'p-bad' : 'p-warn'}">${a.replication_verdict}</span>` : ''}</div>` : '');
  return `<div class="appane active">
    <div class="aphead"><span class="muted" style="font-size:12px">Approach ${i + 1} · ${a.origin === 'manual' ? 'added manually' : 'generated'}${a.status === 'rejected' ? ' · <span class="pill p-bad">rejected by validation</span>' : ''}${a.status === 'referenced_only' ? ' · <span class="pill p-muted">referenced only (L1)</span>' : ''}</span>
      <span class="right"></span><button class="btn sm ghost" data-hist="name" data-aid="${a.approach_id}">${t('f.history')}</button></div>
    <textarea class="apname" rows="1" ${edit('name')} title="${t('f.name')}">${esc(a.name)}</textarea>
    <div class="src" style="margin:-2px 0 10px">${lastSrc(p, a.approach_id, 'name')}</div>
    <div class="props">
      ${prow(t('f.sector'), sel(sectors, a.sector, edit('sector') + ' class="csel"'), 'sector', lastSrc(p, a.approach_id, 'sector'))}
      ${prow(t('f.stage', 'Stage'), stageInner, 'adoption', [esc(a.adoption_reason || ''), lastSrc(p, a.approach_id, 'adoption')].filter(Boolean).join(' · '))}
    </div>
    <div class="props secondary">
      ${prow(t('f.category'), sel(V4_CATS.includes(a.category) || !pillars.length ? V4_CATS : pillars, a.category, edit('category') + ' class="csel"'), 'category', lastSrc(p, a.approach_id, 'category'))}
      ${prow(t('f.repeatedS', 'Repeated'), repInner, 'replication', lastSrc(p, a.approach_id, 'replication_verdict') || lastSrc(p, a.approach_id, 'replication'))}
    </div>
    ${fld(`${t('f.source')} <span class="vbadge ${ev.match_kind === 'manual' ? 'warn' : ''}">${ev.match_kind === 'manual' ? 'manual entry' : '✓ verbatim · ' + (ev.match_kind || 'exact')}</span>`, `<div class="quote" style="font-size:12px">${esc(ev.text)}</div><div style="margin-top:6px">${ctxBtn(ev, -1)}</div>`, 'evidence', a.approach_id,
      `${esc(ev.doc_type || '')} ${esc(ev.doc_date || '')} · ${esc(ev.file_name || '')}${ev.char_start >= 0 ? ` · chars ${ev.char_start}–${ev.char_end} · <a href="#" data-doc="${ev.guid}" data-s="${ev.char_start}" data-e="${ev.char_end}">quick view</a>` : ''}`)}
    <div class="field"><div class="fh"><b>${t('f.desc')}</b></div><div style="font-size:13px">${esc(a.description)}</div><div class="src">${esc(a.why_innovative)}</div></div>
    ${(a.extra_evidence || []).length ? `<details class="field" style="margin-top:8px"><summary style="cursor:pointer;font-weight:700;font-size:13px">${t('f.other')} (${a.extra_evidence.length})</summary>${a.extra_evidence.map((e, j) => `<div class="quote" style="font-size:12px;margin-top:6px">${esc(e.text)}<div class="src">${esc(e.doc_type)} ${esc(e.doc_date)} · chars ${e.char_start}–${e.char_end} · <a href="#" data-doc="${e.guid}" data-s="${e.char_start}" data-e="${e.char_end}">quick view</a> ${ctxBtn(e, j)}</div></div>`).join('')}</details>` : ''}
    ${mode === 'db' ? `<label>Reason for this edit (required when saving)</label><input type="text" id="editReason-${a.approach_id}" placeholder="e.g. corrected category after reading PAD section II.B">
    <div style="margin-top:8px;display:flex;gap:8px;align-items:center"><button class="btn primary" data-save="${a.approach_id}">Save edits</button><span class="muted right" style="font-size:12px">To regenerate, open in <a href="#" data-review="${p.project_id}">Review</a></span></div>` : ''}
  </div>`;
}
function approachesBlock(p, curAp, mode) {
  const aps = p.approaches;
  if (p.review_status === 'no documents') return '<div class="note">No documents available for this project. Fetch them from the World Bank API, then run it in Review.</div>';
  if (p.review_status === 'not run') return `<div class="note">This project has not been run yet. ${mode === 'db' ? `Open it in <a href="#" data-review="${p.project_id}">Review</a> to generate an assessment.` : 'Click Run.'}</div>`;
  let h = `<div class="toolbar" style="margin-bottom:8px"><b>Approaches</b> <span class="pill p-muted">${aps.length}</span><span class="right"></span><button class="btn sm" data-addap="${p.project_id}">+ Add approach manually</button></div>`;
  if (!aps.length) return h + `<div class="note">The workflow found no innovative approach. Record a manual approach if you disagree.</div>`;
  h += `<div class="apwrap"><nav class="apnav"><h4>Approach</h4>${aps.map((a, i) => `<div class="ai ${i === curAp ? 'cur' : ''}" data-ap="${i}">Approach ${i + 1}<small>${esc(a.name)}</small></div>`).join('')}</nav><div>${approachPane(p, aps[curAp] || aps[0], curAp, mode)}</div></div>`;
  return h;
}
function docsAndLog(p) {
  return `<div class="tabs" style="margin-top:16px"><button class="active" data-tab="0">Documents</button><button data-tab="1">Runs</button><button data-tab="2">Edit log</button></div>
  <div class="tabpane active"><table><tr><th>Type</th><th>Date</th><th>File</th><th>Source</th></tr>${p.documents.map((d) => `<tr><td>${d.doc_type}</td><td>${d.doc_date}</td><td class="mono">${esc(d.file_name)}</td><td>${d.source}</td></tr>`).join('') || '<tr><td colspan="4" class="muted">none</td></tr>'}</table></div>
  <div class="tabpane"><table><tr><th>Run</th><th>Workflow</th><th>When</th><th>Duration</th><th>Tier</th><th>Innovative</th><th>Approaches</th><th>Error</th></tr>${p.runs.map((r) => `<tr><td class="mono">${r.run_id}</td><td><b>${esc(r.workflow_tag || r.workflow)}</b> <span class="muted mono">${r.workflow_hash}${r.package_version ? ' · piaa ' + esc(r.package_version) : ''}</span></td><td>${fmtTs(r.started_at)}</td><td>${fmtDur(isoDur(r.started_at, r.ended_at))}</td><td>${r.innovation_tier} (${r.keyword_hits})</td><td>${r.innovative}</td><td>${r.n_approaches}</td><td class="muted">${esc(r.error)}</td></tr>`).join('') || '<tr><td colspan="8" class="muted">no runs</td></tr>'}</table></div>
  <div class="tabpane"><table><tr><th>When</th><th>Source</th><th>Approach</th><th>Field</th><th>From → To</th><th>Reason</th></tr>${[...p.history].reverse().filter((h) => h.source === 'manual' || h.field === 'innovative').slice(0, 60).map((h) => `<tr><td>${fmtTs(h.at).slice(0, 16)}</td><td>${h.source === 'manual' ? '<span class="pill p-purple">manual</span>' : `<span class="pill p-info">run ${h.workflow || ''}</span>`}</td><td>${h.approach_id ? h.approach_id.split('-').pop() : '—'}</td><td>${h.field}</td><td>${esc(h.old_value ?? '—')} → ${esc(h.new_value)}</td><td>${esc(h.reason || '')}</td></tr>`).join('') || '<tr><td colspan="6" class="muted">no entries</td></tr>'}</table></div>`;
}
function wireCommon(root, p, mode) {
  root.querySelectorAll('.tabs button').forEach((b) => b.addEventListener('click', () => { const t = b.parentElement; t.querySelectorAll('button').forEach((x) => x.classList.remove('active')); b.classList.add('active'); const panes = [...t.parentElement.querySelectorAll(':scope > .tabpane')]; panes.forEach((pp, j) => pp.classList.toggle('active', j === Number(b.dataset.tab))); }));
  root.querySelectorAll('[data-ap]').forEach((e) => e.addEventListener('click', () => { if (mode === 'db') { state.drawer.ap = Number(e.dataset.ap); renderDrawer(); } else { state.review.ap = Number(e.dataset.ap); renderReviewPage(); } }));
  root.querySelectorAll('[data-hist]').forEach((b) => b.addEventListener('click', () => openHist(p, b.dataset.hist, b.dataset.aid || null)));
  root.querySelectorAll('[data-doc]').forEach((a) => a.addEventListener('click', (ev) => { ev.preventDefault(); openDoc(p.project_id, a.dataset.doc, Number(a.dataset.s), Number(a.dataset.e)); }));
  root.querySelectorAll('[data-open]').forEach((a) => a.addEventListener('click', (ev) => { ev.preventDefault(); openDrawer(a.dataset.open); }));
  root.querySelectorAll('[data-review]').forEach((a) => a.addEventListener('click', (ev) => { ev.preventDefault(); closeDrawer(); startReviewWith([a.dataset.review]); }));
  root.querySelectorAll('[data-addap]').forEach((b) => b.addEventListener('click', () => addManualApproach(p.project_id, mode)));
  root.querySelectorAll('[data-ctx]').forEach((b) => b.addEventListener('click', () => openContext(p, b.dataset.aid, Number(b.dataset.ctx))));
  root.querySelectorAll('[data-rep]').forEach((b) => b.addEventListener('click', () => openReplication(p, b.dataset.aid, Number(b.dataset.rep))));
  root.querySelectorAll('[data-save]').forEach((b) => b.addEventListener('click', () => saveEdits(p, b.dataset.save, root, mode)));
  root.querySelectorAll('[data-edit-project]').forEach((s) => s.addEventListener('change', async () => { const v = s.value === '—' ? '' : s.value; const reason = prompt('Reason for changing the project-level verdict?', '') ?? ''; await api.post(`/api/projects/${p.project_id}/edits`, { field: 'innovative', value: v, reason }); refreshCurrent(p.project_id, mode); }));
}
async function saveEdits(p, aid, root, mode) {
  const a = p.approaches.find((x) => x.approach_id === aid); if (!a) return;
  const reasonEl = root.querySelector(`#editReason-${CSS.escape(aid)}`); const reason = reasonEl ? reasonEl.value.trim() : '';
  const changes = [];
  root.querySelectorAll(`[data-edit][data-aid="${aid}"]`).forEach((el) => { const f = el.dataset.edit; if ((el.value || '') !== (a[f] || '')) changes.push([f, el.value]); });
  if (!changes.length) { alert('Nothing changed.'); return; }
  if (mode === 'db' && !reason) { alert('Please give a reason for the edit.'); return; }
  for (const [f, v] of changes) await api.post(`/api/projects/${p.project_id}/edits`, { approach_id: aid, field: f, value: v, reason });
  refreshCurrent(p.project_id, mode);
}
async function addManualApproach(pid, mode) {
  const name = prompt('Approach name:'); if (!name) return;
  const evidence_text = prompt('Verbatim evidence sentence (copy from the document):', '') || '';
  const reason = prompt('Why are you adding it?', '') || '';
  await api.post(`/api/projects/${pid}/approaches`, { name, evidence_text, reason });
  refreshCurrent(pid, mode);
}
async function refreshCurrent(pid, mode) {
  const d = await api.get('/api/projects/' + pid); state.taxonomy = d.taxonomy;
  if (mode === 'db') { state.drawer.data = d; renderDrawer(); loadProjects(); } else { state.review.data = d; renderReviewPage(); }
}
function renderDrawer() {
  const p = state.drawer.data; if (!p) return;
  $('dTitle').textContent = `${p.project_id} · ${p.project_name}`;
  $('dStatus').innerHTML = pill(p.review_status) + (p.runs.length ? ` <span class="muted" style="font-size:12px">· ${p.runs.length} run${p.runs.length > 1 ? 's' : ''} · latest ${p.runs[0].workflow_tag || p.runs[0].workflow} ${fmtTs(p.runs[0].started_at).slice(0, 16)}</span>` : '');
  const body = $('dBody');
  body.innerHTML = basicInfo(p) + resultSummary(p) + approachesBlock(p, state.drawer.ap, 'db') + docsAndLog(p);
  wireCommon(body, p, 'db');
}

// ---------------------------------------------------------------- history modal
function openHist(p, field, aid) {
  const rows = p.history.filter((h) => h.field === field && (h.approach_id || '') === (aid || ''));
  $('histTitle').textContent = `History · ${field}` + (aid ? ` · ${aid.split('-').pop()}` : '');
  $('histSub').textContent = `${p.project_id} · every value this field has had, from runs and manual edits`;
  const tl = [...rows].reverse().map((h, i) => `<div class="ev ${h.source === 'manual' ? 'm' : ''} ${i === 0 ? 'cur' : ''}"><div class="when">${fmtTs(h.at)} · ${h.source === 'manual' ? '<span class="pill p-purple">manual</span> · ' + esc(h.who || '') : `<span class="pill p-info">run ${h.workflow || ''}</span> · ${h.run_id || ''}`}${h.confidence != null ? ' · conf ' + Number(h.confidence).toFixed(2) : ''}</div><div class="v">${esc(h.new_value)}</div>${h.reason ? `<div class="muted" style="font-size:12px">reason: "${esc(h.reason)}"</div>` : ''}</div>`).join('') || '<div class="muted">no history yet</div>';
  const counts = {}; rows.forEach((h) => { counts[h.new_value] = (counts[h.new_value] || 0) + 1; });
  const total = rows.length; const bars = Object.entries(counts).sort((a, b) => b[1] - a[1]).map(([v, n]) => `<div class="bar"><span style="width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(v)}">${esc(v)}</span><i style="width:${Math.round(160 * n / total)}px"></i>${n} of ${total}</div>`).join('');
  const runs = rows.filter((h) => h.source === 'run'); const lastWf = runs.length ? runs[runs.length - 1].workflow : null;
  const agree = lastWf ? runs.filter((h) => h.workflow === lastWf) : []; const agreeN = agree.filter((h) => h.new_value === (rows[rows.length - 1] || {}).new_value).length;
  $('histBody').innerHTML = `<div class="grid2"><div><div class="tl">${tl}</div></div><div><div class="helper"><b>Decision helper</b><div style="margin-top:6px">${bars || '<span class="muted">—</span>'}</div>
    <p style="margin:8px 0 0">${lastWf ? `Latest workflow (${lastWf}) agrees with the current value in ${agreeN} / ${agree.length} run${agree.length === 1 ? '' : 's'}.` : 'No run yet.'}${Object.keys(counts).length > 1 ? ' Values differ across history — check the source paragraph before deciding.' : ' All recorded values agree.'}</p></div></div></div>`;
  $('modal').classList.add('open');
}
function closeHist() { $('modal').classList.remove('open'); document.querySelector('#modal .modal').classList.remove('wide'); }


// ---------------------------------------------------------------- review in context (on-demand, formatted pages around a sentence)
const cstate = { p: null, a: null, items: [], cur: 0, pages: 2, cache: {} };
function openContext(p, aid, idx) {
  const a = p.approaches.find((x) => x.approach_id === aid); if (!a) return;
  const items = [{ ...a.evidence, label: 'Evidence 1 (strongest)' }].concat((a.extra_evidence || []).map((e, j) => ({ ...e, label: `Evidence ${j + 2}` }))).filter((e) => e.guid && e.char_start >= 0);
  Object.assign(cstate, { p, a, items, cur: Math.max(0, idx + 1), cache: {} });
  $('histTitle').textContent = `${t('cx.title')} · ${a.name}`;
  $('histSub').textContent = `${p.project_id} · ${p.project_name}`;
  document.querySelector('#modal .modal').classList.add('wide');
  $('modal').classList.add('open');
  renderContext();
}
function renderContext() {
  const items = cstate.items; const cur = items[cstate.cur];
  const tabs = items.map((e, j) => `<div class="ct ${j === cstate.cur ? 'cur' : ''}" data-j="${j}"><b>${esc(e.label)}</b><small>${esc(e.doc_type)} ${esc(e.doc_date)}</small><small>${esc(e.text.slice(0, 60))}…</small></div>`).join('');
  const pagesSel = `<label style="margin:0;font-size:12px;display:inline">${t('cx.pages')}</label> <select id="cxPages" style="width:auto;display:inline-block;padding:3px 26px 3px 8px;background-position:right 8px center">${[1, 2, 3, 4, 6].map((n) => `<option ${n === cstate.pages ? 'selected' : ''}>${n}</option>`).join('')}</select>`;
  $('histBody').innerHTML = `<div class="ctxwrap"><div class="ctxtabs">${tabs}</div><div>
      <div class="ctxmeta">${pagesSel}<span>${esc(cur.file_name || '')}</span><span>chars ${cur.char_start}–${cur.char_end}</span><span class="right muted">${t('cx.legend')}</span></div>
      <div id="cxBody"><div class="muted" style="padding:20px"><span class="spin"></span>${t('cx.generating')}<div class="pbar"><i></i></div></div></div></div></div>`;
  $('histBody').querySelectorAll('.ct').forEach((d) => d.addEventListener('click', () => { cstate.cur = Number(d.dataset.j); renderContext(); }));
  $('cxPages').addEventListener('change', () => { cstate.pages = Number($('cxPages').value); renderContext(); });
  loadContext(cur);
}
async function loadContext(e) {
  const key = `${e.guid}:${e.char_start}:${cstate.pages}`;
  const code = (cstate.a.approach_id || '').split('-').pop();
  let d = cstate.cache[key];
  if (!d) {
    try { d = await api.get(`/api/projects/${cstate.p.project_id}/context?guid=${e.guid}&start=${e.char_start}&end=${e.char_end}&pages=${cstate.pages}&code=${/^\d{6}$/.test(code) ? code : ''}`); }
    catch (err) { $('cxBody').innerHTML = `<div class="note">Could not build the context: ${esc(err.message)}</div>`; return; }
    cstate.cache[key] = d;
  }
  if (cstate.items[cstate.cur].guid !== e.guid || cstate.items[cstate.cur].char_start !== e.char_start) return;  // user switched tab meanwhile
  let html = ''; let page = 0;
  for (const b of d.blocks) {
    if (b.page !== page) { page = b.page; html += `<div class="pg">page ${page} of ${d.pages} · ${t('cx.position')} ${d.position_pct}%</div>`; }
    const inner = markup(b.text, b.marks);
    const hit = b.marks.some((m) => m.kind === 'evidence');
    const sig = (b.signals.aspiration || b.signals.commitment) ? `<div class="sig">${b.signals.aspiration ? `<span class="asp">▌${(b.signals.aspiration_terms || []).join(', ')}</span>` : ''}${b.signals.commitment ? `<span class="com">▌${(b.signals.commitment_terms || []).join(', ')}</span>` : ''}</div>` : '';
    if (b.kind === 'heading') html += `<h4>${inner}</h4>`;
    else html += `<p class="${b.kind === 'subpoint' ? 'sub' : b.kind === 'bullet' ? 'bul' : ''} ${hit ? 'hit' : ''}">${inner}</p>${sig}`;
  }
  $('cxBody').innerHTML = `<div class="ctxdoc">${html}</div><div class="muted" style="font-size:11px;margin-top:6px">${t('cx.coded')}: ${d.coded_in_window} · window chars ${d.window_start}–${d.window_end} of ${d.doc_length} · rebuilt from ${esc(d.file_name)}</div>`;
  const m = $('cxBody').querySelector('mark.ev'); if (m) m.scrollIntoView({ block: 'center' });
}
function markup(text, marks) {
  // flatten overlapping marks into a sorted list of boundaries (evidence > coded > keyword)
  const pri = { evidence: 3, coded: 2, keyword: 1 };
  const pts = new Set([0, text.length]); marks.forEach((m) => { pts.add(m.start); pts.add(m.end); });
  const bounds = [...pts].sort((a, b) => a - b); let out = '';
  for (let i = 0; i < bounds.length - 1; i++) {
    const a = bounds[i], b = bounds[i + 1]; if (b <= a) continue;
    const active = marks.filter((m) => m.start <= a && m.end >= b).sort((x, y) => pri[y.kind] - pri[x.kind]);
    let seg = esc(text.slice(a, b));
    if (active.some((m) => m.kind === 'keyword')) seg = `<b class="kw">${seg}</b>`;
    const top = active[0];
    if (top && top.kind === 'evidence') seg = `<mark class="ev">${seg}</mark>`;
    else if (top && top.kind === 'coded') seg = `<mark class="coded" title="${esc(top.code || '')} ${esc(top.level || '')}">${seg}</mark>`;
    out += seg;
  }
  return out;
}


// ---------------------------------------------------------------- verify a replication link: both projects' evidence side by side
async function openReplication(p, aid, k) {
  const a = p.approaches.find((x) => x.approach_id === aid); if (!a) return;
  const l = (a.replication || [])[k]; if (!l) return;
  $('histTitle').textContent = `${t('rp.title')} · ${a.name}`;
  $('histSub').textContent = `${p.project_id} ${l.direction} ${l.other_project_id} · ${l.kind.replace('_', ' ')} · score ${Number(l.score).toFixed(2)}`;
  document.querySelector('#modal .modal').classList.add('wide');
  $('modal').classList.add('open');
  $('histBody').innerHTML = `<div class="muted"><span class="spin"></span>${t('cx.generating')}<div class="pbar"><i></i></div></div>`;
  let other; try { other = await api.get('/api/projects/' + l.other_project_id); } catch (e) { $('histBody').innerHTML = `<div class="note">${esc(e.message)}</div>`; return; }
  const oa = l.other_approach_id ? other.approaches.find((x) => x.approach_id === l.other_approach_id) : null;
  const code = (a.approach_id || '').split('-').pop();
  const col = async (proj, ev, cd) => {
    if (!ev || !ev.guid || ev.char_start < 0) return '<div class="muted">no anchored evidence</div>';
    const d = await api.get(`/api/projects/${proj.project_id}/context?guid=${ev.guid}&start=${ev.char_start}&end=${ev.char_end}&pages=1&code=${/^\d{6}$/.test(cd) ? cd : ''}`);
    let html = ''; for (const b of d.blocks) { const inner = markup(b.text, b.marks); const hit = b.marks.some((m) => m.kind === 'evidence'); html += b.kind === 'heading' ? `<h4>${inner}</h4>` : `<p class="${hit ? 'hit' : ''}">${inner}</p>`; }
    return `<div class="muted" style="font-size:11px;margin-bottom:4px">${esc(d.file_name)} · chars ${ev.char_start}–${ev.char_end} · ${t('cx.position')} ${d.position_pct}%</div><div class="ctxdoc" style="max-height:52vh;padding:16px 20px;font-size:13.5px">${html}</div>`;
  };
  let right;
  if (oa) right = await col(other, oa.evidence, (oa.approach_id || '').split('-').pop());
  else right = `<div class="note">${t('rp.other')}: ${esc(other.project_name)} — explicit reference found in this project's documents:</div><div class="ctxdoc" style="max-height:52vh;padding:16px 20px;font-size:13.5px"><p class="hit">${esc(l.evidence || '').replace(new RegExp(l.other_project_id, 'g'), `<mark class="ev">${l.other_project_id}</mark>`)}</p></div>`;
  const left = await col(p, a.evidence, code);
  $('histBody').innerHTML = `<div class="grid2">
    <div><h3 style="margin:0 0 6px">${t('rp.this')} · ${p.project_id} ${esc(p.project_name)}</h3><div class="muted" style="font-size:12px;margin-bottom:6px">${esc(a.name)} · ${esc(p.approval_date)}</div>${left}</div>
    <div><h3 style="margin:0 0 6px">${t('rp.other')} · ${other.project_id} ${esc(other.project_name)}</h3><div class="muted" style="font-size:12px;margin-bottom:6px">${oa ? esc(oa.name) : '—'} · ${esc(other.approval_date)} · ${pill(other.review_status)}</div>${right}</div></div>
    <div style="margin-top:12px;display:flex;gap:8px;align-items:center"><button class="btn ok" id="rpConfirm">✔ ${t('rp.confirm')}</button><button class="btn" id="rpReject">✕ ${t('rp.reject')}</button><button class="btn" id="rpOpen">${t('rp.open')} →</button><input type="text" id="rpNote" placeholder="note" style="flex:1"></div>`;
  const verdict = async (v) => { await api.post(`/api/projects/${p.project_id}/edits`, { approach_id: aid, field: 'replication_verdict', value: v, reason: ($('rpNote').value || '') + ` [${l.other_project_id} ${l.kind} ${Number(l.score).toFixed(2)}]` }); closeHist(); refreshCurrent(p.project_id, document.body.classList.contains('drawer-open') ? 'db' : 'review'); };
  $('histBody').querySelectorAll('mark.ev').forEach((m) => m.scrollIntoView({ block: 'center' }));
  $('rpConfirm').addEventListener('click', () => verdict('confirmed'));
  $('rpReject').addEventListener('click', () => verdict('rejected'));
  $('rpOpen').addEventListener('click', () => { closeHist(); go('database'); openDrawer(other.project_id); });
}

// ---------------------------------------------------------------- document viewer
async function openDoc(pid, guid, s, e) {
  const d = await api.get(`/api/projects/${pid}/document/${guid}?start=${s}&end=${e}&context=1500`);
  const t = d.text; const [a, b] = d.highlight;
  $('histTitle').textContent = `Document · ${d.file_name}`;
  $('histSub').textContent = `chars ${s}–${e} of ${d.length} · highlighted text is the stored evidence, re-read from the file`;
  $('histBody').innerHTML = `<div class="quote" style="font-size:13px;max-height:60vh;overflow:auto">${esc(t.slice(0, a))}<mark>${esc(t.slice(a, b))}</mark>${esc(t.slice(b))}</div>`;
  $('modal').classList.add('open');
}

// ---------------------------------------------------------------- analytics (interactive explorer, WBG Scorecard look)
const SC = { navy: '#1c2b3a', blue: '#2c5c8f', teal: '#1f8a8a', green: '#3b8b4f', red: '#9b2d30', gold: '#e0a630', slate: '#7a8c9e', grey: '#c9d2db', muted: '#6b7280', grid: '#e3e7ec' };
const SC_SERIES = [SC.blue, SC.teal, SC.green, SC.red, SC.gold, SC.slate, '#8fb3d9', SC.grey];
const AN = { data: null, d1: 'sector', d2: 'sector', d3: 'sector', d4: 'sector', cx: 'sector', cy: 'category', timeMode: 'count', moneyMode: 'share' };

function scTile(o) {
  const frac = Math.max(0, Math.min(1, o.frac == null ? 1 : o.frac));
  return `<div class="sc-tile"><div class="sc-tile-top"><div class="sc-icon" style="color:${o.color};border-color:${o.color}">${o.glyph}</div><div class="sc-tt"><b>${esc(o.bold)}</b> ${esc(o.rest)}</div></div>
    <div class="sc-num"><span class="sc-bars"><i style="background:#d9dee5;height:100%"></i><i style="background:${o.color};height:${Math.round(frac * 100)}%"></i></span>
      <span><span class="sc-big">${esc(o.big)}</span> <span class="sc-lbl">${esc(o.label)}</span><div class="sc-note">${esc(o.note)}</div></span></div></div>`;
}
function scHBar(labels, values, { color = SC.blue, fmt = (v) => v, max = null, sub = null } = {}) {
  if (!labels.length) return '<div class="sc-empty">No data</div>';
  const W = 640, rowH = 28, left = 236, right = 60, H = labels.length * rowH + 8;
  const mx = max || Math.max(1, ...values) * 1.05; const x = (v) => left + (W - left - right) * v / mx; let g = '';
  labels.forEach((l, i) => { const y = 4 + i * rowH; g += `<text x="${left - 8}" y="${y + rowH / 2}" dy="0.35em" text-anchor="end">${esc(l.length > 34 ? l.slice(0, 33) + '…' : l)}</text>
    <rect x="${left}" y="${y + 6}" width="${Math.max(0, x(values[i]) - left)}" height="${rowH - 12}" rx="3" fill="${color}"><title>${esc(l)}: ${fmt(values[i])}${sub ? ' · ' + sub[i] : ''}</title></rect>
    <text x="${x(values[i]) + 6}" y="${y + rowH / 2}" dy="0.35em" class="sc-val">${fmt(values[i])}</text>`; });
  return `<svg viewBox="0 0 ${W} ${H}" class="sc-chart">${g}</svg>`;
}
function scStack(labels, series, { horizontal = false, percent = false } = {}) {
  const n = labels.length; if (!n || !series.length) return '<div class="sc-empty">No data</div>';
  const raw = labels.map((_, i) => series.reduce((s, q) => s + (q.values[i] || 0), 0));
  const val = (q, i) => percent ? (raw[i] ? 100 * (q.values[i] || 0) / raw[i] : 0) : (q.values[i] || 0);
  const totals = labels.map((_, i) => percent ? (raw[i] ? 100 : 0) : raw[i]); const mx = percent ? 100 : Math.max(1, ...totals) * 1.08;
  const lab = (q, i) => percent ? (val(q, i) ? Math.round(val(q, i)) + '%' : '') : (q.values[i] || '');
  const legend = `<div class="sc-legend">${series.map((q, k) => `<span><i style="background:${SC_SERIES[k % SC_SERIES.length]}"></i>${esc(q.name)}</span>`).join('')}</div>`;
  if (horizontal) {
    const W = 760, rowH = 28, left = 236, right = 50, H = n * rowH + 8; const x = (v) => left + (W - left - right) * v / mx; let g = '';
    labels.forEach((l, i) => { const y = 4 + i * rowH; let acc = 0; g += `<text x="${left - 8}" y="${y + rowH / 2}" dy="0.35em" text-anchor="end">${esc(l)}</text>`;
      series.forEach((q, k) => { const v = val(q, i); if (!v) return; const x0 = x(acc), x1 = x(acc + v); acc += v;
        g += `<rect x="${x0 + 1}" y="${y + 6}" width="${Math.max(0, x1 - x0 - 2)}" height="${rowH - 12}" rx="2" fill="${SC_SERIES[k % SC_SERIES.length]}"><title>${esc(l)} · ${esc(q.name)}: ${q.values[i] || 0}${percent ? ' (' + Math.round(v) + '%)' : ''}</title></rect>`;
        if (x1 - x0 > 22) g += `<text x="${(x0 + x1) / 2}" y="${y + rowH / 2}" dy="0.35em" text-anchor="middle" class="sc-in">${lab(q, i)}</text>`; });
      g += `<text x="${x(acc) + 6}" y="${y + rowH / 2}" dy="0.35em" class="sc-val">${raw[i]}</text>`; });
    return legend + `<svg viewBox="0 0 ${W} ${H}" class="sc-chart">${g}</svg>`;
  }
  const W = 760, H = 290, top = 18, bottom = 26, left = 40, right = 10; const bw = (W - left - right) / n; const y = (v) => top + (H - top - bottom) * (1 - v / mx); let g = '';
  for (let t = 0; t <= 4; t++) { const v = mx * t / 4, yy = y(v); g += `<line x1="${left}" x2="${W - right}" y1="${yy}" y2="${yy}" stroke="${SC.grid}"/><text x="${left - 6}" y="${yy}" dy="0.35em" text-anchor="end" class="sc-tick">${Math.round(v)}${percent ? '%' : ''}</text>`; }
  labels.forEach((l, i) => { const x0 = left + i * bw + bw * 0.2, w = bw * 0.6; let acc = 0;
    series.forEach((q, k) => { const v = val(q, i); if (!v) return; const y1 = y(acc + v), y0 = y(acc); acc += v;
      g += `<rect x="${x0}" y="${y1 + 1}" width="${w}" height="${Math.max(0, y0 - y1 - 2)}" rx="2" fill="${SC_SERIES[k % SC_SERIES.length]}"><title>${esc(l)} · ${esc(q.name)}: ${q.values[i] || 0}${percent ? ' (' + Math.round(v) + '%)' : ''}</title></rect>`;
      if (y0 - y1 > 14) g += `<text x="${x0 + w / 2}" y="${(y0 + y1) / 2}" dy="0.35em" text-anchor="middle" class="sc-in">${lab(q, i)}</text>`; });
    g += `<text x="${x0 + w / 2}" y="${y(acc) - 5}" text-anchor="middle" class="sc-val">${raw[i] || ''}</text><text x="${x0 + w / 2}" y="${H - 8}" text-anchor="middle">${esc(l)}</text>`; });
  return legend + `<svg viewBox="0 0 ${W} ${H}" class="sc-chart">${g}</svg>`;
}
function scLine(labels, values, { color = SC.red, fmt = (v) => v + '%', counts = null } = {}) {
  const W = 760, H = 230, top = 22, bottom = 26, left = 42, right = 16; const mx = Math.max(10, ...values) * 1.25; const n = labels.length;
  const x = (i) => left + (W - left - right) * (n === 1 ? 0.5 : i / (n - 1)); const y = (v) => top + (H - top - bottom) * (1 - v / mx); let g = '';
  for (let t = 0; t <= 4; t++) { const v = mx * t / 4, yy = y(v); g += `<line x1="${left}" x2="${W - right}" y1="${yy}" y2="${yy}" stroke="${SC.grid}"/><text x="${left - 6}" y="${yy}" dy="0.35em" text-anchor="end" class="sc-tick">${Math.round(v)}%</text>`; }
  g += `<polyline fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" points="${values.map((v, i) => `${x(i)},${y(v)}`).join(' ')}"/>`;
  values.forEach((v, i) => { g += `<circle cx="${x(i)}" cy="${y(v)}" r="4.5" fill="${color}" stroke="#fff" stroke-width="2"><title>${esc(labels[i])}: ${fmt(v)}${counts ? ' · ' + counts[i] + ' approaches' : ''}</title></circle><text x="${x(i)}" y="${y(v) - 10}" text-anchor="middle" class="sc-val">${fmt(v)}</text><text x="${x(i)}" y="${H - 8}" text-anchor="middle">${esc(labels[i])}</text>`; });
  return `<svg viewBox="0 0 ${W} ${H}" class="sc-chart">${g}</svg>`;
}

// ---- aggregation over the slim records
function anGroups(dim, { top = 8 } = {}) {
  const cnt = {}; AN.data.records.forEach((r) => { const k = r[dim] || 'Unspecified'; if (k !== 'Unspecified') cnt[k] = (cnt[k] || 0) + 1; });
  const keys = Object.keys(cnt).sort((a, b) => cnt[b] - cnt[a]);
  return { keys, cnt, shown: keys.slice(0, top), rest: keys.slice(top) };
}
function anCount(dim) { const g = anGroups(dim, { top: 99 }); return { labels: g.keys, values: g.keys.map((k) => g.cnt[k]) }; }
function anByFy(dim) {
  const d = AN.data; const years = []; for (let y = d.fy_min; y <= d.fy_max; y++) years.push(y);
  const g = anGroups(dim, { top: 6 }); const tab = {};
  d.records.forEach((r) => { if (!r.fy || r.fy < d.fy_min || r.fy > d.fy_max) return; const k = g.shown.includes(r[dim]) ? r[dim] : (r[dim] === 'Unspecified' ? null : 'Other'); if (!k) return; (tab[k] = tab[k] || {})[r.fy] = (tab[k][r.fy] || 0) + 1; });
  const series = g.shown.map((k) => ({ name: k, values: years.map((y) => (tab[k] || {})[y] || 0) }));
  if (g.rest.length) series.push({ name: `Other (${g.rest.length})`, values: years.map((y) => (tab.Other || {})[y] || 0) });
  return { labels: d.fy_labels, series };
}
function anAi(dim) {
  const all = {}, ai = {}, wAll = {}, wAi = {};
  AN.data.records.forEach((r) => {
    if (dim === 'sector') { r.sector_weights.forEach(([m, sh]) => { all[m] = (all[m] || 0) + sh; wAll[m] = (wAll[m] || 0) + sh * r.commitment; if (r.ai) { ai[m] = (ai[m] || 0) + sh; wAi[m] = (wAi[m] || 0) + sh * r.commitment; } }); }
    else { const k = r[dim] || 'Unspecified'; all[k] = (all[k] || 0) + 1; wAll[k] = (wAll[k] || 0) + r.commitment; if (r.ai) { ai[k] = (ai[k] || 0) + 1; wAi[k] = (wAi[k] || 0) + r.commitment; } }
  });
  const keys = Object.keys(all).filter((k) => k !== 'Unspecified' && k !== 'Other / unmapped').sort((a, b) => (ai[b] || 0) / all[b] - (ai[a] || 0) / all[a]);
  const totAi = Object.values(wAi).reduce((s, v) => s + v, 0);
  return { labels: keys, count: keys.map((k) => +(100 * (ai[k] || 0) / all[k]).toFixed(1)), usd: keys.map((k) => wAll[k] ? +(100 * (wAi[k] || 0) / wAll[k]).toFixed(1) : 0),
           shareOfAi: keys.map((k) => totAi ? +(100 * (wAi[k] || 0) / totAi).toFixed(1) : 0), n: keys.map((k) => Math.round(all[k] * 10) / 10) };
}
function anMoney(dim) {
  // attributed commitment: project commitment / number of its retained approaches (x sector share for the sector dimension)
  const nproj = {}; AN.data.records.forEach((r) => { nproj[r.project_id] = (nproj[r.project_id] || 0) + 1; });
  const usd = {};
  AN.data.records.forEach((r) => { const base = r.commitment / nproj[r.project_id];
    if (dim === 'sector') r.sector_weights.forEach(([m, sh]) => { usd[m] = (usd[m] || 0) + base * sh; });
    else { const k = r[dim] || 'Unspecified'; usd[k] = (usd[k] || 0) + base; } });
  const keys = Object.keys(usd).filter((k) => k !== 'Unspecified' && k !== 'Other / unmapped').sort((a, b) => usd[b] - usd[a]);
  const tot = keys.reduce((t, k) => t + usd[k], 0);
  return { labels: keys, bn: keys.map((k) => +(usd[k] / 1e9).toFixed(2)), share: keys.map((k) => tot ? +(100 * usd[k] / tot).toFixed(1) : 0), total_bn: +(tot / 1e9).toFixed(2) };
}
function anAiFy() {
  const d = AN.data; const years = []; for (let y = d.fy_min; y <= d.fy_max; y++) years.push(y); const all = {}, ai = {};
  d.records.forEach((r) => { if (!r.fy) return; all[r.fy] = (all[r.fy] || 0) + 1; if (r.ai) ai[r.fy] = (ai[r.fy] || 0) + 1; });
  return { labels: d.fy_labels, values: years.map((y) => all[y] ? +(100 * (ai[y] || 0) / all[y]).toFixed(1) : 0), counts: years.map((y) => all[y] || 0) };
}
function anCross(rowDim, colDim) {
  const rows = anGroups(rowDim, { top: 99 }), cols = anGroups(colDim, { top: 6 }); const tab = {};
  AN.data.records.forEach((r) => { const a = r[rowDim], b = cols.shown.includes(r[colDim]) ? r[colDim] : (r[colDim] === 'Unspecified' ? null : 'Other'); if (!a || a === 'Unspecified' || !b) return; (tab[a] = tab[a] || {})[b] = (tab[a][b] || 0) + 1; });
  const series = cols.shown.map((k) => ({ name: k, values: rows.keys.map((a) => (tab[a] || {})[k] || 0) }));
  if (cols.rest.length) series.push({ name: `Other (${cols.rest.length})`, values: rows.keys.map((a) => (tab[a] || {}).Other || 0) });
  return { labels: rows.keys, series };
}

// ---- page
const DIM_COLOR = { sector: SC.blue, theme: SC.teal, category: SC.green, region: SC.gold, vertical: SC.slate, practice: SC.navy };
function anDimSelect(key, cur, { exclude = null, label = '' } = {}) {
  return `<label class="sc-sel">${label ? esc(label) + ' ' : ''}<select data-an="${key}">${Object.entries(AN.data.dims).filter(([k]) => k !== exclude).map(([k, v]) => `<option value="${k}" ${k === cur ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
}
function anSeg(id, cur, opts) { return `<div class="sc-seg" data-an-seg="${id}">${opts.map(([k, v]) => `<button class="${k === cur ? 'on' : ''}" data-v="${k}">${esc(v)}</button>`).join('')}</div>`; }
const dimNote = (dim) => dim === 'sector' ? 'Matched sector of each approach, rolled up to 11 major sectors.' : dim === 'theme' ? 'Matched theme, harmonised into 10 theme groups.' : dim === 'category' ? 'Category as stored by the current workflow.' : 'Project attribute from projects.csv.';
function renderAnalytics() {
  const d = AN.data, k = d.kpis, D = d.dims, low = (x) => D[x].toLowerCase();
  const mix = Object.entries(k.workflow_mix || {}).map(([w, n]) => `${w} ×${n}`).join(' · ');
  const cnt = anCount(AN.d1), money = anMoney(AN.d2), fy = anByFy(AN.d3), ai = anAi(AN.d4), aiFy = anAiFy(), cross = anCross(AN.cx, AN.cy);
  const secLead = anCount('sector');
  const head = (bold, rest, key, cur, extra = '') => `<div class="sc-ct-row"><div class="sc-ct"><b>${esc(bold)}</b> ${rest}</div><div class="sc-ct-tools">${extra}${anDimSelect(key, cur)}</div></div>`;
  $('anBody').innerHTML = `
  <div class="sc-band"><div><b>WORLD BANK GROUP</b><span class="sc-sep">|</span>PIA Analysis <span class="sc-band-sub">Digital &amp; AI approaches</span></div><div class="sc-band-r">current database state · ${esc(mix || '—')}</div></div>
  <div class="sc-page">
    <div class="sc-hero"><h2>What's in the portfolio</h2><p>Achieved so far, against the universe it was measured on. Every chart below has its own dimension switch.</p></div>
    <div class="sc-tiles">
      ${scTile({ color: SC.blue, glyph: '⌂', bold: 'Projects', rest: 'with at least one Digital & AI approach', big: String(k.projects_with_approach), label: 'Projects', note: `${k.projects_analysed} analysed of ${k.projects_listed} listed`, frac: k.projects_with_approach / Math.max(1, k.projects_analysed) })}
      ${scTile({ color: SC.teal, glyph: '≡', bold: 'Approaches', rest: 'retained with verbatim evidence', big: String(k.approaches), label: 'Approaches', note: `${k.per_project} per analysed project`, frac: 1 })}
      ${scTile({ color: SC.red, glyph: '◎', bold: 'AI', rest: 'approaches', big: String(k.ai_approaches), label: 'AI approaches', note: `${k.ai_share}% of all approaches`, frac: k.ai_share / 100 })}
      ${scTile({ color: SC.blue, glyph: '▦', bold: 'Sectors', rest: 'reached by at least one approach', big: String(k.sectors_reached), label: `of ${k.sectors_total} sectors`, note: secLead.labels[0] ? `${secLead.labels[0]} leads with ${secLead.values[0]}` : '—', frac: k.sectors_reached / k.sectors_total })}
      ${scTile({ color: SC.green, glyph: '$', bold: 'Commitment', rest: 'behind the analysed projects', big: `$${k.commitment_bn}B`, label: 'Covered', note: `${k.projects_missing_commitment} projects without an amount`, frac: 1 - k.projects_missing_commitment / Math.max(1, k.projects_analysed) })}
      ${scTile({ color: SC.gold, glyph: '↗', bold: 'AI share', rest: 'of approaches, FY22 and later approvals', big: `${k.ai_share_late}%`, label: `vs ${k.ai_share_early}% in FY19–21`, note: 'by approval cohort', frac: k.ai_share_late / 100 })}
    </div>

    <div class="sc-explore">
      <div class="sc-row2">
        <div class="sc-card">${head('Approaches', 'by ' + esc(low(AN.d1)), 'd1', AN.d1)}${scHBar(cnt.labels, cnt.values, { color: DIM_COLOR[AN.d1] })}<div class="sc-foot">${cnt.labels[0] ? esc(cnt.labels[0]) + ' leads with ' + cnt.values[0] + '. ' : ''}${dimNote(AN.d1)}</div></div>
        <div class="sc-card">${head('Commitment', (AN.moneyMode === 'share' ? 'share' : 'US$ bn') + ' by ' + esc(low(AN.d2)), 'd2', AN.d2, anSeg('moneyMode', AN.moneyMode, [['share', 'Share'], ['bn', 'US$ bn']]))}
          ${scHBar(money.labels, AN.moneyMode === 'share' ? money.share : money.bn, { color: SC.green, fmt: AN.moneyMode === 'share' ? (v) => v + '%' : (v) => '$' + v + 'B', max: AN.moneyMode === 'share' ? Math.max(10, ...money.share) * 1.05 : null })}
          <div class="sc-foot">Commitment attributed to approaches: project commitment ÷ its number of approaches${AN.d2 === 'sector' ? ', × the sector\'s coded share' : ''}; adds up to $${money.total_bn}B across the approaches with a known amount.</div></div>
      </div>
      <div class="sc-row2">
        <div class="sc-card">${head(esc(D[AN.d3]), 'over time, by approval FY', 'd3', AN.d3, anSeg('timeMode', AN.timeMode, [['count', 'Count'], ['percent', 'Share']]))}${scStack(fy.labels, fy.series, { percent: AN.timeMode === 'percent' })}<div class="sc-foot">Six largest groups shown; FY${String(d.fy_min).slice(2)}–FY${String(d.fy_max).slice(2)} approvals only.</div></div>
        <div class="sc-card">${head('AI share', 'within each ' + esc(low(AN.d4)), 'd4', AN.d4)}${scHBar(ai.labels, ai.count, { color: SC.red, fmt: (v) => v + '%', max: 100, sub: ai.n.map((n) => n + ' approaches') })}<div class="sc-foot">AI = ${esc(k.ai_rule)}.${AN.d4 === 'sector' ? ' Each approach is spread over its project\'s coded sectors.' : ''}</div></div>
      </div>
      <div class="sc-row2">
        <div class="sc-card"><div class="sc-ct"><b>AI share</b> of approaches over time, by approval FY</div>${scLine(aiFy.labels, aiFy.values, { counts: aiFy.counts })}<div class="sc-foot">Share of each cohort's approaches flagged AI; hover a point for the cohort size.</div></div>
        <div class="sc-card"><div class="sc-ct-row"><div class="sc-ct"><b>${esc(D[AN.cx])}</b> × ${esc(low(AN.cy))}</div><div class="sc-ct-tools">${anDimSelect('cx', AN.cx, { label: 'Rows' })}${anDimSelect('cy', AN.cy, { exclude: AN.cx, label: 'Columns' })}</div></div>${scStack(cross.labels, cross.series, { horizontal: true })}<div class="sc-foot">Counts; six largest column groups shown, the rest grouped.</div></div>
      </div>
    </div>
  </div>`;
  document.querySelectorAll('#anBody [data-an-seg] button').forEach((b) => b.addEventListener('click', () => { AN[b.closest('[data-an-seg]').dataset.anSeg] = b.dataset.v; renderAnalytics(); }));
  document.querySelectorAll('#anBody select[data-an]').forEach((s) => s.addEventListener('change', () => {
    AN[s.dataset.an] = s.value;
    if (AN.cy === AN.cx) AN.cy = Object.keys(AN.data.dims).find((x) => x !== AN.cx);   // the two cross-tab dimensions never coincide
    renderAnalytics(); }));
}
async function loadAnalytics() { AN.data = await api.get('/api/analytics/v2'); renderAnalytics(); }

// ---------------------------------------------------------------- review
function startReviewWith(ids) { go('review'); $('reviewStart').style.display = ''; $('reviewSession').style.display = 'none'; $('rIds').value = ids.join(', '); document.querySelector('#rSeg button[data-src="ids"]').click(); }
function renderReview() {
  const r = state.review;
  $('reviewStart').style.display = r.session ? 'none' : '';
  $('reviewSession').style.display = r.session ? 'grid' : 'none';
  $('btnNewSession').style.display = r.session ? '' : 'none';
  $('rvSessionInfo').textContent = r.session ? `${t('rv.current')}: ${r.ids.length} projects · ${r.session.workflow} · ${r.session.started.slice(11, 16)}` : t('rv.none');
  updateSpotSummary();
  if (r.session) { renderHeat(); renderReviewPage(); }
}
document.querySelectorAll('#rSeg button').forEach((b) => b.addEventListener('click', () => { document.querySelectorAll('#rSeg button').forEach((x) => x.classList.remove('on')); b.classList.add('on'); ['ids', 'db', 'csv'].forEach((k) => $('rSrc-' + k).style.display = b.dataset.src === k ? 'block' : 'none'); }));
$('rCsv').addEventListener('change', async (ev) => { const f = ev.target.files[0]; if (!f) return; const t = await f.text(); const ids = [...new Set(t.match(/P\d{6}/g) || [])]; $('rIds').value = ids.join(', '); $('rCsvInfo').textContent = `${ids.length} IDs detected`; });
async function startSession() {
  const src = document.querySelector('#rSeg button.on').dataset.src;
  let ids = [];
  if (src === 'db') ids = dbSelection(true);
  else ids = [...new Set(($('rIds').value.match(/P\d{6}/g)) || [])];
  if (!ids.length) { alert('No project IDs.'); return; }
  const workflow = state.wfSel || (document.querySelector('input[name=wf]:checked') || {}).value || 'v1';
  const existing = document.querySelector('input[name=ex]:checked').value; const runMode = document.querySelector('input[name=rm]:checked').value;
  const known = new Set(state.projects.map((p) => p.project_id)); const unknown = ids.filter((i) => !known.has(i));
  if (unknown.length && !confirm(`${unknown.length} IDs are not in projects.csv and will be skipped: ${unknown.slice(0, 5).join(', ')}…`)) return;
  ids = ids.filter((i) => known.has(i));
  state.review = { ...state.review, session: { workflow, existing, runMode, started: new Date().toISOString() }, ids, cur: ids[0], filter: 'all', job: null, data: null, ap: 0, thisRound: {} };
  if (runMode === 'all') await runProjects(ids, workflow, existing === 'never' ? 'missing' : 'refresh', existing === 'skip');
  renderReview();
}
async function stopJob() {
  const j = state.review.job; if (!j) return;
  try { const nj = await api.post(`/api/jobs/${j.job_id}/cancel`); nj._offset = j._offset; state.review.job = nj; } catch (e) { alert(e.message); }
  renderReviewPage();
}
async function runProjects(ids, workflow, mode, skipPushed) {
  if (state.review.job && state.review.job.status === 'running') { state.review.runError = 'A run is already in progress. Press Stop first, then Regenerate.'; renderReviewPage(); return; }
  let job;
  const parallel = parseInt(($('rPar') || {}).value || state.review.parallel || 3, 10) || 3; state.review.parallel = parallel;
  try { job = await api.post('/api/run', { project_ids: ids, workflow, mode, skip_pushed: skipPushed, parallel }); }
  catch (e) { let msg = e.message; try { msg = JSON.parse(msg).detail || msg; } catch (_) { /* plain text */ }
    state.review.runError = msg; if (state.review.cur) renderReviewPage(); else alert(msg); return; }
  state.review.runError = ''; state.review.jobReport = null; state.review.jobIds = ids; job._offset = Date.now() / 1000 - (job.server_ts || Date.now() / 1000); state.review.job = job; pollJob();
}
async function pollJob() {
  const j = state.review.job; if (!j) return;
  const cur = await api.get('/api/jobs/' + j.job_id); cur._offset = Date.now() / 1000 - cur.server_ts; state.review.job = cur;
  if (j.status === 'running' && cur.status !== 'running') state.review.jobReport = cur;   // run ended: show the time report
  state.review.thisRound = state.review.thisRound || {};
  Object.entries(cur.results || {}).forEach(([pid, v]) => { if (v === 'done') state.review.thisRound[pid] = true; });
  const changed = j.status !== cur.status || jobRunning(j).join() !== jobRunning(cur).join() || j.done !== cur.done || j.cancel_requested !== cur.cancel_requested;
  if (changed && state.review.cur && cur.status === 'running') renderReviewPage();   // keep Stop / Regenerate buttons in sync
  await loadProjects(); renderHeat();
  if (state.review.cur && cur.results[state.review.cur] && state.review.data && state.review.data.runs.length === 0) { state.review.data = await api.get('/api/projects/' + state.review.cur); renderReviewPage(); }
  if (cur.status === 'running') setTimeout(pollJob, 2500); else { if (state.review.cur) { state.review.data = await api.get('/api/projects/' + state.review.cur); renderReviewPage(); } }
}
const HM_CLASS = { 'not run': 'hq', generated: 'hg', reviewed: 'hv', pushed: 'hp', 'no documents': 'hf', failed: 'hf' };
function renderHeat() {
  const r = state.review; const byId = Object.fromEntries(state.projects.map((p) => [p.project_id, p]));
  const runningNow = new Set(jobRunning(r.job)); const fresh = r.thisRound || {};
  const items = r.ids.map((id) => { const p = byId[id] || {}; let st = HM_CLASS[p.review_status] || 'hq'; let label = p.review_status;
    if (runningNow.has(id)) { st = 'hr'; label = 'running'; }
    else if (st === 'hg' && !fresh[id]) { st = 'hx'; label = 'earlier result (before this session)'; }   // generated in an earlier session
    else if (st === 'hg') label = 'generated in this session';
    return { id, name: p.project_name || '', st, label }; });
  const counts = {}; items.forEach((x) => counts[x.st] = (counts[x.st] || 0) + 1);
  const L = { hq: 'not run', hx: 'earlier result', hr: 'running', hg: 'new this session', hv: 'reviewed', hp: 'pushed', hf: 'failed / no docs' };
  $('hmFilters').innerHTML = ['all', 'hx', 'hr', 'hg', 'hv', 'hp', 'hf', 'hq'].map((k) => `<span class="${r.filter === k ? 'on' : ''}" data-f="${k}">${k === 'all' ? 'all ' + items.length : L[k] + ' ' + (counts[k] || 0)}</span>`).join('');
  $('hmFilters').querySelectorAll('span').forEach((s) => s.addEventListener('click', () => { r.filter = s.dataset.f; renderHeat(); }));
  const q = ($('hmQ').value || '').toLowerCase();
  $('heat').innerHTML = items.map((x) => `<i class="${x.st}${x.id === r.cur ? ' cur' : ''}" style="${(r.filter !== 'all' && x.st !== r.filter) || (q && !x.id.toLowerCase().includes(q)) ? 'opacity:.18' : ''}" title="${x.id} · ${esc(x.name)} · ${x.label}" data-id="${x.id}"></i>`).join('');
  $('heat').querySelectorAll('i').forEach((i) => i.addEventListener('click', () => selectReview(i.dataset.id)));
  const done = items.filter((x) => x.st === 'hv' || x.st === 'hp').length;
  $('hmProg').style.width = Math.round(100 * done / Math.max(1, items.length)) + '%';
  $('hmCount').textContent = '· ' + items.length;
  const j = r.job; const wfo = state.workflows.find((w) => w.version === r.session.workflow) || {};
  const tile = (n, label, cls) => `<div class="stile ${cls}"><b>${n}</b><span>${label}</span></div>`;
  $('hmStats').innerHTML = `<div class="sess">
    <div class="sess-h"><b>${esc(wfo.tag || r.session.workflow)}</b><span class="muted">started ${r.session.started.slice(11, 16)} UTC</span></div>
    <div class="sess-prog"><div class="sess-bar"><span style="width:${Math.round(100 * done / Math.max(1, items.length))}%"></span></div><span>${done} / ${items.length} reviewed</span></div>
    <div class="sess-tiles">${tile(counts.hr || 0, 'running', 'r')}${tile(counts.hg || 0, 'new this session', 'w')}${tile(counts.hx || 0, 'earlier result', 'x')}${tile(counts.hf || 0, 'failed', 'f')}${tile(done, 'reviewed', 'v')}${tile(counts.hq || 0, 'not run', 'q')}</div>
    ${j ? `<div class="sess-job"><span class="pill ${j.status === 'running' ? 'p-warn' : j.status === 'finished' ? 'p-ok' : j.status === 'cancelled' ? 'p-warn' : 'p-bad'}">${esc(j.status)}</span>
      <span>job <span class="mono">${esc(j.job_id)}</span> · ${j.done}/${j.total}${j.parallel > 1 ? ` · ${j.parallel} at a time` : ''}${j.skipped_pushed.length ? ` · ${j.skipped_pushed.length} skipped (pushed)` : ''}</span></div>` : ''}
  </div>`;
  { const byId = Object.fromEntries(state.projects.map((p) => [p.project_id, p]));
    const remaining = r.ids.filter((i) => ['not run', 'failed'].includes((byId[i] || {}).review_status)).length;
    const busy = !!(j && j.status === 'running'); const b = $('btnGenRemaining');
    b.textContent = `▶ Generate all remaining (${remaining})`; b.disabled = busy || !remaining;
    b.title = busy ? 'A run is in progress - stop it or wait until it finishes.'
      : 'Runs every project of this session that has not run yet or failed, ONE AFTER ANOTHER in one background job (not parallel across projects; model calls inside each project are parallel). You can keep reviewing while it runs.';
    $('genRemHint').textContent = busy ? 'disabled while a run is in progress' : remaining ? `${remaining} project${remaining === 1 ? '' : 's'} not run / failed · run one after another, not in parallel` : 'nothing left to generate'; }
  const c = items.find((x) => x.id === r.cur); const idx = items.indexOf(c);
  $('hmCur').innerHTML = c ? `<b>${c.id} <span class="muted" style="font-weight:400">${idx + 1} / ${items.length}</span></b><span class="muted">${esc(c.name)}</span><br><span class="muted">${c.label}</span> · <a href="#" id="hmNext">next unreviewed →</a>` : '';
  const nx = $('hmNext'); if (nx) nx.addEventListener('click', (e) => { e.preventDefault(); nextUnreviewed(1); });
}
function nextUnreviewed(d) { const r = state.review; const byId = Object.fromEntries(state.projects.map((p) => [p.project_id, p])); const i = r.ids.indexOf(r.cur); for (let k = 1; k <= r.ids.length; k++) { const j = (i + d * k + r.ids.length) % r.ids.length; const st = (byId[r.ids[j]] || {}).review_status; if (st === 'generated' || st === 'not run' || st === 'failed') { selectReview(r.ids[j]); return; } } }
async function selectReview(id) { state.review.cur = id; state.review.ap = 0; state.review.data = await api.get('/api/projects/' + id); state.taxonomy = state.review.data.taxonomy; renderHeat(); renderReviewPage(); window.scrollTo(0, 0); }
function queuedIn(job, id) { const ids = job.project_ids || job.ids || []; return ids.includes(id) && !(job.results || {})[id] && !jobRunning(job).includes(id); }
// "v6 - innovation test, ..." -> "innovation test, ..." (the tag in front already says v6.6)
function wfShortName(w) { return String(w.name || '').replace(/^[a-z]?\d+\s*-\s*/i, ''); }
function runPlaceholder() {
  const wf = state.workflows.find((w) => w.version === (($('rWf') || {}).value || (state.review.session || {}).workflow)) || {};
  return `<div class="card runplaceholder"><div class="spin"></div><div><b>Running ${esc(wf.tag || wf.version || '')}…</b>
    <div class="muted">Previous results are hidden while this project runs; the new approaches appear here when the run finishes.</div></div></div>`;
}
async function renderReviewPage() {
  const r = state.review; if (!r.cur) return;
  if (!r.data || r.data.project_id !== r.cur) { r.data = await api.get('/api/projects/' + r.cur); state.taxonomy = r.data.taxonomy; }
  const p = r.data; const i = r.ids.indexOf(r.cur); const locked = p.review_status === 'pushed';
  const body = $('reviewBody'); body.classList.toggle('locked', locked);
  const job = r.job; const jobActive = !!(job && job.status === 'running'); const stopping = jobActive && job.cancel_requested;
  const running = jobActive && (jobRunning(job).includes(p.project_id) || (!jobRunning(job).length && (r.jobIds || []).includes(p.project_id) && !(job.results || {})[p.project_id]));
  r.hideErr = r.hideErr || {};
  const lastFailed = !!(p.last_record && p.last_record.error) && r.hideErr[p.project_id] !== p.last_record.run_id;
  const latestWf = state.workflows.length ? state.workflows[state.workflows.length - 1] : null;
  const errTop = r.runError || (lastFailed ? `Previous run ${fmtTs(p.last_record.started_at).slice(0, 16)} UTC (${p.last_record.workflow_tag || p.last_record.workflow} · ${p.last_record.run_id}) failed: ${p.last_record.error} — this is the stored result of that run; it stays until you Regenerate.` : '');
  const report = !jobActive && r.jobReport ? jobReportHtml(r.jobReport) : '';
  body.innerHTML = `${report}${errTop ? `<div class="errbanner"><b>⚠ Error</b> ${esc(errTop)}${/API_KEY|API key/.test(errTop) ? ' <a href="#" id="goSetup">→ open Setup</a>' : ''}
      ${!r.runError && lastFailed ? `<div class="errbtns">${jobActive ? '<span>⏳ a run is in progress…</span>' : `<button class="btn sm primary" id="errRegen">▶ Regenerate with ${esc(($('rWf') && $('rWf').value) || (latestWf && latestWf.tag) || '')}</button>`}
        <button class="btn sm ghost" id="errHide" title="hide this message for this run">Dismiss</button></div>` : ''}</div>` : ''}${locked ? `<div class="lockbanner">✔ Pushed to database ${fmtTs(p.pushed_at)}. This review page is frozen; further edits are made in Database. <button class="btn sm ghost" style="color:#fff;border-color:#64748b" id="btnReopen">Reopen for review</button></div>` : ''}
    <div class="card pnav"><div class="toolbar"><div><b style="font-size:17px">${p.project_id}</b> <span class="muted">· ${esc(p.project_name)}</span> ${running ? `<span class="pill p-info">⏳ ${stopping ? 'stopping' : 'running'}</span>` : (jobActive && queuedIn(job, p.project_id) ? '<span class="pill p-muted">queued</span>' : pill(p.review_status))}</div>
      <div class="right toolbar"><button class="btn sm" id="btnPrev">← Prev</button><span class="muted">${i + 1} / ${r.ids.length}</span><button class="btn sm" id="btnNext">Next →</button></div></div>
      <div class="toolbar editable" style="margin-top:10px"><select id="rWf" style="width:220px">${state.workflows.map((w) => `<option value="${w.version}" ${w.version === r.session.workflow ? 'selected' : ''}>${esc(w.tag || w.version)} — ${esc(wfShortName(w))}</option>`).join('')}</select>
      <button class="btn primary" id="btnRun" ${jobActive ? 'disabled title="A run is in progress: stop it first"' : ''}>▶ ${p.runs.length ? 'Regenerate' : 'Run'}</button>
      ${jobActive ? `<button class="btn danger" id="btnStop" ${stopping ? 'disabled' : ''}>■ ${stopping ? 'Stopping…' : 'Stop'}</button>
        <span style="color:var(--bad);font-weight:600">⏳ ${stopping ? 'stopping after the current model calls' : 'running'} · ${jobRunning(job).length > 1 ? jobRunning(job).length + ' projects' : esc(job.current || '')} · ${job.done}/${job.total}</span>
        <span class="jobtimer" id="jobTimer"></span>` : ''}
      ${job && job.status === 'cancelled' ? '<span class="muted">run stopped by user</span>' : ''}
      <span class="right muted">${p.runs.length ? `Current: ${p.runs[0].workflow_tag || p.runs[0].workflow} · ${fmtTs(p.runs[0].started_at).slice(0, 16)} · tier ${p.runs[0].innovation_tier} (${p.runs[0].keyword_hits} hits)` : 'not run yet'}</span></div></div>
    <div class="grid2"><div class="card">${basicInfo(p)}</div>
      <div class="card"><h3>Documents</h3><table><tr><th>Type</th><th>Date</th><th>Source</th><th>Used</th></tr>${p.documents.map((d) => { const used = (p.last_record && p.last_record.documents_used || []).find((u) => u.guid === d.guid); return `<tr><td>${d.doc_type}</td><td>${d.doc_date}</td><td>${d.source === 'api' ? '<span class="pill p-purple">API</span>' : 'documents/'}</td><td>${used ? '✓ ' + used.role : '–'}</td></tr>`; }).join('') || '<tr><td colspan="4" class="muted">none</td></tr>'}</table></div></div>
    ${running ? runPlaceholder() : `
    <div class="card editable"><h3>Innovation assessment ${p.review_status === 'generated' ? '<span class="pill p-warn">needs review</span>' : ''}</h3>${resultSummary(p)}${approachesBlock(p, r.ap, 'review')}
      <label>Reviewer notes</label><textarea id="rNotes">${esc(p.notes || '')}</textarea></div>
    ${p.last_record ? `<div class="card"><h3>Workflow trace <span class="muted" style="font-weight:400">${p.last_record.workflow_tag || p.last_record.workflow} · ${p.last_record.run_id}</span></h3><div class="steps">${p.last_record.trace.map((t) => `<div class="stepbox"><b>${esc(t.step)}</b>${esc(t.note || t.status)}${t.llm_calls ? `<br><span class="muted">${t.llm_calls} LLM call${t.llm_calls > 1 ? 's' : ''}</span>` : ''}</div>`).join('<span class="arrow">→</span>')}</div></div>` : ''}
    `}
    <div class="footer-actions"><button class="btn" id="btnSave" ${running ? 'disabled' : ''}>Save edits</button><button class="btn" id="btnSkip">Skip</button><button class="btn ok" id="btnPush" ${locked || running ? 'disabled' : ''}>✔ Push to database</button></div>`;
  wireCommon(body, p, 'review');
  $('btnPrev').addEventListener('click', () => selectReview(r.ids[(i - 1 + r.ids.length) % r.ids.length]));
  $('btnNext').addEventListener('click', () => selectReview(r.ids[(i + 1) % r.ids.length]));
  $('btnSkip').addEventListener('click', () => nextUnreviewed(1));
  $('btnRun').addEventListener('click', async () => { await runProjects([p.project_id], $('rWf').value, 'refresh', false); renderReviewPage(); });
  const eg = $('errRegen'); if (eg) { eg.textContent = `▶ Regenerate with ${(state.workflows.find((w) => w.version === $('rWf').value) || {}).tag || $('rWf').value}`;
    eg.addEventListener('click', async () => { await runProjects([p.project_id], $('rWf').value, 'refresh', false); renderReviewPage(); }); }
  const eh = $('errHide'); if (eh) eh.addEventListener('click', () => { r.hideErr[p.project_id] = p.last_record.run_id; renderReviewPage(); });
  async function saveReviewEdits() {
    for (const a of p.approaches) { const changes = []; body.querySelectorAll(`[data-edit][data-aid="${a.approach_id}"]`).forEach((el) => { if ((el.value || '') !== (a[el.dataset.edit] || '')) changes.push([el.dataset.edit, el.value]); }); for (const [f, v] of changes) await api.post(`/api/projects/${p.project_id}/edits`, { approach_id: a.approach_id, field: f, value: v, reason: 'review session ' + r.session.workflow }); }
    const notes = $('rNotes').value; if (notes !== (p.notes || '')) await api.post(`/api/projects/${p.project_id}/edits`, { field: 'notes', value: notes, reason: '' });
  }
  $('btnSave').addEventListener('click', async () => { await saveReviewEdits(); await loadProjects(); refreshCurrent(p.project_id, 'review'); renderHeat(); });
  $('btnPush').addEventListener('click', async () => { await saveReviewEdits(); await api.post(`/api/projects/${p.project_id}/status`, { status: 'pushed' }); await loadProjects(); refreshCurrent(p.project_id, 'review'); renderHeat(); });
  const st = $('btnStop'); if (st) st.addEventListener('click', stopJob);
  const cr = $('btnCloseReport'); if (cr) cr.addEventListener('click', () => { r.jobReport = null; renderReviewPage(); });
  body.querySelectorAll('.rrrow[data-jump]').forEach((tr) => tr.addEventListener('click', () => selectReview(tr.dataset.jump)));
  tickJobTimer();
  const gs = $('goSetup'); if (gs) gs.addEventListener('click', (e) => { e.preventDefault(); go('setup'); });
  const ro = $('btnReopen'); if (ro) ro.addEventListener('click', async () => { await api.post(`/api/projects/${p.project_id}/status`, { status: 'reviewed' }); await loadProjects(); refreshCurrent(p.project_id, 'review'); renderHeat(); });
}

// ---------------------------------------------------------------- workflow panel (inside Approach Spot)
// Version list -> flowchart of the selected version; clicking a step opens the code page.
state.wfSel = null;
async function loadWorkflows() {
  try { state.workflows = await api.get('/api/workflows'); } catch (e) { $('wfList').innerHTML = `<div class="note">${esc(e.message)}</div>`; return; }
  const ws = state.workflows;
  if (!state.wfSel || !ws.some((w) => w.version === state.wfSel)) state.wfSel = ws.length ? ws[ws.length - 1].version : null;
  const opts = ws.map((w) => `<option>${w.version}</option>`).join('');
  $('cmpA').innerHTML = opts; $('cmpB').innerHTML = opts;
  if (ws.length >= 2) { $('cmpA').value = ws[ws.length - 2].version; $('cmpB').value = ws[ws.length - 1].version; }
  $('btnCompare').onclick = compareWorkflows;
  renderWfList();
  if (state.wfSel) showWorkflow(state.wfSel);
}
function renderWfList() {
  const ws = state.workflows; const latest = ws.length ? ws[ws.length - 1].version : null;
  $('wfList').innerHTML = [...ws].reverse().map((w) => `<label class="wfrow ${w.version === state.wfSel ? 'on' : ''}">
      <input type="radio" name="wf" value="${w.version}" ${w.version === state.wfSel ? 'checked' : ''}>
      <span class="wfv" title="version tag (releases.json)">${esc(w.tag || w.version)}</span>
      <span class="wfn">${esc(w.name.replace(/^v\d+\s*-\s*/, ''))}</span>
      <span class="wfm">${w.version === latest ? '<span class="pill p-ok">latest</span> ' : ''}${w.released === false ? '<span class="pill p-warn" title="the folder changed after its last release; run: piaa release ' + w.version + ' --note ...">unreleased edits</span> ' : ''}<span class="muted mono">${(w.steps || []).length} steps · ${w.hash}</span></span></label>`).join('') || '<span class="muted">No workflow found.</span>';
  $('wfList').querySelectorAll('input[name=wf]').forEach((i) => i.addEventListener('change', () => { state.wfSel = i.value; renderWfList(); showWorkflow(i.value); updateSpotSummary(); }));
  updateSpotSummary();
}
async function showWorkflow(v) {
  const w = state.workflows.find((x) => x.version === v); if (!w) return;
  $('wfSelHead').innerHTML = `<b>${v}</b> · ${esc(w.name.replace(/^v\d+\s*-\s*/, ''))}<div class="muted" style="font-size:12px;margin-top:2px">${esc((w.config.description || '').trim())}</div>`;
  $('wfFlow').innerHTML = '<div class="muted" style="padding:10px"><span class="spin"></span></div>';
  const data = await api.get(`/api/workflows/${v}/steps`);
  if (state.wfSel !== v) return;
  drawFlow(data, $('wfFlow'), (st) => openCode('approach', v, { type: 'step', id: st.name }, 'review'));
  $('wfFrame').srcdoc = await (await fetch(`/api/workflows/${v}/html`)).text();
}
// vertical flowchart (fits a narrow column); every step is a button to its code
function drawFlow(data, el, onStep) {
  const steps = data.steps || [];
  el.innerHTML = steps.map((st, i) => `<div class="fstep">
      <button class="fnode ${st.kind}" data-i="${i}">
        <span class="fidx">${i + 1}</span>
        <span class="fbody"><span class="ftitle">${esc(st.label)} <span class="fkind">${st.kind === 'llm' ? 'LLM' : 'Python'}${st.prompts.length ? ` · ${st.prompts.length} prompt${st.prompts.length > 1 ? 's' : ''}` : ''}</span></span>
          <span class="fsum">${esc(st.summary || '')}</span>
          <span class="fio">${(st.inputs || []).length ? `<span>◂ ${esc(st.inputs.join(', '))}</span>` : ''}${(st.outputs || []).length ? `<span>▸ ${esc(st.outputs.join(', '))}</span>` : ''}</span></span>
        <span class="fgo">${t('sp.code', 'code')} →</span>
      </button></div>`).join('') + `<div class="muted" style="font-size:12px;margin-top:8px">${t('wf.clickHint')}</div>`;
  el.querySelectorAll('.fnode').forEach((b) => b.addEventListener('click', () => onStep(steps[Number(b.dataset.i)])));
}
// "From database": projects matching the review-status filter, optionally reduced to a random or first-N subset.
function dbMatching() {
  const st = $('rDbFilter').value;
  return state.projects.filter((p) => st === 'all' || p.review_status === st).map((p) => p.project_id).sort();
}
function dbSelection(draw) {
  const all = dbMatching(); const mode = ($('rDbPick') || {}).value || 'all';
  const n = Math.max(1, parseInt(($('rDbN') || {}).value, 10) || 10);
  if (mode === 'first') return all.slice(0, n);
  if (mode === 'random') {
    if (draw || !state.dbSample || state.dbSample.key !== `${$('rDbFilter').value}|${n}`) {   // new draw when the filter or N changes, and at Start
      const a = [...all]; for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
      state.dbSample = { key: `${$('rDbFilter').value}|${n}`, ids: a.slice(0, n).sort() };
    }
    return state.dbSample.ids;
  }
  return all;
}
function dbSubsetText() {
  const mode = ($('rDbPick') || {}).value || 'all'; const all = dbMatching(); const n = Math.max(1, parseInt(($('rDbN') || {}).value, 10) || 10);
  if (mode === 'all') return `${all.length} matching`;
  return `${mode === 'random' ? 'random' : 'first'} ${Math.min(n, all.length)} of ${all.length} matching`;
}
function updateSpotSummary() {
  const el = $('spSummary'); if (!el) return;
  const src = (document.querySelector('#rSeg button.on') || {}).dataset; const ids = [...new Set(($('rIds').value.match(/P\d{6}/g)) || [])];
  if ($('rDbInfo')) { $('rDbInfo').textContent = dbSubsetText() + (($('rDbPick') || {}).value === 'random' ? ' · new random draw at start' : ''); $('rDbN').disabled = $('rDbPick').value === 'all'; }
  const what = src && src.src === 'db' ? `${t('sp.fromDb', 'from database')}: ${$('rDbFilter').value} · ${dbSubsetText()}` : `${ids.length} ${t('sp.ids', 'project IDs')}`;
  el.innerHTML = `${what} · ${t('sp.workflowLbl', 'workflow')} <b>${state.wfSel || '—'}</b>`;
}

// ---------------------------------------------------------------- code page (workflow step -> code, prompts, files, modules)
async function openCode(kind, version, focus, back) {
  state.code = { kind, version, focus, back: back || (kind === 'pattern' ? 'patterns' : 'review'), data: null, cache: {} };
  go('code');
  const base = kind === 'pattern' ? '/api/patterns/workflows' : '/api/workflows';
  try { state.code.data = await api.get(`${base}/${version}/steps`); } catch (e) { $('codeMain').innerHTML = `<div class="note">${esc(e.message)}</div>`; return; }
  renderCode();
}
function renderCode() {
  const c = state.code; if (!c || !c.data) return;
  const d = c.data;
  $('codeBack').textContent = `← ${c.back === 'patterns' ? t('nav.patterns', 'Patterns') : t('nav.review', 'Approach Spot')}`;
  $('codeTitle').textContent = `${d.version} · ${d.name.replace(/^[a-z]?\d+\s*-\s*/i, '')}`;
  $('codeSub').textContent = `${d.folder}  ·  ${d.tag || d.version}  ·  hash ${d.hash}`;
  const f = c.focus || { type: 'step', id: (d.steps[0] || {}).name };
  const item = (type, id, label, sub) => `<a href="#" class="cn ${f.type === type && f.id === id ? 'on' : ''}" data-t="${type}" data-id="${esc(id)}">${label}${sub ? `<small>${sub}</small>` : ''}</a>`;
  $('codeNav').innerHTML = `<h4>${t('cd.steps', 'Steps')}</h4>` + d.steps.map((s, i) => item('step', s.name, `<span class="cnum ${s.kind}">${i + 1}</span>${esc(s.label)}`, '')).join('') +
    `<h4>${t('cd.files', 'Workflow folder')}</h4>` + d.files.map((p) => item('file', p, `<span class="mono">${esc(p)}</span>`, '')).join('') +
    (d.imports.length ? `<h4>${t('cd.modules', 'Package modules used')}</h4>` + d.imports.map((m) => item('module', m.module, `<span class="mono">${esc(m.path)}</span>`, '')).join('') : '');
  $('codeNav').querySelectorAll('.cn').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); c.focus = { type: a.dataset.t, id: a.dataset.id }; renderCode(); window.scrollTo(0, 0); }));
  if (f.type === 'step') renderCodeStep(d, d.steps.find((s) => s.name === f.id) || d.steps[0]);
  else renderCodeFile(f.type, f.id);
}
function codeBlock(text, start, lang) {
  const lines = String(text || '').replace(/\n$/, '').split('\n');
  const hl = (l) => { let h = esc(l); if (lang === 'py') { h = h.replace(/(#.*)$/, '<span class="c-com">$1</span>').replace(/^(\s*)(def|class|async def)\b/, '$1<span class="c-kw">$2</span>'); } return h; };
  return `<div class="code"><table>${lines.map((l, i) => `<tr><td class="ln">${(start || 1) + i}</td><td class="lc">${hl(l) || ' '}</td></tr>`).join('')}</table></div>`;
}
function langOf(p) { return /\.py$/.test(p) ? 'py' : /\.ya?ml$/.test(p) ? 'yaml' : /\.md$/.test(p) ? 'md' : /\.html$/.test(p) ? 'html' : ''; }
function yamlish(o, ind) { ind = ind || ''; if (o == null || typeof o !== 'object') return String(o); return Object.entries(o).map(([k, v]) => (v && typeof v === 'object' && !Array.isArray(v)) ? `${ind}${k}:\n${yamlish(v, ind + '  ')}` : `${ind}${k}: ${Array.isArray(v) ? '[' + v.join(', ') + ']' : v}`).join('\n'); }
function renderCodeStep(d, st) {
  const c = state.code; const i = d.steps.indexOf(st);
  const cfg = d.config[st.name];
  const fileLink = st.file ? `<a href="#" class="mono" data-mod="${esc(st.module)}">${esc(st.file)}:${st.line}</a>` : '<span class="muted">source not found</span>';
  const shared = st.file && !st.file.startsWith(d.folder) ? `<span class="pill p-muted" title="${t('cd.sharedT', 'This step is reused from another workflow version')}">${t('cd.shared', 'inherited')}</span>` : '';
  $('codeMain').innerHTML = `<div class="card">
      <div class="toolbar"><span class="cnum big ${st.kind}">${i + 1}</span><h3 style="margin:0">${esc(st.label)}</h3><span class="pill ${st.kind === 'llm' ? 'p-purple' : 'p-info'}">${st.kind === 'llm' ? 'LLM' : 'Python'}</span>${shared}<span class="right"></span>
        <button class="btn sm" id="cdPrev" ${i <= 0 ? 'disabled' : ''}>← ${t('cd.prev', 'Previous step')}</button><button class="btn sm" id="cdNext" ${i >= d.steps.length - 1 ? 'disabled' : ''}>${t('cd.next', 'Next step')} →</button></div>
      <div style="margin:8px 0 10px;font-size:14px">${esc(st.summary)}</div>
      <dl class="kv"><dt>${t('cd.function', 'Function')}</dt><dd class="mono">${esc(st.module)}.step_${esc(st.name)}</dd><dt>${t('cd.file', 'Defined in')}</dt><dd>${fileLink}</dd>
        <dt>${t('cd.inputs', 'Inputs')}</dt><dd>${(st.inputs || []).map((x) => `<span class="chip">${esc(x)}</span>`).join('') || '—'}</dd><dt>${t('cd.outputs', 'Outputs')}</dt><dd>${(st.outputs || []).map((x) => `<span class="chip">${esc(x)}</span>`).join('') || '—'}</dd>
        <dt>${t('cd.prompts', 'Prompt files')}</dt><dd>${(st.prompts || []).map((k) => `<a href="#" class="chip mono" data-file="prompts/${k}.md">prompts/${k}.md</a>`).join('') || '—'}</dd></dl></div>
    <div class="card"><h3>${t('cd.source', 'Python source')} <span class="muted mono" style="font-weight:400;font-size:12px">${esc(st.file)}</span></h3>${codeBlock(st.source || '(source not available)', st.line, 'py')}</div>
    ${cfg && typeof cfg === 'object' ? `<div class="card"><h3>config.yaml → <span class="mono">${esc(st.name)}</span></h3>${codeBlock(yamlish(cfg), 1, 'yaml')}</div>` : ''}
    ${(st.prompts || []).map((k) => `<div class="card"><h3>prompts/${esc(k)}.md</h3>${codeBlock(d.prompts[k] || '', 1, 'md')}</div>`).join('')}`;
  const go2 = (j) => { c.focus = { type: 'step', id: d.steps[j].name }; renderCode(); window.scrollTo(0, 0); };
  $('cdPrev').onclick = () => go2(i - 1); $('cdNext').onclick = () => go2(i + 1);
  bindCodeLinks();
}
async function renderCodeFile(type, id) {
  const c = state.code; const key = type + ':' + id;
  $('codeMain').innerHTML = '<div class="card"><span class="spin"></span></div>';
  let f = c.cache[key];
  try { if (!f) f = c.cache[key] = type === 'module' ? await api.get(`/api/code/module?name=${encodeURIComponent(id)}`) : await api.get(`/api/code/file?kind=${c.kind}&version=${c.version}&path=${encodeURIComponent(id)}`); }
  catch (e) { $('codeMain').innerHTML = `<div class="note">${esc(e.message)}</div>`; return; }
  if (c.focus.type !== type || c.focus.id !== id) return;
  const imps = f.imports && f.imports.length ? `<div style="margin-top:6px">${f.imports.map((m) => `<a href="#" class="chip mono" data-mod="${esc(m.module)}">${esc(m.module)}</a>`).join('')}</div>` : '';
  const isHtml = /\.html$/.test(f.path);
  $('codeMain').innerHTML = `<div class="card"><div class="toolbar"><h3 style="margin:0" class="mono">${esc(f.path)}</h3><span class="right"></span><span class="muted" style="font-size:12px">${String(f.text).split('\n').length} lines</span></div>${imps ? `<div class="muted" style="font-size:12px;margin-top:6px">${t('cd.imports', 'Imports from the package')}:</div>${imps}` : ''}</div>
    ${isHtml ? `<div class="card"><iframe class="wfframe" style="height:520px" id="cdFrame"></iframe></div>` : ''}
    <div class="card">${codeBlock(f.text, 1, langOf(f.path))}</div>`;
  if (isHtml) $('cdFrame').srcdoc = f.text;
  bindCodeLinks();
}
function bindCodeLinks() {
  const c = state.code;
  $('codeMain').querySelectorAll('[data-file]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); c.focus = { type: 'file', id: a.dataset.file }; renderCode(); window.scrollTo(0, 0); }));
  $('codeMain').querySelectorAll('[data-mod]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); c.focus = { type: 'module', id: a.dataset.mod }; renderCode(); window.scrollTo(0, 0); }));
}

async function compareWorkflows() {
  const a = $('cmpA').value, b = $('cmpB').value;
  $('wfCompare').innerHTML = `<div class="muted"><span class="spin"></span>${LANG === 'zh' ? '正在生成对比报告…' : 'Generating comparison…'}<div class="pbar"><i></i></div></div>`;
  let d; try { d = await api.get(`/api/workflows/compare?a=${a}&b=${b}`); } catch (e) { $('wfCompare').innerHTML = `<div class="note">${esc(e.message)}</div>`; return; }
  const zh = LANG === 'zh';
  const metaA = d.a.steps_meta || {}, metaB = d.b.steps_meta || {};
  const stepRow = (name, inA, inB) => { const m = metaB[name] || metaA[name] || {}; return `<tr><td class="mono">${name}</td><td>${inA ? '✓' : '—'}</td><td>${inB ? '✓' : '—'}</td><td><span class="pill ${m.kind === 'llm' ? 'p-purple' : 'p-info'}">${m.kind || 'python'}</span></td><td>${esc(m.summary || '')}</td></tr>`; };
  const allSteps = [...new Set([...d.steps.a, ...d.steps.b])];
  const promptRows = Object.entries(d.prompts).map(([k, v]) => `<tr><td class="mono">${k}</td><td>${v.status === 'same' ? '<span class="pill p-ok">' + t('cmp.same') + '</span>' : v.status === 'changed' ? '<span class="pill p-warn">' + t('cmp.changed') + ' · ' + Math.round(v.similarity * 100) + '%</span>' : '<span class="pill p-muted">' + t('cmp.onlyA') + ' ' + (v.status === 'only_in_a' ? a : b) + '</span>'}</td><td>${v.chars_a || 0} / ${v.chars_b || 0}</td></tr>`).join('');
  const res = (v) => { const r = d.results[v] || {}; return `<tr><td><b>${v}</b></td><td>${r.projects_run || 0}</td><td>${r.runs || 0}</td><td>${r.approaches_headline || 0}</td><td>${Object.entries(r.innovative || {}).map(([k, n]) => `${k} ${n}`).join(' · ') || '—'}</td><td>${fmtTs(r.last_run || '')}</td></tr>`; };
  // narrative summary (Chinese or English) built from the structural differences
  const onlyB = d.steps.only_b, onlyA = d.steps.only_a, changed = Object.entries(d.prompts).filter(([, v]) => v.status !== 'same').map(([k]) => k);
  const summary = zh
    ? `<p><b>${a} → ${b}：</b>${onlyB.length ? `${b} 新增步骤 <b>${onlyB.join('、')}</b>；` : ''}${onlyA.length ? `去掉了 ${a} 的 <b>${onlyA.join('、')}</b>；` : ''}${d.steps.shared.length} 个步骤共有。` +
      `${changed.length ? `Prompt 有差异的文件：<b>${changed.join('、')}</b>。` : 'Prompt 文件完全相同。'} 配置差异 ${d.config_diff.filter((l) => /^[+-](?![+-])/.test(l)).length} 行。` +
      `${d.results[a] && d.results[a].projects_run ? `本库中 ${a} 跑过 ${d.results[a].projects_run} 个项目（计入统计的方法 ${d.results[a].approaches_headline} 个）` : `本库中 ${a} 没有运行记录`}；${d.results[b] && d.results[b].projects_run ? `${b} 跑过 ${d.results[b].projects_run} 个项目（${d.results[b].approaches_headline} 个）。` : `${b} 没有运行记录。`}</p>`
    : `<p><b>${a} → ${b}:</b> ${onlyB.length ? `${b} adds <b>${onlyB.join(', ')}</b>; ` : ''}${onlyA.length ? `drops <b>${onlyA.join(', ')}</b>; ` : ''}${d.steps.shared.length} shared steps. ${changed.length ? `Prompt files that differ: <b>${changed.join(', ')}</b>.` : 'Prompt files identical.'} ${d.config_diff.filter((l) => /^[+-](?![+-])/.test(l)).length} changed config lines.</p>`;
  $('wfCompare').innerHTML = `<h3 style="margin:6px 0">${t('cmp.summary')}</h3>${summary}
    <div class="grid2"><div><h3>${t('cmp.changelog')} · ${a}</h3><div class="tree" style="white-space:pre-wrap;font-size:11px">${esc(d.a.changelog)}</div></div><div><h3>${t('cmp.changelog')} · ${b}</h3><div class="tree" style="white-space:pre-wrap;font-size:11px">${esc(d.b.changelog)}</div></div></div>
    <h3>${t('cmp.steps')}</h3><table><tr><th>step</th><th>${a}</th><th>${b}</th><th>kind</th><th>summary</th></tr>${allSteps.map((n) => stepRow(n, d.steps.a.includes(n), d.steps.b.includes(n))).join('')}</table>
    <h3>${t('cmp.prompts')}</h3><table><tr><th>file</th><th>status</th><th>chars ${a} / ${b}</th></tr>${promptRows}</table>
    <h3>${t('cmp.results')}</h3><table><tr><th>version</th><th>${t('cmp.projects')}</th><th>runs</th><th>${t('cmp.headline')}</th><th>innovative</th><th>last run</th></tr>${res(a)}${res(b)}</table>
    <h3>${t('cmp.config')}</h3><div class="tree" style="white-space:pre-wrap;font-size:11px">${d.config_diff.length ? d.config_diff.map((l) => `<span style="color:${l.startsWith('+') ? '#065f46' : l.startsWith('-') ? '#991b1b' : '#475569'}">${esc(l)}</span>`).join('\n') : (zh ? '无差异' : 'no differences')}</div>`;
}

// ---------------------------------------------------------------- patterns (replication & scaling, portfolio level)
// One page tells the story: method funnel with counts -> filters -> key findings -> 5 views.
state.pat = { runs: [], wfs: [], result: null, view: 'both', sector: '', region: '', country: '', fyFrom: '', fyTo: '', q: '', basis: 'auto', open: null, showAll: false, pairTab: 'verified', pairPage: 0, wf: null, colAll: false };
const C_ORIGIN = '#2f6fed', C_REP = '#f59e0b', C_SCALE = '#0f9d7a';
const pct = (x) => `${Math.round((x || 0) * 100)}%`;
const fyl = (y) => (y ? 'FY' + String(y).slice(-2) : '—');

async function loadPatterns(run) {
  const P = state.pat;
  try { [P.runs, P.wfs] = await Promise.all([api.get('/api/patterns/runs'), api.get('/api/patterns/workflows')]); } catch (e) { $('patBody').innerHTML = `<div class="note">✖ ${esc(e.message)}${/Not Found/.test(e.message) ? ' — ' + t('pt.restart', 'restart <code>piaa serve</code> so the server loads the Patterns endpoints.') : ''}</div>`; renderPatFilters(); return; }
  P.wf = P.wfs.length ? P.wfs[P.wfs.length - 1].version : null;
  $('patRun').innerHTML = P.runs.map((r) => `<option value="${esc(r.run)}">${esc(r.run)}${r.label ? ' · ' + esc(r.label) : ''}</option>`).join('') || `<option value="">${t('pt.noRun', 'no result yet')}</option>`;
  { const pw = P.wfs.find((w) => w.version === P.wf) || {}; $('patRunBtn').textContent = `▶ ${t('pt.runV', 'Run')} ${pw.tag || P.wf || ''}`; }
  if (!P.runs.length) { P.result = null; renderPatterns(); return; }
  const name = run || (P.result && P.runs.some((r) => r.run === P.result.run) ? P.result.run : P.runs[0].run);
  $('patRun').value = name;
  P.result = await api.get(`/api/patterns/result?run=${encodeURIComponent(name)}`);
  P.open = null; P.pairPage = 0;
  renderPatterns();
}
async function runPatterns() {
  const P = state.pat;
  $('patRunBtn').disabled = true;
  $('patJob').innerHTML = `<div class="card jobcard"><div class="toolbar"><span class="spin"></span><b>${t('pt.running', 'Pattern analysis')}</b> <span class="muted">${t('pt.starting', 'starting…')}</span></div></div>`;
  let job;
  try { job = await api.post('/api/patterns/run', { workflow: P.wf }); }
  catch (e) { $('patRunBtn').disabled = false; $('patJob').innerHTML = `<div class="note">✖ ${t('pt.runFail', 'Could not start the pattern analysis')}: ${esc(e.message)}${/Not Found/.test(e.message) ? ' — ' + t('pt.restart', 'restart <code>piaa serve</code> so the server loads the Patterns endpoints.') : ''}</div>`; return; }
  const poll = async () => {
    const j = await api.get('/api/jobs/' + job.job_id);
    $('patJob').innerHTML = `<div class="card jobcard"><div class="toolbar">${j.status === 'running' ? '<span class="spin"></span>' : (j.status === 'finished' ? '✔' : '✖')}<b>${t('pt.running', 'Pattern analysis')}</b> <span class="muted">${esc(j.status)}</span></div><div class="mono joblog">${j.log.map(esc).join('<br>')}</div></div>`;
    if (j.status === 'running') { setTimeout(poll, 900); return; }
    $('patRunBtn').disabled = false;
    if (j.status === 'finished') { await loadPatterns(j.run); setTimeout(() => { $('patJob').innerHTML = ''; }, 5000); }
  };
  poll();
}

// ---- filters (one sticky row above all tables; every table below follows it)
const patActive = () => { const P = state.pat; return !!(P.sector || P.region || P.country || P.fyFrom || P.fyTo || P.q || P.view !== 'both'); };
function memberOk(m) {
  const P = state.pat;
  return (!P.sector || m.major_sector === P.sector) && (!P.region || m.region_short === P.region) && (!P.country || m.country === P.country)
    && (!P.fyFrom || (m.fy && m.fy >= Number(P.fyFrom))) && (!P.fyTo || (m.fy && m.fy <= Number(P.fyTo)));
}
function patView() {
  const P = state.pat; const R = P.result; const q = P.q.trim().toLowerCase();
  const textOk = (p) => !q || p.label.toLowerCase().includes(q) || p.members.some((m) => m.name.toLowerCase().includes(q) || m.project_id.toLowerCase().includes(q));
  const pats = R.patterns.filter((p) => (P.view === 'both' || p[P.view] > 0) && p.members.some(memberOk) && textOk(p));
  const keep = new Set(pats.map((p) => p.pattern_id));
  const events = R.events.filter((e) => keep.has(e.pattern_id) && (P.view === 'both' || e.type === P.view)
    && memberOk({ major_sector: e.sector, region_short: e.region, country: e.country, fy: e.fy }));
  const pairs = R.pairs.filter((x) => (P.view === 'both' || x.relation === P.view) && (!q || `${x.name_a} ${x.name_b} ${x.project_a} ${x.project_b}`.toLowerCase().includes(q))
    && (x.sector_a === undefined || [['a'], ['b']].some(([k]) => memberOk({ major_sector: x['sector_' + k], region_short: x['region_' + k], country: x['country_' + k], fy: x['fy_' + k] })))
    && (x.sector_a !== undefined || !P.country || x.country_a === P.country || x.country_b === P.country));
  return { pats, events, pairs };
}
function renderPatFilters() {
  const P = state.pat; const R = P.result; const el = $('patFilters');
  const ok = R && R.events;
  const all = ok ? R.patterns.flatMap((p) => p.members) : [];
  const uniq = (f) => [...new Set(all.map(f).filter(Boolean))].sort((a, b) => String(a).localeCompare(String(b)));
  const fys = uniq((m) => m.fy);
  const sel = (id, label, cur, vals, fmt) => `<label class="pf ${cur ? 'on' : ''}"><span>${label}</span><select id="${id}" ${ok ? '' : 'disabled'}><option value="">${t('pt.any', 'All')}</option>${vals.map((v) => `<option value="${esc(v)}" ${String(v) === String(cur) ? 'selected' : ''}>${esc(fmt ? fmt(v) : v)}</option>`).join('')}</select></label>`;
  const seg = (v, l, c) => `<button class="${P.view === v ? 'on' : ''}" data-view2="${v}" ${ok ? '' : 'disabled'}>${c ? `<i style="background:${c}"></i>` : ''}${l}</button>`;
  el.innerHTML = `<div class="dbsearch" style="flex:0 1 220px"><span class="ico">⌕</span><input type="search" id="patQ" placeholder="${t('pt.search', 'Search approach or project…')}" value="${esc(P.q)}" ${ok ? '' : 'disabled'}></div>
    <div class="seg2">${seg('both', t('pt.both', 'Both'))}${seg('replication', t('pt.rep', 'Replication'), C_REP)}${seg('scaling', t('pt.scale', 'Scaling'), C_SCALE)}</div>
    ${sel('pfSec', t('pt.sector', 'Sector'), P.sector, uniq((m) => m.major_sector))}
    ${sel('pfReg', t('pt.region', 'Region'), P.region, uniq((m) => m.region_short))}
    ${sel('pfCty', t('pt.country', 'Country'), P.country, uniq((m) => m.country))}
    ${sel('pfFrom', t('pt.fyFrom', 'FY from'), P.fyFrom, fys, fyl)}
    ${sel('pfTo', t('pt.fyTo', 'FY to'), P.fyTo, fys, fyl)}
    ${patActive() ? `<button class="fbtn link" id="patClear">✕ ${t('db.reset0', 'Reset')}</button>` : ''}
    ${ok ? '' : `<span class="muted" style="font-size:12px">${t('pt.fNo', 'Filters become available after a run of the current workflow.')}</span>`}`;
  if (!ok) return;
  const upd = () => { P.open = null; P.pairPage = 0; P.showAll = false; renderPatFilters(); renderPatMain(); };
  el.querySelectorAll('[data-view2]').forEach((b) => b.addEventListener('click', () => { P.view = b.dataset.view2; upd(); }));
  [['pfSec', 'sector'], ['pfReg', 'region'], ['pfCty', 'country'], ['pfFrom', 'fyFrom'], ['pfTo', 'fyTo']].forEach(([id, k]) => { $(id).onchange = () => { P[k] = $(id).value; upd(); }; });
  let tm; $('patQ').oninput = () => { clearTimeout(tm); tm = setTimeout(() => { P.q = $('patQ').value; P.open = null; P.pairPage = 0; renderPatMain(); const c = $('patClear'); if (!c && patActive()) renderPatFilters(); }, 200); };
  if ($('patClear')) $('patClear').onclick = () => { Object.assign(P, { view: 'both', sector: '', region: '', country: '', fyFrom: '', fyTo: '', q: '' }); upd(); };
}

function renderPatterns() {
  const P = state.pat; const R = P.result;
  renderPatFilters();
  if (!R) {
    $('patBody').innerHTML = `<div class="card empty"><h3>${t('pt.emptyH', 'No pattern analysis yet')}</h3><p class="muted">${t('pt.emptyP', 'Pattern analysis reads every validated approach in the database at once, finds the same approach in different projects and labels each repeat as replication (another country) or scaling (same country).')}</p><button class="btn primary" onclick="runPatterns()">▶ ${t('pt.runV', 'Run')} ${esc(P.wf || '')}</button></div>`;
    return;
  }
  if (!R.events) {
    $('patBody').innerHTML = `<div class="note">${t('pt.old', 'This result was produced by an earlier workflow version with a different method.')} ${esc(R.workflow)} · <a href="#" onclick="runPatterns();return false">${t('pt.rerun', 'Run the current workflow')} (${esc(P.wf)})</a></div>`;
    return;
  }
  const k = R.kpis; const M = R.method;
  const unverified = M.basis !== 'verified';
  const staleBar = R.stale ? `<div class="warnbar">↻ ${t('pt.stale', 'The database changed after this analysis (new extraction runs or manual edits). Run it again to include them.')} <button class="btn sm" onclick="runPatterns()">▶ ${t('pt.runV', 'Run')} ${esc(P.wf || '')}</button></div>` : '';
  $('patBody').innerHTML = `
    ${staleBar}${unverified ? `<div class="warnbar">⚠ ${M.basis === 'rules' ? t('pt.rules', 'The model did not run (no API key for the selected provider, or the provider is mock), so the results below come from <b>rules only</b>: explicit project references and cue language for replication, similarity above the rule threshold for scaling. Set the key in Setup and re-run for model judgements.') : t('pt.unv', 'Verification has not run (no API key), so the groups below are <b>unverified semantic candidates</b>. Set the API key in Setup and re-run to verify them in context.')}</div>` : ''}
    <div class="funnel">
      ${fstage('1', k.approaches, t('pt.f1', 'validated approaches'), t('pt.f1s', 'theme + original text'))}
      <div class="farrow">→</div>
      ${fstage('2', k.candidate_pairs, t('pt.f2', 'candidate pairs'), `${t('pt.f2s', 'semantic match')} ≥ ${M.threshold} · ${esc(M.backend)}`)}
      <div class="farrow">→</div>
      ${M.columns
        ? fstage('3', unverified ? '—' : k.judged, t('pt.f3c', 'approaches judged by the model'), unverified ? t('pt.f3n', 'not run') : `${k.verified_pairs} ${t('pt.f3cs', 'same-approach links verified')} · ${k.rejected_pairs} ${t('pt.rejected', 'rejected')}`, unverified)
        : fstage('3', unverified ? '—' : k.verified_pairs, t('pt.f3', 'verified same approach'), unverified ? t('pt.f3n', 'not run') : `${t('pt.f3s', 'read ±2 pages')} · ${k.rejected_pairs} ${t('pt.rejected', 'rejected')}`, unverified)}
      <div class="farrow">→</div>
      <div class="fsplit">
        ${M.columns
          ? fstage('4a', k.replication_events, t('pt.rep', 'Replication'), `${k.replication_confirmed} ${t('pt.confirmed', 'confirmed')} · ${k.replication_likely} ${t('pt.likely', 'likely')} · ${k.replication_source_in_portfolio} ${t('pt.srcIn', 'source in portfolio')}`, false, C_REP)
          : fstage('4a', k.replication_events, t('pt.rep', 'Replication'), t('pt.repS', 'same approach, different country'), false, C_REP)}
        ${M.columns
          ? fstage('4b', k.scaling_events, t('pt.scale', 'Scaling'), t('pt.scaleS3', 'same approach earlier · same country + sector'), false, C_SCALE)
          : fstage('4b', k.scaling_events, t('pt.scale', 'Scaling'), t('pt.scaleS', 'same approach, same country'), false, C_SCALE)}
      </div>
      <a href="#" class="fhow" id="patWfLink">${t('pt.how', 'Method & code →')}</a>
    </div>
    <div class="muted runmeta">${esc(R.workflow_tag || (R.manifest || {}).workflow_tag || R.workflow)} · ${esc(R.workflow_hash)} · ${esc(((R.manifest || {}).created_at || '').replace('T', ' ').slice(0, 16))}</div>
    <div id="patMain"></div>`;
  $('patWfLink').onclick = (e) => { e.preventDefault(); openCode('pattern', R.workflow, { type: 'file', id: 'workflow.html' }, 'patterns'); };
  renderPatMain();
}
function fstage(n, v, l, s, muted, color) {
  return `<div class="fstage ${muted ? 'muted' : ''}" ${color ? `style="border-top:3px solid ${color}"` : ''}><div class="fsn">${n}</div><div class="fsv">${v}</div><div class="fsl">${l}</div><div class="fss">${s}</div></div>`;
}

function renderPatMain() {
  const P = state.pat; const R = P.result; const { pats, events } = patView();
  const nRep = events.filter((e) => e.type === 'replication').length, nSc = events.filter((e) => e.type === 'scaling').length;
  const act = patActive();
  const fTag = act ? `<span class="ftag">${t('pt.filtered', 'filtered')}</span>` : '';
  // ---- aggregates recomputed from the filtered events (so every table follows the filter row)
  const base = Object.fromEntries(R.by_sector.map((x) => [x.sector, x]));
  const secAgg = {};
  const addS = (k) => (secAgg[k] = secAgg[k] || { sector: k, replication: 0, scaling: 0, pats: {} });
  events.forEach((e) => { const x = addS(e.sector); x[e.type]++; x.pats[e.pattern_id] = (x.pats[e.pattern_id] || 0) + 1; });
  pats.forEach((p) => p.members.filter(memberOk).forEach((m) => { const x = addS(m.major_sector); x.pats[p.pattern_id] = x.pats[p.pattern_id] || 0; }));
  const label = Object.fromEntries(R.patterns.map((p) => [p.pattern_id, p.label]));
  const bySector = Object.values(secAgg).map((x) => ({ ...x, approaches: (base[x.sector] || {}).approaches || 0, in_pattern: (base[x.sector] || {}).in_pattern || 0, share_in_pattern: (base[x.sector] || {}).share_in_pattern || 0,
    top_patterns: Object.entries(x.pats).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, n]) => ({ pattern_id: k, label: label[k], n })) }))
    .sort((a, b) => (b.replication + b.scaling) - (a.replication + a.scaling));
  const ctyAgg = {};
  const addC = (k) => (ctyAgg[k] = ctyAgg[k] || { country: k, originated: 0, received: 0, scaled: 0 });
  events.forEach((e) => { if (e.type === 'replication') { addC(e.origin_country).originated++; addC(e.country).received++; } else addC(e.country).scaled++; });
  const byCountry = Object.values(ctyAgg).filter((c) => c.country).sort((a, b) => (b.originated + b.received + b.scaled) - (a.originated + a.received + a.scaled));
  // ---- key findings (auto text for the story)
  const top = pats[0];
  const secRows = bySector;
  const topSecRep = [...secRows].sort((a, b) => b.replication - a.replication)[0];
  const topSecSc = [...secRows].sort((a, b) => b.scaling - a.scaling)[0];
  const ctyO = [...byCountry].sort((a, b) => b.originated - a.originated)[0];
  const scope = [P.sector, P.region, P.country, P.fyFrom || P.fyTo ? `${fyl(P.fyFrom) === '—' ? '…' : fyl(P.fyFrom)}–${fyl(P.fyTo) === '—' ? '…' : fyl(P.fyTo)}` : '', P.q ? `“${P.q}”` : ''].filter(Boolean).join(' · ');
  const findings = [
    `${scope ? `<b>${esc(scope)}</b>: ` : ''}${pats.length} ${t('pt.kf1', 'approaches were used in more than one project')} — ${nRep} ${t('pt.kf1r', 'replications to another country and')} ${nSc} ${t('pt.kf1s', 'scaling steps within the same country.')}`,
    top ? `${t('pt.kf2', 'Most repeated')}: <b>${esc(top.label)}</b> — ${top.n_projects} ${t('pt.projects', 'projects')}, ${top.n_countries} ${t('pt.countries', 'countries')} (${esc(top.countries.slice(0, 4).join(' → '))}${top.countries.length > 4 ? ' …' : ''}), ${fyl(top.first_fy)}–${fyl(top.last_fy)}.` : '',
    !P.sector && topSecRep && topSecRep.replication ? `${t('pt.kf3', 'Sector with most replication')}: <b>${esc(topSecRep.sector)}</b> (${topSecRep.replication})${topSecSc && topSecSc.scaling ? `; ${t('pt.kf3s', 'most scaling')}: <b>${esc(topSecSc.sector)}</b> (${topSecSc.scaling})` : ''}.` : '',
    !P.country && ctyO && ctyO.originated ? `${t('pt.kf4', 'Leading origin country')}: <b>${esc(ctyO.country)}</b> — ${ctyO.originated} ${t('pt.kf4s', 'later adoptions elsewhere started from its projects.')}` : '',
  ].filter(Boolean);

  // ---- ① most repeated approaches
  const LIMIT = 12; const shown = P.showAll || pats.length <= LIMIT + 3 ? pats : pats.slice(0, LIMIT);
  const maxN = Math.max(2, ...R.patterns.map((p) => p.n_projects));
  const rows = shown.map((p) => {
    const open = P.open === p.pattern_id; const w = (n) => (n / maxN) * 100;
    return `<div class="prow2 ${open ? 'open' : ''}" data-pid="${p.pattern_id}">
      <div class="plab"><span class="pidtag">${p.pattern_id}</span><span class="pname" title="${esc(p.label)}">${esc(p.label)}</span></div>
      <div class="pbarw" title="${p.n_projects} projects: 1 origin · ${p.replication} replication · ${p.scaling} scaling">
        <span class="pbar1" style="width:${w(1)}%;background:${C_ORIGIN}"></span>${p.replication ? `<span class="pbar1" style="width:${w(p.replication)}%;background:${C_REP}"></span>` : ''}${p.scaling ? `<span class="pbar1" style="width:${w(p.scaling)}%;background:${C_SCALE}"></span>` : ''}
        <span class="pval">${p.n_projects}</span></div>
      <div class="ppath">${p.members.map((m) => `<span class="pc ${m.role}" title="${esc(m.project_id)} · ${fyl(m.fy)} · ${m.role}">${esc(m.country.length > 18 ? m.country.slice(0, 17) + '…' : m.country)}</span>`).join('<span class="pa">›</span>')}
        <div class="muted" style="font-size:11px;margin-top:2px">${fyl(p.first_fy)}→${fyl(p.last_fy)} · ${esc(p.sectors.slice(0, 2).join(' · '))}</div></div>
    </div>${open ? patDetail(p) : ''}`;
  }).join('') || `<div class="muted" style="padding:14px">${t('pt.none', 'No repeated approach matches these filters.')}</div>`;

  // ---- ② by sector
  const maxS = Math.max(1, ...bySector.map((s) => Math.max(s.replication, s.scaling)));
  const sec = bySector.map((s) => `<tr class="srow ${P.sector === s.sector ? 'sel' : ''}" data-sec="${esc(s.sector)}">
      <td><b>${esc(s.sector)}</b><div class="muted" style="font-size:11px">${s.in_pattern} / ${s.approaches} ${t('pt.inGroups', 'approaches in a repeated group')} (${pct(s.share_in_pattern)})${act ? ' · ' + t('pt.allData', 'all data') : ''}</div></td>
      <td><div class="mbar"><span style="width:${(s.replication / maxS) * 78}%;background:${C_REP}"></span><b>${s.replication}</b></div></td>
      <td><div class="mbar"><span style="width:${(s.scaling / maxS) * 78}%;background:${C_SCALE}"></span><b>${s.scaling}</b></div></td>
      <td>${s.top_patterns.slice(0, 3).map((x) => `<span class="schip" title="${esc(x.label)}">${x.pattern_id} ${esc(x.label.length > 30 ? x.label.slice(0, 30) + '…' : x.label)}</span>`).join('') || '<span class="muted">—</span>'}</td></tr>`).join('');

  // ---- ③ over time
  const evFy = {}; events.forEach((e) => { if (!e.fy) return; const x = (evFy[e.fy] = evFy[e.fy] || { replication: 0, scaling: 0 }); x[e.type]++; });
  const fy = R.by_fy.filter((x) => x.fy && (!P.fyFrom || x.fy >= Number(P.fyFrom)) && (!P.fyTo || x.fy <= Number(P.fyTo)))
    .map((x) => act ? { fy: x.fy, first_use: 0, replication: (evFy[x.fy] || {}).replication || 0, scaling: (evFy[x.fy] || {}).scaling || 0, approaches: ((evFy[x.fy] || {}).replication || 0) + ((evFy[x.fy] || {}).scaling || 0) } : x);
  const maxF = Math.max(1, ...fy.map((x) => x.approaches));
  const fyBars = fy.map((x) => {
    const r = P.view === 'scaling' ? 0 : x.replication, s = P.view === 'replication' ? 0 : x.scaling;
    return `<div class="fycol" title="${fyl(x.fy)}: ${x.first_use} first use · ${x.replication} replication · ${x.scaling} scaling">
      <div class="fystack" style="height:${(x.approaches / maxF) * 150}px">${s ? `<span style="height:${(s / (x.approaches || 1)) * 100}%;background:${C_SCALE}"></span>` : ''}${r ? `<span style="height:${(r / (x.approaches || 1)) * 100}%;background:${C_REP}"></span>` : ''}${x.first_use ? '<span style="flex:1;background:#c7d7fb"></span>' : ''}</div>
      <div class="fyv">${r + s ? `<b>${r + s}</b>/` : ''}${x.approaches}</div><div class="fyl">${fyl(x.fy)}</div></div>`;
  }).join('');

  // ---- ④ countries
  const ctys = byCountry.filter((c) => P.view === 'both' || (P.view === 'replication' ? c.originated + c.received : c.scaled)).slice(0, 14);
  const cty = ctys.map((c) => `<tr><td>${esc(c.country)}</td><td class="num">${c.originated || '<span class="muted">0</span>'}</td><td class="num">${c.received || '<span class="muted">0</span>'}</td><td class="num">${c.scaled || '<span class="muted">0</span>'}</td></tr>`).join('');

  const colTable = R.approaches ? renderPatColumns() : '';
  $('patMain').innerHTML = `
    ${colTable}
    <div class="card findings"><h3>${t('pt.kf', 'Key findings')} <span class="muted" style="font-weight:400;font-size:12px">${t('pt.kfH', 'generated from the current filters')}</span></h3><ul>${findings.map((f) => `<li>${f}</li>`).join('')}</ul></div>
    <div class="card">
      <div class="toolbar"><h3 style="margin:0">① ${t('pt.s1', 'Which approaches were repeated most?')} ${fTag}</h3><span class="right"></span>
        <span class="lgd"><i style="background:${C_ORIGIN}"></i>${t('pt.origin', 'origin')}</span><span class="lgd"><i style="background:${C_REP}"></i>${t('pt.rep', 'Replication')}</span><span class="lgd"><i style="background:${C_SCALE}"></i>${t('pt.scale', 'Scaling')}</span></div>
      <div class="muted" style="font-size:12px;margin:4px 0 8px">${t('pt.s1h', 'Bar = projects using the approach. Country path in approval order. Click a row for the evidence and the verification of each link.')}</div>
      <div class="plist2">${rows}</div>
      ${shown.length < pats.length ? `<div style="margin-top:8px"><button class="btn sm" id="patMore">${t('pt.showAll', 'Show all')} ${pats.length}</button></div>` : ''}
    </div>
    <div class="card"><h3>② ${t('pt.s2', 'By sector')} ${fTag}</h3>
      <div class="muted" style="font-size:12px;margin-bottom:8px">${t('pt.s2h', 'Counted at the sector of the project that repeats the approach. Click a sector to filter the page.')}</div>
      <table class="stable"><thead><tr><th>${t('pt.sector', 'Sector')}</th><th style="width:20%">${t('pt.rep', 'Replication')}</th><th style="width:20%">${t('pt.scale', 'Scaling')}</th><th>${t('pt.top', 'Most repeated approaches')}</th></tr></thead><tbody>${sec}</tbody></table></div>
    <div class="grid2">
      <div class="card"><h3>③ ${t('pt.s3', 'Over time')} ${fTag}</h3>
        <div class="muted" style="font-size:12px;margin-bottom:8px">${act ? t('pt.s3hf', 'Replication and scaling events in the current filter, by approval year.') : t('pt.s3h', 'Approaches by approval year of the adopting project.')} <span class="lgd"><i style="background:#c7d7fb"></i>${t('pt.first', 'first use')}</span><span class="lgd"><i style="background:${C_REP}"></i>${t('pt.rep', 'Replication')}</span><span class="lgd"><i style="background:${C_SCALE}"></i>${t('pt.scale', 'Scaling')}</span></div>
        <div class="fychart">${fyBars}</div>
        <details style="margin-top:8px"><summary class="muted" style="font-size:12px;cursor:pointer">${t('pt.table', 'Show as table')}</summary><table><tr><th>FY</th><th class="num">${t('pt.first', 'first use')}</th><th class="num">${t('pt.rep', 'Replication')}</th><th class="num">${t('pt.scale', 'Scaling')}</th></tr>${fy.map((x) => `<tr><td>${fyl(x.fy)}</td><td class="num">${x.first_use}</td><td class="num">${x.replication}</td><td class="num">${x.scaling}</td></tr>`).join('')}</table></details></div>
      <div class="card"><h3>④ ${t('pt.s4', 'Countries')} ${fTag}</h3>
        <div class="muted" style="font-size:12px;margin-bottom:8px">${t('pt.s4h', 'Origin = its projects started approaches later replicated elsewhere; received = it adopted an approach first seen in another country; scaled = it repeated an approach within the country.')}</div>
        <table><thead><tr><th>${t('pt.country', 'Country')}</th><th class="num">${t('pt.originated', 'origin')}</th><th class="num">${t('pt.received', 'received')}</th><th class="num">${t('pt.scaled', 'scaled')}</th></tr></thead><tbody>${cty || '<tr><td colspan="4" class="muted">—</td></tr>'}</tbody></table></div>
    </div>
    <div class="card" id="patPairs"></div>`;
  if ($('patMore')) $('patMore').onclick = () => { P.showAll = true; renderPatMain(); };
  if ($('patColAll')) $('patColAll').onclick = () => { P.colAll = !P.colAll; renderPatMain(); };
  $('patMain').querySelectorAll('.prow2').forEach((r) => r.addEventListener('click', () => { P.open = P.open === r.dataset.pid ? null : r.dataset.pid; renderPatMain(); }));
  $('patMain').querySelectorAll('.srow').forEach((r) => r.addEventListener('click', () => { P.sector = P.sector === r.dataset.sec ? '' : r.dataset.sec; P.open = null; P.pairPage = 0; renderPatFilters(); renderPatMain(); $('patMain').scrollIntoView({ behavior: 'smooth' }); }));
  bindOpenProject($('patMain'));
  renderPairs();
}
// ---- ⓪ approach table: one row per approach with the two columns (r3+)
function renderPatColumns() {
  const P = state.pat; const R = P.result; const q = P.q.trim().toLowerCase();
  const rows = R.approaches.filter((a) => memberOk({ major_sector: a.sector, region_short: a.region, country: a.country, fy: a.fy })
    && (P.view === 'both' || (P.view === 'replication' ? a.replication : a.scaling))
    && (!q || `${a.approach} ${a.project_id} ${a.replication_source_project} ${a.scaling_source_project}`.toLowerCase().includes(q)));
  const flagged = rows.filter((a) => a.replication || a.scaling);
  const list = P.colAll ? rows : flagged;
  const lvl = (a) => a.replication ? `<span class="pill ${a.replication === 'confirmed' ? 'p-warn' : 'p-muted'}" title="${esc(a.replication_reason || '')}">${a.replication === 'confirmed' ? t('pt.confirmed', 'confirmed') : t('pt.likely', 'likely')}</span>` : '<span class="muted">—</span>';
  const src = (pid, name, cty, inP) => pid ? `${inP === false || inP === 'False' ? `<span class="mono">${esc(pid)}</span>` : `<a href="#" data-open="${esc(pid)}">${esc(pid)}</a>`}${name ? ` <span class="muted">${esc(name.length > 40 ? name.slice(0, 39) + '…' : name)}</span>` : ''}${cty ? ` <span class="muted">· ${esc(cty)}</span>` : ''}` : '';
  const tr = list.map((a) => `<tr>
      <td><a href="#" data-open="${a.project_id}">${a.project_id}</a> <span class="muted">${esc(a.country)} · ${fyl(a.fy)}</span><div>${esc(a.approach)}</div><div class="muted" style="font-size:11px">${esc(a.sector)}</div></td>
      <td>${lvl(a)}${a.replication ? `<div style="margin-top:3px">${src(a.replication_source_project, a.replication_source_name, a.replication_source_country, a.replication_source_in_portfolio) || `<span class="muted">${esc(a.replication_source_text || t('pt.srcNone', 'source not identified'))}</span>`}</div>` : ''}${a.replication_quote ? `<div class="muted" style="font-size:11px;margin-top:3px">“${esc(a.replication_quote.length > 200 ? a.replication_quote.slice(0, 200) + '…' : a.replication_quote)}”</div>` : ''}</td>
      <td>${a.scaling ? `<span class="pill p-ok">${t('pt.scale', 'Scaling')}</span><div style="margin-top:3px">${src(a.scaling_source_project, a.scaling_source_name, '', true)}${a.scaling_confidence != null ? ` <span class="muted">· ${t('pt.conf2', 'confidence')} ${a.scaling_confidence}</span>` : ''}</div>` : '<span class="muted">—</span>'}</td>
    </tr>`).join('') || `<tr><td colspan="3" class="muted">${t('pt.none', 'No repeated approach matches these filters.')}</td></tr>`;
  return `<div class="card"><div class="toolbar"><h3 style="margin:0">⓪ ${t('pt.s0', 'Replication and scaling per approach')} ${patActive() ? `<span class="ftag">${t('pt.filtered', 'filtered')}</span>` : ''}</h3><span class="right"></span>
      <span class="muted" style="font-size:12px">${flagged.length} / ${rows.length} ${t('pt.s0n', 'approaches flagged')}</span>
      <button class="btn sm" id="patColAll">${P.colAll ? t('pt.s0flag', 'Flagged only') : t('pt.s0all', 'Show all approaches')}</button></div>
    <div class="muted" style="font-size:12px;margin:4px 0 8px">${t('pt.s0h', 'Replication: confirmed = the passages state the project replicated / learned from an earlier project (source named or identifiable); likely = earlier experience mentioned without a name, and the same approach exists in an earlier project of another country. Scaling: the same approach was verified in an earlier project of the same country and sector. Hover a level for the model\'s reason.')}</div>
    <table class="pairt"><thead><tr><th style="width:38%">${t('pt.approach', 'Approach')}</th><th style="width:34%">${t('pt.rep', 'Replication')}</th><th>${t('pt.scale', 'Scaling')}</th></tr></thead><tbody>${tr}</tbody></table></div>`;
}
function bindOpenProject(root) { root.querySelectorAll('[data-open]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); go('database'); openDrawer(a.dataset.open); })); }
function patDetail(p) {
  const ROLE = { origin: ['p-info', t('pt.origin', 'origin')], replication: ['p-warn', t('pt.rep', 'Replication')], scaling: ['p-ok', t('pt.scale', 'Scaling')], same: ['p-muted', t('pt.sameOnly', 'same approach, no link type')] };
  return `<div class="pdetail"><div class="muted" style="font-size:12px;margin-bottom:6px">${t('pt.themes', 'Themes')}: ${esc(p.themes.join('; ') || '—')}${p.mean_confidence != null ? ` · ${t('pt.conf', 'mean verification confidence')}: <b>${p.mean_confidence}</b>` : ''}</div>
    <div class="tline">${p.members.map((m) => `<div class="tl-item ${m.role}"><div class="tl-dot" style="background:${m.role === 'origin' ? C_ORIGIN : m.role === 'replication' ? C_REP : m.role === 'scaling' ? C_SCALE : '#9ca3af'}"></div>
      <div class="tl-head"><b>${fyl(m.fy)}</b> · <a href="#" data-open="${m.project_id}">${m.project_id}</a> · ${esc(m.country)} <span class="muted">· ${esc(m.major_sector)}</span> <span class="pill ${ROLE[m.role][0]}">${ROLE[m.role][1]}</span></div>
      <div class="tl-name">${esc(m.name)}</div>
      <div class="tl-ev">“${esc(m.evidence.length > 260 ? m.evidence.slice(0, 260) + '…' : m.evidence)}” <span class="muted">${esc(m.evidence_doc)}</span></div></div>`).join('')}</div>
    <div class="plinks"><b style="font-size:12px">${t('pt.links', 'Links behind this group')}</b>${p.links.map((l) => `<div class="plink"><span class="pill ${l.status === 'verified' ? 'p-ok' : l.status === 'rejected' ? 'p-bad' : 'p-muted'}">${l.status}</span>
      <span class="mono">${l.project_a}</span> ↔ <span class="mono">${l.project_b}</span> · ${l.relation === 'scaling' ? t('pt.scale', 'Scaling') : t('pt.rep', 'Replication')} · ${t('pt.score', 'score')} ${l.score}${l.confidence != null ? ` · ${t('pt.conf2', 'confidence')} ${l.confidence}` : ''}${l.reason ? `<div class="muted" style="font-size:12px">${esc(l.reason)}</div>` : ''}</div>`).join('')}</div></div>`;
}
function renderPairs() {
  const P = state.pat; const R = P.result;
  const { pairs } = patView();
  const counts = { verified: 0, rejected: 0, candidate: 0, error: 0 }; pairs.forEach((p) => { counts[p.status] = (counts[p.status] || 0) + 1; });
  if (!counts[P.pairTab]) P.pairTab = ['verified', 'candidate', 'rejected', 'error'].find((x) => counts[x]) || 'verified';
  const list = pairs.filter((p) => p.status === P.pairTab); const PER = 25; const pages = Math.max(1, Math.ceil(list.length / PER)); P.pairPage = Math.min(P.pairPage, pages - 1);
  const tab = (k, l) => `<button class="${P.pairTab === k ? 'active' : ''}" data-ptab="${k}">${l} <span class="pill p-muted">${counts[k] || 0}</span></button>`;
  $('patPairs').innerHTML = `<h3>⑤ ${t('pt.s5', 'Verification log')} ${patActive() ? `<span class="ftag">${t('pt.filtered', 'filtered')}</span>` : ''} <span class="muted" style="font-weight:400;font-size:12px">${t('pt.s5h', 'every candidate pair, its semantic score and the model verdict after reading the context')}</span></h3>
    <div class="tabs">${tab('verified', t('pt.verified', 'verified'))}${tab('rejected', t('pt.rejected', 'rejected'))}${tab('candidate', t('pt.unverifiedT', 'unverified'))}${counts.error ? tab('error', 'error') : ''}</div>
    <table class="pairt"><thead><tr><th>${t('pt.approachA', 'Approach A')}</th><th>${t('pt.approachB', 'Approach B')}</th><th>${t('pt.relation', 'Relation')}</th><th class="num">${t('pt.score', 'score')}</th><th class="num">${t('pt.conf2', 'confidence')}</th><th>${t('pt.reason', 'Reason')}</th></tr></thead><tbody>
    ${list.slice(P.pairPage * PER, (P.pairPage + 1) * PER).map((p) => `<tr><td><a href="#" data-open="${p.project_a}">${p.project_a}</a> <span class="muted">${esc(p.country_a)}</span><div>${esc(p.name_a)}</div></td>
      <td><a href="#" data-open="${p.project_b}">${p.project_b}</a> <span class="muted">${esc(p.country_b)}</span><div>${esc(p.name_b)}</div></td>
      <td><span class="pill" style="background:${p.relation === 'scaling' ? '#d1fae5' : '#fef3c7'};color:${p.relation === 'scaling' ? '#065f46' : '#92400e'}">${p.relation === 'scaling' ? t('pt.scale', 'Scaling') : t('pt.rep', 'Replication')}</span>${(p.reference_match || []).length ? `<div class="muted" style="font-size:11px;margin-top:3px">${t('pt.same', 'same')} ${p.reference_match.join(', ')}</div>` : ''}</td>
      <td class="num">${p.score}</td><td class="num">${p.confidence ?? '—'}</td><td style="font-size:12px">${p.shared_solution ? `<b>${esc(p.shared_solution)}</b> · ` : ''}${esc(p.reason || '')}</td></tr>`).join('') || `<tr><td colspan="6" class="muted">—</td></tr>`}</tbody></table>
    ${pages > 1 ? `<div class="toolbar" style="margin-top:8px"><button class="btn sm" id="ppPrev" ${P.pairPage === 0 ? 'disabled' : ''}>←</button><span class="muted" style="font-size:12px">${P.pairPage + 1} / ${pages}</span><button class="btn sm" id="ppNext" ${P.pairPage >= pages - 1 ? 'disabled' : ''}>→</button></div>` : ''}`;
  $('patPairs').querySelectorAll('[data-ptab]').forEach((b) => b.addEventListener('click', () => { P.pairTab = b.dataset.ptab; P.pairPage = 0; renderPairs(); }));
  if ($('ppPrev')) { $('ppPrev').onclick = () => { P.pairPage--; renderPairs(); }; $('ppNext').onclick = () => { P.pairPage++; renderPairs(); }; }
  bindOpenProject($('patPairs'));
}

// ---------------------------------------------------------------- setup
async function loadSetup() {
  const s = await api.get('/api/setup'); state.setup = s;
  $('sRaw').value = s.raw_dir || ''; $('sOut').value = s.output_dir || ''; $('sProvider').value = s.provider || 'anthropic'; $('sModel').value = s.model || '';
  $('sBaseUrl').value = s.base_url || '';
  const hints = s.api_key_hint || {}; const hint = hints[s.provider];
  $('sKey').placeholder = hint ? `${hint} (set)` : 'not set — paste key here or add it to .env';
  $('sTestInfo').textContent = '';
  const sv = s.saving || {};
  $('sWarm').checked = sv.warm_cache !== false; $('sReuse').checked = !!sv.reuse_answers;
  $('sCodesModel').value = sv.codes_model || ''; $('sMergeModel').value = sv.merge_model || '';
  $('sPeakInfo').textContent = sv.deepseek_note || '';
  $('sProvider').onchange = () => { const h = hints[$('sProvider').value]; $('sKey').placeholder = h ? `${h} (set)` : 'not set — paste key here'; $('sModel').value = ''; $('sCodesModel').value = ''; $('sMergeModel').value = ''; $('sBaseUrl').value = $('sProvider').value === 'deepseek' ? 'https://api.deepseek.com' : ''; };
  $('sCsvInfo').innerHTML = `${s.projects_csv.rows} rows · ${s.projects_csv.unique_ids} unique IDs${s.projects_csv.duplicate_ids.length ? ` · <span class="pill p-warn">duplicates: ${s.projects_csv.duplicate_ids.join(', ')}</span>` : ''}${s.projects_csv.malformed_ids.length ? ` · <span class="pill p-bad">malformed: ${s.projects_csv.malformed_ids.length}</span>` : ''}`;
  $('sDocInfo').innerHTML = `${s.documents.documents} files · ${s.documents.projects} projects · ${Object.entries(s.documents.by_type).map(([k, v]) => k + ' ' + v).join(' · ')}<br><span class="mono">${(s.documents_dirs || []).join('<br>')}</span>`;
}
async function saveSetup() {
  const body = { raw_dir: $('sRaw').value, output_dir: $('sOut').value, provider: $('sProvider').value, model: $('sModel').value || null,
    api_key: $('sKey').value || null, base_url: $('sBaseUrl').value || null,
    warm_cache: $('sWarm').checked, reuse_answers: $('sReuse').checked,
    codes_model: $('sCodesModel').value.trim(), merge_model: $('sMergeModel').value.trim() };
  await api.post('/api/setup', body); $('sKey').value = ''; await loadSetup();
  if ($('sSaveInfo')) $('sSaveInfo').textContent = 'Saved ' + new Date().toLocaleTimeString() + '. Projects and documents were not reindexed.';
}
async function testLlm() {
  $('sTestInfo').textContent = 'testing…';
  await saveSetup();
  const r = await api.post('/api/setup/test', {});
  $('sTestInfo').innerHTML = r.ok ? `<span class="pill p-ok">OK</span> ${esc(r.provider)} · ${esc(r.model)} · ${r.tokens.input_tokens + r.tokens.cached_tokens} in / ${r.tokens.output_tokens} out tokens`
    : `<span class="pill p-bad">failed</span> ${esc(r.error)}`;
}
// Database -> Export: download one Excel (tabs Projects + Approaches) straight to the browser
async function doExport(scope) {
  const q = scope === 'rejected' ? 'scope=all&rejected=1' : `scope=${scope}`;
  const info = $('exportInfo'); info.style.display = 'block'; info.innerHTML = '⏳ Preparing the Excel file…';
  try {
    const r = await fetch(`/api/download/database.xlsx?${q}`); if (!r.ok) throw new Error(await r.text());
    const blob = await r.blob(); const cd = r.headers.get('Content-Disposition') || ''; const name = (cd.match(/filename="([^"]+)"/) || [])[1] || 'PIA_database.xlsx';
    const meta = JSON.parse(r.headers.get('X-PIA-Info') || '{}');
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 5000);
    info.innerHTML = `✔ Downloaded <b>${esc(name)}</b> · tab Projects: ${meta.projects} rows · tab Approaches: ${meta.approaches} rows (${meta.projects_with_approaches} projects) · a copy is in <span class="mono">output/exports/</span>`;
  } catch (e) { info.innerHTML = `<span style="color:var(--bad)">Export failed: ${esc(e.message)}</span>`; }
}
async function doExportOld(scope) { const m = await api.post('/api/export', { scope, label: scope }); $('exportInfo').style.display = 'block'; $('exportInfo').innerHTML = `✔ Exported ${m.projects} projects · ${m.approaches} approaches → <span class="mono">${esc(m.folder)}</span>`; }

// ---------------------------------------------------------------- setup: reviewer-curated approach examples
const EX_CATS = ['Operational', 'Technological', 'Financial', 'Collaborative'];
state.ex = { data: null, dirty: false };
async function loadExamples() {
  try { state.ex.data = await api.get('/api/examples'); } catch (e) { $('exInfo').innerHTML = `✖ ${esc(e.message)}${/Not Found/.test(e.message) ? ' — restart <code>piaa serve</code> to load this feature.' : ''}`; return; }
  state.ex.dirty = false; renderExamples();
}
function exRows(kind) {
  const rows = state.ex.data[kind];
  if (!rows.length) return `<div class="exempty">No ${kind} examples yet. Click “+ Add”.</div>`;
  return rows.map((r, i) => `<div class="exrow" data-k="${kind}" data-i="${i}"><div class="exn">${i + 1}</div><div>
      <textarea data-f="text" placeholder="${kind === 'good' ? 'Passage that describes an approach, e.g. “The project will deploy satellite-based crop monitoring to target insurance payouts.”' : 'Passage that looks related but is NOT an approach'}">${esc(r.text)}</textarea>
      <div class="exmeta"><select data-f="category" title="${kind === 'good' ? 'Category' : 'Category it could be confused with (optional)'}"><option value="">${kind === 'good' ? '— category —' : '— looks like —'}</option>${EX_CATS.map((c) => `<option ${c === r.category ? 'selected' : ''}>${c}</option>`).join('')}</select>
        <input type="text" data-f="note" value="${esc(r.note)}" placeholder="${kind === 'good' ? 'why it is a good example (optional)' : 'why it is NOT an approach'}">
        <input type="text" data-f="project_id" value="${esc(r.project_id)}" placeholder="Project ID"></div></div>
      <button class="exdel" title="Delete this example" data-del="1">✕</button></div>`).join('');
}
function renderExamples() {
  const d = state.ex.data;
  $('exEnabled').checked = d.enabled;
  $('exGood').innerHTML = exRows('good'); $('exBad').innerHTML = exRows('bad');
  renderExInfo();
  document.querySelectorAll('#exCard .exrow').forEach((row) => {
    const r = d[row.dataset.k][Number(row.dataset.i)];
    row.querySelectorAll('[data-f]').forEach((el) => el.addEventListener('input', () => { r[el.dataset.f] = el.value; markExDirty(row); }));
    row.querySelector('[data-del]').addEventListener('click', () => { d[row.dataset.k].splice(Number(row.dataset.i), 1); state.ex.dirty = true; renderExamples(); });
  });
}
function renderExInfo() {
  const d = state.ex.data;
  const status = state.ex.dirty ? '<b style="color:var(--warn)">Unsaved changes</b>' : (d.updated_at ? `Saved ${esc(d.updated_at.replace('T', ' ').slice(0, 16))} UTC` : 'Not saved yet');
  $('exInfo').innerHTML = `${status} · ${d.good.length} good / ${d.bad.length} bad · stored in <span class="mono">${esc(d.path)}</span>${d.fingerprint && !state.ex.dirty ? ` · set <span class="mono">${d.fingerprint}</span> (recorded in each run's trace)` : ''}<br>
    Added to the system prompt of the extraction steps (workflows v4 and later, up to 25 per side). Changing the examples changes extraction results: re-run projects to apply them.`;
  $('exPreview').textContent = previewExamples(d);
}
function markExDirty(row) { state.ex.dirty = true; if (row) row.classList.add('dirty'); renderExInfo(); }
function previewExamples(d) {
  if (!d.enabled) return '(examples are switched off: nothing is added to the prompt)';
  const g = d.good.filter((r) => r.text.trim()), b = d.bad.filter((r) => r.text.trim());
  if (!g.length && !b.length) return '(no examples: nothing is added to the prompt)';
  return ['## Reference examples from human reviewers', ...(g.length ? ['', '### GOOD examples - these ARE approaches', ...g.slice(0, 25).map((r, i) => `${i + 1}. [${r.category || 'category not given'}] "${r.text.trim()}"${r.note ? ' - ' + r.note : ''}`)] : []),
    ...(b.length ? ['', '### BAD examples - these are NOT approaches', ...b.slice(0, 25).map((r, i) => `${i + 1}. "${r.text.trim()}"${r.note ? ' - why not: ' + r.note : ''}`)] : [])].join('\n');
}
async function saveExamples() {
  const d = state.ex.data; if (!d) return;
  $('exSave').disabled = true;
  try { state.ex.data = await api.post('/api/examples', { enabled: $('exEnabled').checked, good: d.good, bad: d.bad }); state.ex.dirty = false; renderExamples(); toast('✔ Examples saved', 'ok'); }
  catch (e) { toast('✖ Could not save examples: ' + esc(e.message)); }
  finally { $('exSave').disabled = false; }
}

// ---------------------------------------------------------------- init
// ---------------------------------------------------------------- errors, build check, data source
function toast(msg, kind) {
  let box = $('toasts'); if (!box) { box = document.createElement('div'); box.id = 'toasts'; document.body.appendChild(box); }
  const el = document.createElement('div'); el.className = 'toast ' + (kind || 'err'); el.innerHTML = msg; box.appendChild(el);
  setTimeout(() => el.remove(), kind === 'ok' ? 4000 : 9000);
}
window.addEventListener('unhandledrejection', (e) => { const m = (e.reason && e.reason.message) || String(e.reason); toast(`⚠ ${esc(m.length > 300 ? m.slice(0, 300) + '…' : m)}`); });
// database update marker: badge on the Database tab until the tab is opened; changed rows marked once
const seenKey = () => 'pia_db_seen:' + ((state.server || {}).db || '');
function dbSeen() { try { return localStorage.getItem(seenKey()); } catch (e) { return null; } }
function setDbSeen(v) { try { localStorage.setItem(seenKey(), v || ''); } catch (e) { /* ignore */ } }
function updateDbBadge() {
  const v = state.server; if (!v) return;
  let seen = dbSeen();
  if (seen === null) { setDbSeen(v.db_marker); seen = v.db_marker; }          // first visit: nothing is "new"
  const isNew = !!v.db_marker && v.db_marker > seen;
  if (isNew && $('view-database').classList.contains('active')) { markDbSeen(); if (state.projects.length) renderTable(); return; }
  $('dbNew').style.display = isNew ? '' : 'none';
}
function markDbSeen() {
  const v = state.server; if (!v) return;
  const seen = dbSeen();
  if (v.db_marker && seen && v.db_marker > seen) state.newSince = seen;     // rows changed after this time get a "New" tag
  setDbSeen(v.db_marker); $('dbNew').style.display = 'none';
}
async function pollDbMarker() {
  try {
    const v = await api.get('/api/version'); const before = state.server && state.server.db_marker;
    state.server = v; updateDbBadge();
    if (before && v.db_marker !== before) {
      toast(`↻ ${t('bd.dbUpdated', 'The database was updated')} (${esc((v.db_marker || '').replace('T', ' ').slice(0, 16))})`, 'ok');
      if ($('view-database').classList.contains('active')) { state.newSince = before; setDbSeen(v.db_marker); $('dbNew').style.display = 'none'; loadProjects(); }
    }
  } catch (e) { /* server restarting */ }
  setTimeout(pollDbMarker, 30000);
}
async function checkServer() {
  let v = null;
  try { v = await api.get('/api/version'); } catch (e) { /* older server: endpoint missing */ }
  if (!v || (APP_BUILD && v.build !== APP_BUILD)) {
    $('buildBanner').innerHTML = `⚠ ${t('bd.old', 'The code was updated after the server started, so the server runs an older version. Restart it (R + Enter in the start window, or stop and start <code>piaa serve</code>), then reload.')} <span class="muted">${t('bd.page', 'page')} ${APP_BUILD} · ${t('bd.server', 'server')} ${v ? esc(v.build) : t('bd.unknown', 'older build')}</span>`;
    $('buildBanner').style.display = 'block';
  }
  if (v) {
    state.server = v;
    const out = v.output_dir.split(/[\\/]/).filter(Boolean).pop();
    $('dataSrc').innerHTML = `<b>${esc(out)}</b> · ${v.projects} ${t('pt.projects', 'projects')}<br>${t('bd.lastRun', 'last run')} ${esc((v.last_run || '—').replace('T', ' ').slice(0, 16))}<br>${t('bd.latest', 'latest workflow')} ${esc(v.latest_workflow || '—')}`;
    $('dataSrc').title = v.db;
    updateDbBadge();
    setTimeout(pollDbMarker, 30000);
  }
}

(async function init() {
  checkServer();
  api.get('/api/version').then((v) => { $('appVersion').textContent = `piaa ${v.package}` + (v.workflow_tag ? ` · workflow ${v.workflow_tag}` : ''); })
    .catch(() => { $('appVersion').textContent = 'piaa version: restart the app to show'; $('appVersion').title = 'The server is running older code than the files on disk. Stop it (Ctrl+C) and start it again.'; });
  $('q').addEventListener('input', renderTable);
  $('btnGroup').addEventListener('click', (e) => { e.stopPropagation(); togglePop('group', $('btnGroup')); });
  $('btnFields').addEventListener('click', (e) => { e.stopPropagation(); togglePop('fields', $('btnFields')); });
  $('dbPop').addEventListener('click', (e) => e.stopPropagation());
  $('btnExport').addEventListener('click', (e) => { e.stopPropagation(); $('exportMenu').classList.toggle('open'); });
  $('exportMenu').querySelectorAll('[data-x]').forEach((d) => d.addEventListener('click', () => { $('exportMenu').classList.remove('open'); doExport(d.dataset.x); }));
  document.addEventListener('click', () => { closePop(); $('exportMenu').classList.remove('open'); });
  $('btnTestLlm').addEventListener('click', testLlm);
  $('drawerBg').addEventListener('click', closeDrawer); $('dClose').addEventListener('click', closeDrawer);
  $('dPrev').addEventListener('click', () => stepDrawer(-1)); $('dNext').addEventListener('click', () => stepDrawer(1));
  $('modal').addEventListener('click', (e) => { if (e.target === $('modal')) closeHist(); }); $('histClose').addEventListener('click', closeHist);
  $('btnNewSession').addEventListener('click', () => { state.review.session = null; renderReview(); });
  $('btnStart').addEventListener('click', startSession); $('btnCancel').addEventListener('click', () => renderReview());
  $('hmQ').addEventListener('input', renderHeat);
  $('btnGenRemaining').addEventListener('click', () => { const byId = Object.fromEntries(state.projects.map((p) => [p.project_id, p])); const ids = state.review.ids.filter((i) => ['not run', 'failed'].includes((byId[i] || {}).review_status)); if (ids.length) runProjects(ids, state.review.session.workflow, 'refresh', true); });
  $('btnSaveSetup').addEventListener('click', saveSetup); $('btnReindex').addEventListener('click', async () => { const r = await api.post('/api/reindex'); await loadSetup(); loadProjects(); if ($('sSaveInfo')) $('sSaveInfo').textContent = `Reindexed ${new Date().toLocaleTimeString()}: ${r.projects} projects.`; });
  $('langToggle').addEventListener('click', toggleLang);
  $('exSave').addEventListener('click', saveExamples);
  $('exEnabled').addEventListener('change', () => { if (state.ex.data) { state.ex.data.enabled = $('exEnabled').checked; markExDirty(); } });
  document.querySelectorAll('[data-exadd]').forEach((b) => b.addEventListener('click', () => { if (!state.ex.data) return; state.ex.data[b.dataset.exadd].push({ text: '', category: '', note: '', project_id: '' }); state.ex.dirty = true; renderExamples(); const rows = document.querySelectorAll(`#ex${b.dataset.exadd === 'good' ? 'Good' : 'Bad'} textarea`); if (rows.length) rows[rows.length - 1].focus(); }));
  window.addEventListener('beforeunload', (e) => { if (state.ex.dirty) { e.preventDefault(); e.returnValue = ''; } });
  $('codeBack').addEventListener('click', (e) => { e.preventDefault(); go((state.code || {}).back || 'review'); });
  $('patRunBtn').addEventListener('click', runPatterns);
  $('patRun').addEventListener('change', () => loadPatterns($('patRun').value));
  $('patWfBtn').addEventListener('click', () => openCode('pattern', state.pat.wf || 'r1', null, 'patterns'));
  ['input', 'change'].forEach((ev) => { $('rIds').addEventListener(ev, updateSpotSummary); $('rDbFilter').addEventListener(ev, updateSpotSummary);
    $('rDbPick').addEventListener(ev, updateSpotSummary); $('rDbN').addEventListener(ev, updateSpotSummary); });
  $('rDbTest').addEventListener('click', () => { $('rDbPick').value = 'random'; $('rDbN').value = 10; updateSpotSummary(); });
  document.querySelectorAll('#rSeg button').forEach((b) => b.addEventListener('click', updateSpotSummary));
  document.addEventListener('keydown', (e) => { if (e.key === 'Enter' && e.target.classList && e.target.classList.contains('apname')) e.preventDefault(); }); // approach name stays one value
  const fitName = (el) => { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; };
  document.addEventListener('input', (e) => { if (e.target.classList && e.target.classList.contains('apname')) fitName(e.target); });
  new MutationObserver(() => document.querySelectorAll('textarea.apname:not([data-fit])').forEach((el) => { el.dataset.fit = 1; fitName(el); })).observe(document.body, { childList: true, subtree: true });
  applyLang();
  state.workflows = await api.get('/api/workflows');
  await loadProjects();
})();
