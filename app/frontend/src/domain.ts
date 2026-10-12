// Framework-independent product contracts. B0 uses an in-browser mock adapter;
// these checks are not a replacement for B1 server authorization or budgeting.
export type Stage = 'idea' | 'content' | 'route' | 'frames' | 'video' | 'audio' | 'review';
export type Role = 'primary' | 'economy' | 'image' | 'video' | 'audio';
export type Model = { id: string; apiModelId?: string; name: string; provider: string; role: Role; vision?: boolean; enabled: boolean };
export type Connection = { id: string; name: string; protocol: string; endpoint: string; ready: boolean; region?: 'cn' | 'global' | 'shared' };
export type Settings = { region: 'cn' | 'global'; connections: Connection[]; models: Model[] };
export type Shot = { id: string; title: string; visual: string; narration: string; subtitle?: string; method: 'local' | 'generate'; frame: boolean; clip: boolean; modelId: string };
export type Approval = { contentRev: number; routeRev: number; at: string; scope: string };
export type Attempt = { id: string; projectId: string; kind: 'frames' | 'demo' | 'video' | 'audio' | 'repair'; phase: 'demo' | 'formal'; status: 'running' | 'unknown' | 'succeeded' | 'failed' | 'superseded'; cents: number; rev: number; routeRev: number; createdAt: number; settled: boolean; label: string };
export type Message = { id: string; role: 'user' | 'assistant'; text: string };
export type Event = { id: string; text: string; at: string };
export type Repair = { shotId: string; text: string; kind: 'subtitle' | 'motion'; status: 'proposed' | 'applied'; cents: number };
export type Project = {
  id: string; name: string; category: 'commerce' | 'creator'; brief: string; audience: string; duration: number; complex: boolean;
  stage: Stage; contentRev: number; routeRev: number; planReady: boolean; proposalApproved: boolean;
  concept: string; synopsis: string; contentFromProposal?: string; shots: Shot[]; contentApproval?: Approval; routeApproval?: Approval;
  mode: 'economy' | 'balanced' | 'quality'; resolution: '480' | '720' | '1080';
  planner: string; executor: string; reviewer: string; imageModel: string; videoModel: string; audioModel: string;
  demoLimit: number; totalLimit: number; includesDemo: boolean; demoDone: boolean; demoAccepted: boolean; videoDone: boolean; audioDone: boolean;
  attempts: Attempt[]; messages: Message[]; events: Event[]; assetIds: string[];
  timelineRev: number; reviewResolved: boolean; repair?: Repair; finalApproved?: number; exported: boolean;
};
export type Store = { schema: 1; settings: Settings; projects: Project[]; activeId: string; theme: 'light' | 'dark'; panelOpen: boolean };
export const stages: { id: Stage; label: string; short: string }[] = [
  { id: 'idea', label: '与导演共创', short: '提案' }, { id: 'content', label: '脚本与分镜', short: '内容' },
  { id: 'route', label: '制作方案', short: '方案' }, { id: 'frames', label: '关键帧与小样', short: '小样' },
  { id: 'video', label: '视频制作', short: '视频' }, { id: 'audio', label: '声音制作', short: '声音' },
  { id: 'review', label: '审片与交付', short: '审片' }
];
export const uid = () => globalThis.crypto.randomUUID();
export const money = (cents: number) => `¥${(cents / 100).toFixed(2)}`;
export function initialSettings(): Settings {
  return {
    region: 'cn',
    connections: [
      { id: 'zhipu', name: '智谱', protocol: 'Chat Completions', endpoint: 'https://open.bigmodel.cn/api/paas/v4', ready: false },
      { id: 'kimi', name: 'Kimi', protocol: 'Chat Completions', endpoint: 'https://api.moonshot.cn/v1', ready: false },
      { id: 'deepseek', name: 'DeepSeek', protocol: 'Chat Completions', endpoint: 'https://api.deepseek.com', ready: false },
      { id: 'codex', name: 'ChatGPT / Codex', protocol: 'Codex 本地运行时', endpoint: '官方登录 · B1 接入', ready: false },
      { id: 'openai', name: 'OpenAI API', protocol: 'Responses', endpoint: 'https://api.openai.com/v1', ready: false },
      { id: 'media', name: '媒体服务模拟器', protocol: '异步媒体任务', endpoint: '本地模拟 · 无网络请求', ready: false }
    ],
    models: [
      { id: 'glm-5.3', name: 'GLM-5.3', provider: 'zhipu', role: 'primary', enabled: true },
      { id: 'kimi-k3', name: 'K3', provider: 'kimi', role: 'primary', vision: true, enabled: true },
      { id: 'glm-5.3-flash', name: 'GLM-5.3-Flash', provider: 'zhipu', role: 'economy', vision: true, enabled: true },
      { id: 'deepseek-v4-flash-vision-exp', name: 'DeepSeek-V4-Flash-Vision-Exp', provider: 'deepseek', role: 'economy', vision: true, enabled: true },
      { id: 'deepseek-v4-flash', name: 'DeepSeek-V4-Flash', provider: 'deepseek', role: 'economy', enabled: false },
      ...['gpt-6-astra', 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4-mini'].map((id, i) => ({ id, name: ['GPT-6 Astra', 'GPT-5.6 Sol', 'GPT-5.6 Terra', 'GPT-5.6 Luna', 'GPT-5.5', 'GPT-5.4 Mini'][i], provider: 'codex', role: (i < 2 ? 'primary' : 'economy') as Role, vision: true, enabled: i < 4 })),
      { id: 'image-quality', name: '高质量生图 / 编辑', provider: 'media', role: 'image', enabled: true },
      { id: 'video-economy', name: '常规运动视频', provider: 'media', role: 'video', enabled: true },
      { id: 'video-premium', name: '复杂运动视频', provider: 'media', role: 'video', enabled: true },
      { id: 'audio-tts', name: '旁白 + 已授权配乐', provider: 'media', role: 'audio', enabled: true }
    ]
  };
}
export function createProject(name = '我的第一部作品', category: Project['category'] = 'commerce'): Project {
  return {
    id: uid(), name, category, brief: '', audience: '日常通勤的年轻人', duration: 30, complex: false, stage: 'idea',
    contentRev: 1, routeRev: 1, planReady: false, proposalApproved: false, concept: '', synopsis: '', shots: [],
    mode: 'balanced', resolution: '720', planner: 'glm-5.3', executor: 'glm-5.3-flash', reviewer: 'kimi-k3',
    imageModel: 'image-quality', videoModel: 'video-economy', audioModel: 'audio-tts',
    demoLimit: 2000, totalLimit: 10000, includesDemo: true, demoDone: false, demoAccepted: false, videoDone: false, audioDone: false,
    attempts: [], assetIds: [], timelineRev: 1, reviewResolved: false, exported: false,
    messages: [{ id: uid(), role: 'assistant', text: '你好，我们从你想表达的内容开始。可以上传商品图或个人素材，也可以先写一句想法。当前是流程体验版，我会用示例回复演示导演如何与你共创。' }], events: []
  };
}
export function initialStore(): Store { const p = createProject(); return { schema: 1, settings: initialSettings(), projects: [p], activeId: p.id, theme: 'light', panelOpen: true }; }
export function addEvent(p: Project, text: string) { p.events.unshift({ id: uid(), text, at: new Date().toISOString() }); p.events = p.events.slice(0, 100); }
export function say(p: Project, text: string) { p.messages.push({ id: uid(), role: 'assistant', text }); }
export function modelReady(settings: Settings, id: string) { const m = settings.models.find(m => m.id === id); return Boolean(m?.enabled && settings.connections.find(c => c.id === m.provider)?.ready); }
export function inRegion(s: Settings, provider: string) { const region = s.connections.find(c => c.id === provider)?.region ?? (provider === 'media' ? 'shared' : ['codex', 'openai'].includes(provider) ? 'global' : 'cn'); return region === 'shared' || region === s.region; }
export function available(settings: Settings, role: Role) { return settings.models.filter(m => m.role === role && m.enabled && (role === 'primary' || role === 'economy' ? inRegion(settings, m.provider) : true)); }
export function readiness(s: Settings) {
  const missing: string[] = [];
  if (!available(s, 'primary').some(m => modelReady(s, m.id))) missing.push('主力策划模型');
  if (!available(s, 'economy').some(m => modelReady(s, m.id))) missing.push('经济执行模型');
  if (![...available(s, 'primary'), ...available(s, 'economy')].some(m => m.vision && modelReady(s, m.id))) missing.push('视觉理解');
  for (const [role, name] of [['image', '关键帧'], ['video', '视频'], ['audio', '声音']] as const) if (!available(s, role).some(m => modelReady(s, m.id))) missing.push(name);
  return missing;
}
export function recommendModels(p: Project, s: Settings) {
  const primaries = available(s, 'primary').filter(m => modelReady(s, m.id));
  const economy = available(s, 'economy').filter(m => modelReady(s, m.id));
  p.planner = (p.complex ? primaries.find(m => m.vision) : primaries[0])?.id ?? '';
  p.executor = economy[0]?.id ?? '';
  p.reviewer = [...primaries, ...economy].find(m => m.vision)?.id ?? '';
}
export function draftProposal(p: Project, s: Settings) {
  const missing = readiness(s); if (missing.length) throw new Error(`先完成基础配置：${missing.join('、')}。`);
  if (!p.brief.trim()) throw new Error('先写一句你想表达的内容，或载入示例。');
  if (p.planReady) return;
  recommendModels(p, s); p.planReady = true;
  p.concept = p.category === 'commerce' ? '让产品走进生活' : '把一个观点讲清楚';
  p.synopsis = `用 ${p.duration} 秒，面向${p.audience || '目标观众'}。先用一个生活片段建立共鸣，再清楚展示主体，最后用一句简洁的话收尾。`;
  addEvent(p, '导演提交示例提案，等待确认');
  say(p, '我建议先建立使用情境，再展示主体。提案已放到画布上，你可以直接改文字。缺少实拍证据的产品性能与内部结构不会作为已知事实加入。');
}
export function createContent(p: Project) {
  if (!p.proposalApproved) throw new Error('先确认创作提案。');
  const signature = JSON.stringify([p.concept, p.synopsis, p.brief, p.duration, p.audience, p.complex]);
  if (p.shots.length && p.contentFromProposal === signature) { p.stage = 'content'; return; }
  if (p.shots.length) invalidateContent(p);
  p.contentFromProposal = signature;
  const commerce = p.category === 'commerce';
  const titles = commerce ? ['生活开场', '完整外观', '随行场景', '细节留白', '情绪延续', '主体收尾'] : ['提出问题', '表达观点', '一个例子', '解释原因', '回到自己', '一句话收尾'];
  const visuals = commerce ? ['环境与随身物品的静态构图，建立出发的情绪。', '基于原始参考图展示商品全貌，保留外观与标识。', '独立的环境运动镜头，不生成未经验证的使用功能。', '原始图片裁切细节；没有参考的结构不生成。', '呼应开场的生活场景，运动保持克制。', '回到完整商品图，预留文字空间。'] : ['标题与上传素材建立问题。', '图文表达核心观点。', '用一段情境画面承接例子。', '静态画面和字幕拆解逻辑。', '情境镜头连接个人感受。', '留白画面与一句总结。'];
  const lines = commerce ? ['每一次出发，都可以轻松一点。', '熟悉的样子，就在手边。', '跟着今天的生活节奏，陪你走过每一段日常。', '给日常，留一点从容。', '一路相伴，恰到好处。', '从这一刻，开始你的日常。'] : ['你有没有想过这个问题？', '我想分享一个简单的看法。', '从日常的一个例子说起。', '关键，是理解它背后的原因。', '你也可以试着观察自己的生活。', '让一个想法，变成下一步行动。'];
  p.shots = titles.map((title, i) => ({ id: `S${String(i + 1).padStart(2, '0')}`, title, visual: visuals[i], narration: lines[i], method: [2, 4].includes(i) ? 'generate' : 'local', frame: false, clip: false, modelId: p.videoModel }));
  p.stage = 'content'; addEvent(p, '内容任务完成：6 个文字分镜与旁白草稿');
}
export function contentValid(p: Project) { return p.contentApproval?.contentRev === p.contentRev; }
export function routeValid(p: Project) { return contentValid(p) && p.routeApproval?.contentRev === p.contentRev && p.routeApproval?.routeRev === p.routeRev; }
export function approve(p: Project, scope: 'content' | 'route') {
  if (scope === 'content' && (!p.shots.length || p.shots.some(s => !s.visual.trim() || !s.narration.trim()))) throw new Error('每个分镜需要画面描述和旁白。');
  if (scope === 'route' && !contentValid(p)) throw new Error('内容有更新，请先重新确认脚本和分镜。');
  const a = { contentRev: p.contentRev, routeRev: p.routeRev, at: new Date().toISOString(), scope };
  if (scope === 'content') { p.contentApproval = a; p.stage = 'route'; } else { p.routeApproval = a; p.stage = 'frames'; }
  addEvent(p, `用户确认${scope === 'content' ? '内容' : '制作方案'} · v${scope === 'content' ? p.contentRev : p.routeRev}`);
}
export function invalidateContent(p: Project, shotId?: string) {
  p.contentRev++; p.contentApproval = undefined; p.routeApproval = undefined;
  p.demoDone = false; p.demoAccepted = false; p.videoDone = false; p.audioDone = false;
  p.finalApproved = undefined; p.exported = false; p.reviewResolved = false; p.repair = undefined; p.timelineRev++;
  for (const shot of p.shots) if (!shotId || shot.id === shotId) { shot.frame = false; shot.clip = false; shot.subtitle = undefined; }
  p.stage = 'content'; addEvent(p, `内容更新到 v${p.contentRev}；${shotId || '全部镜头'}的依赖已失效，费用保留`);
}
export function invalidateRoute(p: Project, mediaChanged = false) {
  p.routeRev++; p.routeApproval = undefined; p.finalApproved = undefined; p.exported = false;
  if (mediaChanged) { p.videoDone = false; p.demoDone = false; p.demoAccepted = false; p.shots.forEach(s => s.clip = false); }
  addEvent(p, `制作方案更新到 v${p.routeRev}，待重新确认`);
}
export function totals(p: Project, phase?: 'demo') {
  const attempts = p.attempts.filter(a => phase ? a.phase === phase : p.includesDemo || a.phase === 'formal');
  return { spent: attempts.filter(a => a.settled).reduce((n, a) => n + a.cents, 0), reserved: attempts.filter(a => ['running', 'unknown'].includes(a.status)).reduce((n, a) => n + a.cents, 0) };
}
export function remaining(p: Project, phase: 'demo' | 'formal' = 'formal') { const t = totals(p); const total = p.totalLimit - t.spent - t.reserved; const d = totals(p, 'demo'); return phase === 'demo' ? Math.min(p.demoLimit - d.spent - d.reserved, p.includesDemo ? total : Infinity) : total; }
export function quote(p: Project, kind: Attempt['kind']) {
  // All values are artificial UX fixtures, never live provider prices.
  const multiplier = (p.mode === 'quality' ? 2.1 : p.mode === 'economy' ? .7 : 1) * (p.resolution === '1080' ? 1.6 : p.resolution === '480' ? .75 : 1);
  if (kind === 'frames') return p.shots.filter(s => !s.frame).length * 100;
  if (kind === 'demo') return 900;
  if (kind === 'audio') return 400;
  if (kind === 'repair') return p.repair?.kind === 'motion' ? Math.round(1600 * multiplier) : 0;
  return Math.round(p.shots.filter(s => s.method === 'generate' && !s.clip).reduce((cost, s) => cost + 1600 * (s.modelId === 'video-premium' ? 1.8 : 1), 0) * multiplier * (p.duration / 30));
}
export function routeReady(p: Project, settings: Settings) {
  const ids = [p.planner, p.executor, p.reviewer, p.imageModel, p.videoModel, p.audioModel, ...p.shots.filter(s => s.method === 'generate').map(s => s.modelId)];
  if (!ids.every(id => modelReady(settings, id))) throw new Error('所选模型或服务未启用 / 未验证，请回到模型配置。');
  const matches = (id: string, role: Role) => settings.models.find(m => m.id === id)?.role === role;
  if (!matches(p.planner, 'primary') || !matches(p.executor, 'economy') || !matches(p.imageModel, 'image') || !matches(p.videoModel, 'video') || !matches(p.audioModel, 'audio') || !p.shots.filter(s => s.method === 'generate').every(s => matches(s.modelId, 'video'))) throw new Error('模型与所分配的任务角色不匹配。');
  if (!settings.models.find(m => m.id === p.reviewer)?.vision) throw new Error('视觉复核必须使用支持视觉输入的模型。');
}
export function beginAttempt(p: Project, settings: Settings, kind: Attempt['kind'], unknown = false): Attempt {
  if (!routeValid(p)) throw new Error('当前内容与制作方案需要确认，尚不能开始。');
  routeReady(p, settings);
  if (p.attempts.some(a => ['running', 'unknown'].includes(a.status))) throw new Error('还有在途或结果不明的任务，先处理原任务。');
  if (kind !== 'frames' && !p.shots.every(s => s.frame)) throw new Error('先生成并确认全部关键帧。');
  if (kind === 'video' && !p.demoAccepted) throw new Error('先验看小样并确认进入正式制作。');
  if (kind === 'audio' && !p.videoDone) throw new Error('当前旁白片流程先完成视频。口型片将使用不同依赖。');
  if (kind === 'repair' && (!p.repair || p.repair.status !== 'proposed')) throw new Error('先提出一个局部修改。');
  if (kind === 'repair' && !p.repair?.text.trim()) throw new Error('修改后的内容不能为空。');
  if (kind === 'frames' && framesGenerated(p)) throw new Error('当前关键帧候选已生成，请直接确认，不重复购买。');
  if ((kind === 'demo' && p.demoDone) || (kind === 'video' && p.videoDone) || (kind === 'audio' && p.audioDone)) throw new Error('该阶段已完成，无需重复生成。');
  const phase = ['frames', 'demo'].includes(kind) ? 'demo' : 'formal';
  const cents = quote(p, kind);
  if (cents > remaining(p, phase)) throw new Error(`预算不足：本次需预留 ${money(cents)}，可用 ${money(Math.max(0, remaining(p, phase)))}。请调整方案或手动授权新上限。`);
  const a: Attempt = { id: uid(), projectId: p.id, kind, phase, status: unknown ? 'unknown' : 'running', cents, rev: p.contentRev, routeRev: p.routeRev, createdAt: Date.now(), settled: false, label: ({ frames: '关键帧母版', demo: '小样试拍', video: '正式视频', audio: '配音与配乐', repair: '局部修片' })[kind] };
  p.attempts.push(a); addEvent(p, `${a.label} · ${unknown ? '模拟提交结果不明' : '开始模拟'} · 预留 ${money(cents)}`); return a;
}
export function finishAttempt(p: Project, id: string) {
  const a = p.attempts.find(a => a.id === id); if (!a || !['running', 'unknown'].includes(a.status)) return;
  a.settled = true;
  if (a.rev !== p.contentRev || a.routeRev !== p.routeRev) { a.status = 'superseded'; addEvent(p, '旧版本任务已对账，结果归旧版，不覆盖当前作品'); return; }
  a.status = 'succeeded';
  // Frames first become candidates; confirmation is a separate user action.
  if (a.kind === 'demo') p.demoDone = true;
  if (a.kind === 'video') { p.shots.forEach(s => s.clip = true); p.videoDone = true; }
  if (a.kind === 'audio') { p.audioDone = true; p.timelineRev++; }
  if (a.kind === 'repair' && p.repair) { const shot = p.shots.find(s => s.id === p.repair!.shotId); if (shot && p.repair.kind === 'subtitle') shot.subtitle = p.repair.text; p.repair.status = 'applied'; p.reviewResolved = true; p.finalApproved = undefined; p.exported = false; p.timelineRev++; }
  addEvent(p, `${a.label} · 模拟完成 · 结算 ${money(a.cents)}`);
}
export function framesGenerated(p: Project) { return p.attempts.some(a => a.kind === 'frames' && a.status === 'succeeded' && a.rev === p.contentRev); }
export function canVisit(p: Project, stage: Stage) {
  return stage === 'idea' || (stage === 'content' && p.proposalApproved) || (stage === 'route' && contentValid(p)) || (stage === 'frames' && routeValid(p)) || (stage === 'video' && p.demoAccepted) || (stage === 'audio' && p.videoDone) || (stage === 'review' && p.videoDone && p.audioDone);
}
export function exportManifest(p: Project) {
  if (p.finalApproved !== p.timelineRev || !p.reviewResolved || !p.audioDone || !p.videoDone || !routeValid(p)) throw new Error('先完成当前版本审片与最终确认。');
  return { format: 'director-studio-b0', simulated: true, exportedAt: new Date().toISOString(), project: p, note: '流程体验版项目清单，不是生成的成片。无账户凭据。' };
}
