import { useEffect, useRef, useState } from 'react';
import { Clapperboard, Plus, PanelRightClose, PanelRightOpen, Sun, Moon, FolderOpen, Images, Settings2, ChevronRight, ArrowUp, Check, CircleHelp, FileText, WandSparkles, CheckCheck } from 'lucide-react';
import * as D from './domain.ts';
import type { Project, Settings, Stage, Store } from './domain.ts';
import { loadState, saveState, importAsset, listAssets, downloadJson } from './storage.ts';
import type { LocalAsset } from './storage.ts';
import { Button, Tag, Modal, Notice, BudgetStrip } from './components.tsx';
import { Workspace } from './Workspace.tsx';
import { Configuration, AssetLibrary, BudgetPanel } from './Panels.tsx';

export type Update = (fn: (p: Project, s: Settings) => void) => void;
export default function App() {
  const [store, setStore] = useState<Store>(loadState);
  const stateRef = useRef(store); stateRef.current = store;
  const [view, setView] = useState<'work' | 'assets' | 'settings' | 'projects'>('work');
  const [modal, setModal] = useState<'budget' | 'new' | 'repair' | 'help' | null>(null);
  const [toast, setToast] = useState('');
  const [assets, setAssets] = useState<LocalAsset[]>([]);
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [chat, setChat] = useState('');
  const [panelTab, setPanelTab] = useState<'chat' | 'files'>('chat');
  const [newName, setNewName] = useState('');
  const [newCategory, setNewCategory] = useState<Project['category']>('commerce');
  const [panelWidth, setPanelWidth] = useState(330);
  const [uploading, setUploading] = useState(false);
  const chatEnd = useRef<HTMLDivElement>(null);
  const mainArea = useRef<HTMLElement>(null);
  const p = store.projects.find(p => p.id === store.activeId) || store.projects[0];
  const missing = D.readiness(store.settings);
  useEffect(() => { if (mainArea.current) mainArea.current.scrollTop = 0; }, [p.id, p.stage, view]);
  const imageAsset = assets.find(a => p.assetIds.includes(a.id) && a.mime.startsWith('image/'));
  const imageUrl = imageAsset ? urls[imageAsset.id] : undefined;

  function notify(message: string) { setToast(message); }
  function commit(fn: (s: Store) => void): boolean {
    try { const next = structuredClone(stateRef.current); fn(next); stateRef.current = next; setStore(next); return true; }
    catch (e) { notify(e instanceof Error ? e.message : '这一步没有完成，请重试。'); return false; }
  }
  const update: Update = fn => { commit(s => fn(s.projects.find(x => x.id === s.activeId)!, s.settings)); };
  useEffect(() => { document.documentElement.dataset.theme = store.theme; try { saveState(store); } catch { notify('浏览器存储空间不足，当前更改尚未保存。请先导出项目。'); } }, [store]);
  useEffect(() => { if (toast) { const timer = setTimeout(() => setToast(''), 5000); return () => clearTimeout(timer); } }, [toast]);
  useEffect(() => { listAssets().then(setAssets).catch(() => notify('本地素材存储无法打开。请使用正常浏览器窗口。')); }, []);
  useEffect(() => { const next = Object.fromEntries(assets.map(a => [a.id, URL.createObjectURL(a.blob)])); setUrls(next); return () => Object.values(next).forEach(URL.revokeObjectURL); }, [assets]);
  useEffect(() => { const node = chatEnd.current; if (node?.parentElement) node.parentElement.scrollTop = node.parentElement.scrollHeight; }, [p.messages.length, panelTab]);
  // B0 simulation resumes persisted running attempts after reload. Unknown tasks
  // require an explicit reconcile action and never auto-submit a replacement.
  useEffect(() => { const timer = setInterval(() => {
    if (!stateRef.current.projects.some(p => p.attempts.some(a => a.status === 'running' && Date.now() - a.createdAt > 2600))) return;
    commit(s => { for (const project of s.projects) for (const a of project.attempts) if (a.status === 'running' && Date.now() - a.createdAt > 2600) D.finishAttempt(project, a.id); });
  }, 600); return () => clearInterval(timer); }, []);

  async function upload(files: FileList | File[]) {
    const projectId = p.id; setUploading(true);
    try {
      const uploaded: LocalAsset[] = []; for (const file of Array.from(files)) uploaded.push(await importAsset(file));
      setAssets(await listAssets());
      commit(s => { const project = s.projects.find(p => p.id === projectId)!; project.assetIds = [...new Set([...project.assetIds, ...uploaded.map(a => a.id)])]; if (project.shots.length) D.invalidateContent(project); D.addEvent(project, `导入 ${uploaded.length} 个本地素材；按哈希去重`); });
      notify(`已导入 ${uploaded.length} 个素材，保存在此浏览器本地。`);
    } catch (e) { notify(String((e as Error).message)); } finally { setUploading(false); }
  }
  function visit(stage: Stage) { if (!D.canVisit(p, stage)) { notify('先完成前面的必要确认，工作台会引导你进入这一步。'); return; } update(p => { p.stage = stage; }); setView('work'); }
  function sendChat(text = chat) {
    if (!text.trim()) return; setChat('');
    update((p, settings) => {
      p.messages.push({ id: D.uid(), role: 'user', text });
      if (/预算|多少钱|费用|价格/.test(text)) {
        const t = D.totals(p); D.say(p, `当前是模拟费用：已结算 ${D.money(t.spent)}，在途 ${D.money(t.reserved)}。Demo 上限 ${D.money(p.demoLimit)}，正式上限 ${D.money(p.totalLimit)}${p.includesDemo ? '（包含 Demo）' : '（Demo 单独计算）'}。点击顶部费用条可以查看账目和手动授权。`);
      } else if (/字幕|12.?秒|十二秒/.test(text) && p.stage === 'review') {
        const quoted = text.match(/[“「"](.+?)[”」"]/);
        p.repair = { shotId: 'S03', text: quoted?.[1] || '跟着今天的节奏。', kind: 'subtitle', status: 'proposed', cents: 0 };
        D.say(p, '已准备第 12 秒附近的字幕修改草案。你可以在审片画布查看前后差异；这个示例只更新字幕和合成，新增媒体费用 ¥0.00，确认后再应用。');
      } else if (/模型|K3|GLM|GPT/i.test(text)) {
        const model = settings.models.find(m => m.id === p.planner)?.name || '主力模型'; D.say(p, `本项目建议由 ${model} 负责策划，经济模型处理已确认内容下的执行。多个候选可以同时启用，任务不会调用全部候选。具体制作模型在内容确认后选择；现在所有通道都是模拟状态。`);
      } else if (p.stage === 'idea' && !/怎么|帮助|流程/.test(text)) {
        p.brief = text; if (p.planReady) { p.planReady = false; p.proposalApproved = false; if (p.shots.length) D.invalidateContent(p); p.stage = 'idea'; } D.say(p, '已把这句话放入创作想法。你可以在画布补充受众和时长，然后生成示例提案。此体验版使用规则回复，尚不能对任意素材做真实 AI 分析。');
      } else {
        const guidance: Record<Stage, string> = { idea: '先描述想法或载入示例，完成模型模拟配置，然后查看导演提案。', content: '直接修改镜头卡中的画面或旁白；确认整套内容后再决定模型和费用。', route: '先看每个镜头的制作方法，再选择已配置模型。报价是模拟数值，确认后才进入关键帧。', frames: '先生成示意关键帧并确认，再制作小样。小样通过后才能进入正式视频。', video: '视频按已批准方案执行。结果不明时先查询原任务，避免重复付费。', audio: '本例是旁白片，视频完成后分别配置配音和配乐。口型片未来采用音轨优先的依赖。', review: '拖动时间线或点击问题定位。可以说“第12秒字幕短一点”，先预览差异再应用。' };
        D.say(p, guidance[p.stage]);
      }
    });
  }
  function begin(kind: D.Attempt['kind'], unknown = false) { update((p, s) => { D.beginAttempt(p, s, kind, unknown); }); }
  function resizePanel(e: React.PointerEvent) {
    e.currentTarget.setPointerCapture(e.pointerId);
    const onMove = (ev: PointerEvent) => setPanelWidth(Math.min(480, Math.max(290, window.innerWidth - ev.clientX)));
    const onUp = () => { window.removeEventListener('pointermove', onMove); window.removeEventListener('pointerup', onUp); };
    window.addEventListener('pointermove', onMove); window.addEventListener('pointerup', onUp);
  }
  function newProject() { if (!newName.trim()) { notify('给这个项目起一个名字。'); return; } commit(s => { const project = D.createProject(newName.trim(), newCategory); D.recommendModels(project, s.settings); s.projects.push(project); s.activeId = project.id; }); setModal(null); setNewName(''); setView('work'); }

  return <>
    <div className="demo-banner"><span><i />流程体验 B0 <b>·</b> AI 回复、生成与费用均为模拟</span><span className="banner-right">不连接账号 · 不产生费用 <button onClick={() => setModal('help')}>体验说明</button></span></div>
    <div className={`app-shell ${store.panelOpen ? '' : 'panel-closed'}`} style={{ '--panel-width': `${panelWidth}px` } as React.CSSProperties}>
      <aside className="sidebar">
        <a className="brand" href="#" onClick={e => { e.preventDefault(); setView('work'); }}><span className="brand-mark"><Clapperboard size={20} strokeWidth={1.5} /></span><span>片场<small>你的 AI 内容团队</small></span></a>
        <Button className="new-project" onClick={() => setModal('new')}><Plus size={16} />新建作品</Button>
        <div className="nav-group"><button className={view === 'work' ? 'active' : ''} onClick={() => setView('work')}><WandSparkles size={17} />导演工作台</button><button className={view === 'projects' ? 'active' : ''} onClick={() => setView('projects')}><FolderOpen size={17} />我的作品<span>{store.projects.length}</span></button><button className={view === 'assets' ? 'active' : ''} onClick={() => setView('assets')}><Images size={17} />本地素材<span>{assets.length}</span></button></div>
        <div className="nav-caption">当前作品</div><div className="project-name">{p.name}</div>
        <nav className="stages" aria-label="创作流程">{D.stages.map((step, i) => <button key={step.id} onClick={() => visit(step.id)} className={view === 'work' && p.stage === step.id ? 'current' : ''} aria-current={p.stage === step.id ? 'step' : undefined}><span className={D.canVisit(p, step.id) ? 'unlocked' : ''}>{D.stages.findIndex(x => x.id === p.stage) > i && D.canVisit(p, step.id) ? <Check size={12} /> : String(i + 1).padStart(2, '0')}</span>{step.label}</button>)}</nav>
        <div className="sidebar-bottom"><button onClick={() => setView('settings')} className={view === 'settings' ? 'active' : ''}><Settings2 size={17} />模型与连接{missing.length > 0 && <i className="warning-dot" />}</button><button onClick={() => setModal('help')}><CircleHelp size={17} />使用帮助</button><div className="local-note"><span className="status-dot" />本地浏览器保存 <span>B0.8</span></div></div>
      </aside>
      <header className="topbar"><div className="breadcrumb"><span>工作空间</span><ChevronRight size={13} /><strong>{view === 'work' ? p.name : { settings: '模型与连接', assets: '本地素材', projects: '我的作品' }[view]}</strong></div><div className="top-actions"><span className="saved">已在本地保存</span><button className="icon-button" aria-label={`切换${store.theme === 'light' ? '深色' : '浅色'}主题`} onClick={() => commit(s => { s.theme = s.theme === 'light' ? 'dark' : 'light'; })}>{store.theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}</button><button className="icon-button" aria-label={store.panelOpen ? '收起导演对话' : '展开导演对话'} onClick={() => commit(s => { s.panelOpen = !s.panelOpen; })}>{store.panelOpen ? <PanelRightClose size={18} /> : <PanelRightOpen size={18} />}</button></div></header>
      <main className="main-area" ref={mainArea}>
        {view === 'work' && <><div className="work-context"><div className="context-pills"><Tag>{p.category === 'commerce' ? '商品短片' : '自媒体讲解'}</Tag><span>{p.duration} 秒</span><span>9:16</span><span>内容 v{p.contentRev}</span></div><BudgetStrip project={p} onOpen={() => setModal('budget')} /></div><Workspace p={p} settings={store.settings} update={update} imageUrl={imageUrl} assets={assets.filter(a => p.assetIds.includes(a.id))} uploading={uploading} upload={upload} notify={notify} begin={begin} openSettings={() => setView('settings')} openBudget={() => setModal('budget')} /></>}
        {view === 'settings' && <Configuration settings={store.settings} setSettings={fn => commit(s => { const before = structuredClone(s.settings); fn(s.settings); for (const project of s.projects) { if (!project.proposalApproved && (!D.available(s.settings, 'primary').some(m => m.id === project.planner) || !D.available(s.settings, 'economy').some(m => m.id === project.executor))) D.recommendModels(project, s.settings); const ids = [project.planner, project.executor, project.reviewer, project.imageModel, project.videoModel, project.audioModel, ...project.shots.filter(x => x.method === 'generate').map(x => x.modelId)]; const fingerprint = (settings: Settings, id: string) => { const m = settings.models.find(m => m.id === id); return JSON.stringify([m, settings.connections.find(c => c.id === m?.provider)]); }; const changed = ids.some(id => fingerprint(before, id) !== fingerprint(s.settings, id)); if (changed && project.routeApproval) { D.invalidateRoute(project); if (D.contentValid(project)) project.stage = 'route'; } } })} onBack={() => setView('work')} notify={notify} />}
        {view === 'assets' && <AssetLibrary assets={assets} urls={urls} project={p} upload={upload} uploading={uploading} attach={id => update(p => { if (!p.assetIds.includes(id)) { p.assetIds.push(id); if (p.shots.length) D.invalidateContent(p); D.addEvent(p, '从本地素材库引用素材'); notify('已加入当前作品。'); } })} />}
        {view === 'projects' && <><div className="page-title"><div><div className="eyebrow">YOUR STUDIO</div><h1>每个想法，都有自己的片场。</h1><p>继续创作，或开启一个新的故事。</p></div><Button kind="primary" onClick={() => setModal('new')}><Plus size={16} />新建作品</Button></div><div className="projects-grid">{store.projects.map(project => <button className="project-card" key={project.id} onClick={() => { commit(s => { s.activeId = project.id; }); setView('work'); }}><div className="project-art"><Clapperboard size={35} strokeWidth={1} /><span>{project.category === 'commerce' ? 'PRODUCT STORY' : 'YOUR STORY'}</span></div><h3>{project.name}</h3><p>{project.duration} 秒 · {D.stages.find(s => s.id === project.stage)?.label}</p><div><Tag tone={project.finalApproved ? 'good' : ''}>{project.finalApproved ? '已确认交付' : '创作中'}</Tag><ChevronRight size={17} /></div></button>)}</div></>}
      </main>
      {store.panelOpen && <aside className="director-panel"><div className="panel-resizer" onPointerDown={resizePanel} role="separator" aria-label="调整导演栏宽度" aria-orientation="vertical" tabIndex={0} onKeyDown={e => { if (e.key === 'ArrowLeft') setPanelWidth(w => Math.min(480, w + 20)); if (e.key === 'ArrowRight') setPanelWidth(w => Math.max(290, w - 20)); }} /><div className="panel-tabs"><button className={panelTab === 'chat' ? 'selected' : ''} onClick={() => setPanelTab('chat')}>导演对话</button><button className={panelTab === 'files' ? 'selected' : ''} onClick={() => setPanelTab('files')}>作品文件</button></div>
        {panelTab === 'chat' ? <><div className="director-identity"><span className="director-avatar"><Clapperboard size={17} /></span><div><strong>导演</strong><small>与你一起，把想法拍出来</small></div><Tag>示例回复</Tag></div><div className="messages">{p.messages.map(message => <div key={message.id} className={`message ${message.role}`}><small>{message.role === 'user' ? '你' : '导演 · 模拟'}</small><p>{message.text}</p></div>)}<div ref={chatEnd} /></div><div className="quick-prompts"><button onClick={() => sendChat('这一步怎么操作？')}>这一步怎么做</button><button onClick={() => sendChat('目前花了多少钱？')}>解释费用</button>{p.stage === 'review' && <button onClick={() => sendChat('第12秒字幕短一点')}>第12秒字幕短一点</button>}</div><form className="chat-composer" onSubmit={e => { e.preventDefault(); sendChat(); }}><textarea aria-label="与导演对话" placeholder="说出想法，或选中作品提出修改…" value={chat} onChange={e => setChat(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } }} /><div><small>{store.settings.models.find(m => m.id === p.planner)?.name || '尚未选择模型'} · 模拟</small><button type="submit" className="send" aria-label="发送给导演" disabled={!chat.trim()}><ArrowUp size={17} /></button></div></form><p className="chat-disclaimer">修改先预览，内容与费用由你确认。</p></> : <div className="files-panel"><div className="eyebrow">当前版本</div><button onClick={() => visit('idea')}><FileText size={18} /><span>创作提案<small>{p.planReady ? p.concept : '尚未生成'}</small></span></button><button onClick={() => visit('content')}><FileText size={18} /><span>脚本与分镜 v{p.contentRev}<small>{p.shots.length} 个镜头 · {D.contentValid(p) ? '已确认' : '待确认'}</small></span></button><button onClick={() => setModal('budget')}><FileText size={18} /><span>制作账本<small>{p.attempts.length} 次模拟任务</small></span></button><div className="eyebrow history-label">过程记录</div>{p.events.length ? p.events.slice(0, 14).map(e => <div className="event" key={e.id}><span /><div>{e.text}<small>{new Date(e.at).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</small></div></div>) : <p className="muted">提案、批准和生成记录会保存在这里。</p>}</div>}
      </aside>}
    </div>
    {modal === 'budget' && <Modal title="预算与制作账本" onClose={() => setModal(null)} wide><BudgetPanel p={p} update={update} /></Modal>}
    {modal === 'new' && <Modal title="开启一部新作品" onClose={() => setModal(null)}><label className="field">作品名称<input autoFocus value={newName} onChange={e => setNewName(e.target.value)} placeholder="例如：通勤保温杯 · 夏日短片" onKeyDown={e => { if (e.key === 'Enter') newProject(); }} /></label><label className="field">创作类型<select value={newCategory} onChange={e => setNewCategory(e.target.value as Project['category'])}><option value="commerce">电商 · 商品短片</option><option value="creator">自媒体 · 观点讲解</option></select></label><p className="muted">新作品复用已配置模型，内容与预算单独记录。</p><div className="dialog-actions"><Button onClick={() => setModal(null)}>取消</Button><Button kind="primary" onClick={newProject}>进入片场<ChevronRight size={15} /></Button></div></Modal>}
    {modal === 'help' && <Modal title="这版可以体验什么" onClose={() => setModal(null)}><p className="help-lead">这是 B 方案的第一批交付：可运行的流程前端。</p><ol className="help-list"><li>先在「模型与连接」点击模拟配置。</li><li>上传参考图，或载入一个示例想法。</li><li>与导演确认提案，再确认脚本和分镜。</li><li>确认模型与费用，验看关键帧和小样。</li><li>分别完成视频、声音，最后审片和局部修改。</li></ol><Notice>所有 AI、媒体和价格都是明确标注的演示数据；导出的是 JSON 项目清单，尚不生成 MP4。</Notice><p className="muted">项目和上传文件存放在此浏览器的本地存储；清除网站数据会删除它们。B1 将迁移到 Python 后台与本地资产目录。</p><div className="dialog-actions"><Button kind="primary" onClick={() => setModal(null)}>开始体验</Button></div></Modal>}
    {toast && <div className="toast" role="status">{toast}</div>}
  </>;
}
