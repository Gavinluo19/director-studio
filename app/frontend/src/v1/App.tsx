import { useCallback, useEffect, useRef, useState } from "react";
import {
  Clapperboard,
  Plus,
  FolderOpen,
  Images,
  Settings2,
  Sun,
  Moon,
  PanelRightClose,
  PanelRightOpen,
  ArrowUp,
  FileText,
  Check,
  CircleHelp,
} from "lucide-react";
import { Button, Modal, Notice } from "../components.tsx";
import { api, bootstrap, command, ApiError } from "./api.ts";
import { phases, cash, fileUrl } from "./types.ts";
import type {
  Asset,
  Bootstrap,
  Budget,
  Job,
  Project,
  Settings,
  Stage,
} from "./types.ts";
import { LiveSettings } from "./Settings.tsx";
import { Creation } from "./Creation.tsx";
import { Production } from "./Production.tsx";
import "./live.css";
import "./workbench.css";
import {
  ContextNotes,
  MediaWorkbench,
  TranscriptStudio,
  CapabilityPanel,
} from "./Workbench.tsx";
import { DraftContext, useDraftGuard } from "./drafts.tsx";

export type Send = (
  type: string,
  payload?: Record<string, unknown>,
) => Promise<
  { project: Project; job_id?: string; warnings?: string[] } | undefined
>;
export default function LiveApp() {
  const [boot, setBoot] = useState<Bootstrap>();
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [connectionIssue, setConnectionIssue] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [p, setP] = useState<Project>();
  const ref = useRef<Project | undefined>(undefined);
  const [settings, setSettings] = useState<Settings>();
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [budget, setBudget] = useState<Budget>();
  const [view, rawSetView] = useState<
    "work" | "settings" | "assets" | "projects" | "capabilities"
  >("work");
  const pendingDrafts = useRef(new Map<string, string>());
  const [draftCount, setDraftCount] = useState(0);
  const reportDraft = useCallback((id: string, label: string | null) => {
    if (label) pendingDrafts.current.set(id, label);
    else pendingDrafts.current.delete(id);
    setDraftCount(pendingDrafts.current.size);
  }, []);
  const canProceed = useCallback(() => {
    if (!pendingDrafts.current.size) return true;
    setToast(
      "请先保存当前修改：" +
        [...new Set(pendingDrafts.current.values())].join("、") +
        "。生成与导航使用已保存版本。",
    );
    return false;
  }, []);
  const setView = (next: typeof view) => {
    if (canProceed()) rawSetView(next);
  };
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => {
      if (pendingDrafts.current.size) {
        e.preventDefault();
        e.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, []);
  const [narrowScreen, setNarrowScreen] = useState(
    () => window.matchMedia("(max-width: 1020px)").matches,
  );
  const [panel, setPanel] = useState(
    () => !window.matchMedia("(max-width: 1020px)").matches,
  );
  useEffect(() => {
    const q = window.matchMedia("(max-width: 1020px)");
    const update = () => {
      setNarrowScreen(q.matches);
      if (q.matches) setPanel(false);
    };
    q.addEventListener("change", update);
    return () => q.removeEventListener("change", update);
  }, []);
  const [panelTab, setPanelTab] = useState<"chat" | "files">("chat");
  const [panelWidth, setPanelWidth] = useState(350);
  const [assetSearch, setAssetSearch] = useState("");
  const [chat, setChat] = useState("");
  const [busy, setBusy] = useState(false);
  const [selection, setSelection] = useState<{
    shot_id?: string;
    anchor_id?: string;
    transcript_id?: string;
  }>({});
  const [creatorMode, setCreatorMode] = useState<"footage" | "script">(
    "footage",
  );
  const [newName, setNewName] = useState("");
  const [newCategory, setNewCategory] = useState("commerce");
  const [modal, setModal] = useState<"new" | "budget" | "help" | null>(null);
  const [theme, setTheme] = useState(
    localStorage.getItem("studio-live-theme") || "light",
  );
  const [workerReady, setWorkerReady] = useState(false);
  const main = useRef<HTMLElement>(null);
  const messages = useRef<HTMLDivElement>(null);
  const eventTimer = useRef<ReturnType<typeof setTimeout> | undefined>(
    undefined,
  );
  const refreshSequence = useRef(0);
  const takeProject = (project: Project) => {
    if (ref.current?.id !== project.id) {
      refreshSequence.current++;
      setBudget(undefined);
      setJobs([]);
      setSelection({});
    }
    ref.current = project;
    setP(project);
    localStorage.setItem("studio-live-active", project.id);
  };
  async function refresh(projectId = ref.current?.id) {
    const sequence = ++refreshSequence.current;
    const [list, s, a, h] = await Promise.all([
      api<Project[]>("/projects"),
      api<Settings>("/settings"),
      api<Asset[]>("/assets"),
      api<any>("/health"),
    ]);
    if (sequence !== refreshSequence.current) return;
    setProjects(list);
    setSettings(s);
    setAssets(a);
    setWorkerReady(Boolean(h.workers?.length));
    const preferred = projectId || localStorage.getItem("studio-live-active");
    const id = list.some((x) => x.id === preferred) ? preferred : list[0]?.id;
    if (id && list.some((p) => p.id === id)) {
      const [project, j, b] = await Promise.all([
        api<Project>("/projects/" + id),
        api<Job[]>("/projects/" + id + "/jobs"),
        api<Budget>("/projects/" + id + "/budget"),
      ]);
      if (sequence !== refreshSequence.current) return;
      takeProject(project);
      setJobs(j);
      setBudget(b);
    }
  }
  async function connect() {
    try {
      setError("");
      setBoot(await bootstrap());
      await refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    void connect();
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("studio-live-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 6500);
      return () => clearTimeout(t);
    }
  }, [toast]);
  useEffect(() => {
    if (main.current) main.current.scrollTop = 0;
  }, [p?.id, p?.stage, view]);
  useEffect(() => {
    if (messages.current)
      messages.current.scrollTop = messages.current.scrollHeight;
  }, [p?.messages.length, jobs.length]);
  useEffect(() => {
    if (!boot) return;
    const source = new EventSource(
      "/api/events?after=" + (boot.event_cursor || 0),
    );
    source.onmessage = () => {
      clearTimeout(eventTimer.current);
      eventTimer.current = setTimeout(
        () => refresh().catch((e) => setToast(e.message)),
        250,
      );
    };
    source.onerror = () => {};
    const health = setInterval(
      () =>
        api<any>("/health")
          .then((h) => {
            setWorkerReady(Boolean(h.workers?.length));
            setConnectionIssue("");
          })
          .catch(() => {
            setWorkerReady(false);
            setConnectionIssue("本地服务已断开。请运行启动脚本，再点击重新连接。未提交的内容仍保留在当前页面。");
          }),
      10000,
    );
    return () => {
      source.close();
      clearInterval(health);
      clearTimeout(eventTimer.current);
    };
  }, [boot]);
  const send: Send = async (type, payload = {}) => {
    const current = ref.current;
    if (!current) return;
    if (
      !type.startsWith("update_") &&
      !["set_budget", "attach_asset", "save_source_range"].includes(type) &&
      !canProceed()
    )
      return;
    setBusy(true);
    try {
      const result = await command(current, type, payload);
      if (ref.current?.id === current.id) {
        takeProject(result.project);
        await refresh(current.id);
      } else await refresh();
      return result;
    } catch (e) {
      setToast((e as Error).message);
      if (e instanceof ApiError && e.status === 409) await refresh(current.id);
    } finally {
      setBusy(false);
    }
  };
  async function createProject() {
    if (creating || !newName.trim() || !canProceed()) return;
    setCreating(true);
    setCreateError("");
    try {
      const project = await api<Project>("/projects", "POST", {
        name: newName.trim(),
        category: newCategory,
        region: settings?.defaults.region || "cn",
      });
      takeProject(project);
      await refresh(project.id);
      setModal(null);
      setView("work");
      setNewName("");
    } catch (e) {
      setCreateError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }
  async function upload(files: FileList | File[]) {
    const id = ref.current?.id;
    if (!id) return;
    setBusy(true);
    try {
      for (const file of Array.from(files)) {
        const form = new FormData();
        form.set("file", file);
        const a = await api<Asset>("/assets", "POST", form);
        const current = await api<Project>("/projects/" + id);
        const result = await command(current, "attach_asset", {
          asset_id: a.id,
        });
        takeProject(result.project);
      }
      await refresh(id);
      setToast("素材已保存到本地资产目录。");
    } catch (e) {
      setToast((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function chatSend() {
    if (!chat.trim() || !p || !canProceed()) return;
    const text = chat;
    setChat("");
    await send("director", { message: text, ...selection });
  }
  async function saveSettings(s: Settings): Promise<boolean> {
    try {
      const saved = await api<Settings>("/settings", "PUT", s);
      setSettings(saved);
      setToast("配置已保存到本地。");
      return true;
    } catch (e) {
      setToast((e as Error).message);
      return false;
    }
  }
  const inflight = jobs.filter((j) =>
    [
      "queued",
      "submitting",
      "submitted",
      "running",
      "downloading",
      "unknown",
      "cancel_requested",
    ].includes(j.state),
  );
  const draft = jobs.find(
    (j) => j.kind === "plan_content" && j.state === "succeeded",
  );
  return (
    <DraftContext.Provider value={{ report: reportDraft, canProceed }}>
      <div className="demo-banner live-banner">
        <span>
          <i />
          本地制作服务 {boot?.version || "连接中"} <b>·</b>{" "}
          {workerReady ? "独立任务进程运行中" : "任务进程待连接"}
        </span>
        <span>配置后的请求会真实执行 · 费用受项目授权限制</span>
      </div>
      <div
        className={`app-shell v12-shell ${panel ? "" : "panel-closed"}`}
        style={{ "--panel-width": panelWidth + "px" } as React.CSSProperties}
      >
        <aside className="sidebar">
          <a
            className="brand"
            href="/"
            onClick={(e) => {
              e.preventDefault();
              setView("work");
            }}
          >
            <span className="brand-mark">
              <Clapperboard size={20} />
            </span>
            <span>
              片场<small>你的 AI 内容团队</small>
            </span>
          </a>
          <Button className="new-project" onClick={() => setModal("new")}>
            <Plus size={15} />
            新建作品
          </Button>
          <div className="nav-group">
            <button
              className={view === "work" ? "active" : ""}
              onClick={() => setView("work")}
            >
              <Clapperboard size={16} />
              导演工作台
            </button>
            <button
              className={view === "projects" ? "active" : ""}
              onClick={() => setView("projects")}
            >
              <FolderOpen size={16} />
              我的作品<span>{projects.length}</span>
            </button>
            <button
              className={view === "assets" ? "active" : ""}
              onClick={() => setView("assets")}
            >
              <Images size={16} />
              本地素材<span>{assets.length}</span>
            </button>
          </div>
          <div className="nav-caption">当前作品</div>
          <div className="project-name">{p?.name || "尚未创建"}</div>
          <nav className="stages" aria-label="制作流程">
            {phases.map((s, i) => (
              <button
                key={s.id}
                className={
                  p?.stage === s.id && view === "work" ? "current" : ""
                }
                onClick={async () => {
                  const r = await send("set_stage", { stage: s.id });
                  if (r) setView("work");
                }}
              >
                <span>{i + 1}</span>
                {s.name}
              </button>
            ))}
          </nav>
          {p && <ContextNotes key={p.id} p={p} send={send} busy={busy} />}
          <div className="sidebar-bottom">
            <button onClick={() => setView("capabilities")}>
              <FileText size={16} />
              能力与方法
            </button>
            <button
              className={view === "settings" ? "active" : ""}
              onClick={() => setView("settings")}
            >
              <Settings2 size={16} />
              模型与连接
            </button>
            <button onClick={() => setModal("help")}>
              <CircleHelp size={16} />
              使用与保存说明
            </button>
            <div className="local-note">
              <span className="status-dot" />
              本地数据库与资产目录
            </div>
          </div>
        </aside>
        <header className="topbar">
          <div className="breadcrumb">
            <span>工作空间</span>
            <strong>
              {view === "work"
                ? p?.name || "开始创作"
                : view === "settings"
                  ? "模型与连接"
                  : view === "assets"
                    ? "本地素材"
                    : view === "capabilities"
                      ? "能力与方法"
                      : "我的作品"}
            </strong>
          </div>
          <div className="top-actions">
            <span className="saved">
              {busy
                ? "正在处理…"
                : draftCount
                  ? "有未保存修改"
                  : p
                    ? "已保存 · v" + p.revision
                    : ""}
            </span>
            <button
              className="icon-button"
              aria-label="切换黑白主题"
              onClick={() => setTheme(theme === "light" ? "dark" : "light")}
            >
              {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
            </button>
            <button
              className="icon-button"
              aria-label={panel ? "收起导演" : "展开导演"}
              onClick={() => setPanel((v) => !v)}
            >
              {panel ? (
                <PanelRightClose size={17} />
              ) : (
                <PanelRightOpen size={17} />
              )}
            </button>
          </div>
        </header>
        <main
          className="main-area"
          ref={main}
          inert={narrowScreen && panel}
          aria-hidden={narrowScreen && panel}
        >
          {(error || connectionIssue) && (
            <Notice tone="warning">
              {error || connectionIssue}
              <Button onClick={connect}>重新连接</Button>
            </Notice>
          )}
          {!workerReady && boot && (
            <Notice>
              独立任务进程未连接。仍可编辑作品；生成任务会等待进程恢复。
            </Notice>
          )}
          {view === "capabilities" && <CapabilityPanel />}
          {view === "settings" && settings && (
            <LiveSettings
              settings={settings}
              save={saveSettings}
              reload={() => refresh()}
              notify={setToast}
            />
          )}
          {view === "projects" && (
            <>
              <div className="page-title">
                <div>
                  <div className="eyebrow">YOUR STUDIO</div>
                  <h1>从想法，到一部作品。</h1>
                  <p>原始素材、过程版本与最终成片都保存在本机。</p>
                </div>
              </div>
              <div className="inline-actions">
                <label className="btn">
                  恢复项目包
                  <input
                    hidden
                    type="file"
                    accept=".zip"
                    onChange={async (e) => {
                      if (!e.target.files?.[0]) return;
                      const f = new FormData();
                      f.set("file", e.target.files[0]);
                      try {
                        const restored = await api<Project>(
                          "/import-archive",
                          "POST",
                          f,
                        );
                        takeProject(restored);
                        await refresh(restored.id);
                        setView("work");
                        setToast(
                          "项目包已恢复。采用图与制作批准需重新确认，历史费用已保留。",
                        );
                      } catch (error) {
                        setToast((error as Error).message);
                      }
                    }}
                  />
                </label>
              </div>
              <div className="projects-grid">
                {projects.map((project) => (
                  <button
                    className="project-card"
                    key={project.id}
                    onClick={() => {
                      takeProject(project);
                      void refresh(project.id);
                      setView("work");
                    }}
                  >
                    <div className="project-art">
                      <Clapperboard size={30} />
                    </div>
                    <h3>{project.name}</h3>
                    <p>
                      {project.shots.length} 个镜头 · {project.target_duration}{" "}
                      秒
                    </p>
                    <span>
                      {phases.find((s) => s.id === project.stage)?.name}
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}
          {view === "assets" && (
            <>
              <div className="page-title">
                <div>
                  <div className="eyebrow">LOCAL ASSETS</div>
                  <h1>每一次创作，都成为你的资产。</h1>
                  <p>{boot?.data_dir}</p>
                </div>
                <label className="btn">
                  <Plus size={15} />
                  导入素材
                  <input
                    type="file"
                    multiple
                    hidden
                    accept="image/*,audio/*,video/*"
                    onChange={(e) => {
                      if (e.target.files) void upload(e.target.files);
                    }}
                  />
                </label>
              </div>
              <input
                className="search-field"
                aria-label="搜索本地素材"
                placeholder="按文件名查找原图、候选或成片…"
                value={assetSearch}
                onChange={(e) => setAssetSearch(e.target.value)}
              />
              <div className="asset-grid">
                {assets
                  .filter((a) =>
                    a.name.toLowerCase().includes(assetSearch.toLowerCase()),
                  )
                  .map((a) => (
                    <article className="asset-card" key={a.id}>
                      {a.mime.startsWith("image/") ? (
                        <a
                          className="asset-preview"
                          href={fileUrl(a.id)}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <img src={fileUrl(a.id)} alt={a.name} />
                        </a>
                      ) : a.mime.startsWith("video/") ? (
                        <video
                          className="asset-preview"
                          controls
                          src={fileUrl(a.id)}
                        />
                      ) : (
                        <audio controls src={fileUrl(a.id)} />
                      )}
                      <strong>{a.name}</strong>
                      <p>
                        {(a.size / 1048576).toFixed(1)} MB · {a.mime}
                      </p>
                      <Button
                        disabled={!p || p.asset_ids.includes(a.id) || busy}
                        onClick={() =>
                          void send("attach_asset", { asset_id: a.id })
                        }
                      >
                        {p?.asset_ids.includes(a.id)
                          ? "已在当前作品"
                          : "加入当前作品"}
                      </Button>
                    </article>
                  ))}
              </div>
            </>
          )}
          {view === "work" && !p && (
            <div className="library-empty">
              <Clapperboard size={38} />
              <h1>你的片场，准备开场。</h1>
              <p>先创建作品，再配置导演和高质量生图服务。</p>
              <Button kind="primary" onClick={() => setModal("new")}>
                创建第一部作品
              </Button>
            </div>
          )}
          {view === "work" && p && settings && (
            <>
              <div className="work-context">
                <div className="context-pills">
                  <span>
                    {p.category === "commerce" ? "商品短片" : "自媒体"}
                  </span>
                  <span>{p.target_duration} 秒</span>
                  <span>{p.aspect}</span>
                  <span>{"多模型制作"}</span>
                </div>
                {budget && (
                  <button
                    className="budget-strip"
                    onClick={() => setModal("budget")}
                  >
                    <span>
                      <small>媒体已计</small>
                      <b>
                        {cash(budget.media.spent)}{" "}
                        <em>/ {cash(budget.total_limit)}</em>
                      </b>
                    </span>
                    <span className="budget-detail">
                      在途 {cash(budget.media.reserved)}
                    </span>
                  </button>
                )}
              </div>
              {p.category !== "commerce" && (
                <div className="v12-mode-switch">
                  <Button
                    kind={creatorMode === "footage" ? "primary" : "ghost"}
                    onClick={() => {
                      if (canProceed()) setCreatorMode("footage");
                    }}
                  >
                    原片口播 / 访谈
                  </Button>
                  <Button
                    kind={creatorMode === "script" ? "primary" : "ghost"}
                    onClick={() => {
                      if (canProceed()) setCreatorMode("script");
                    }}
                  >
                    文稿型知识视频
                  </Button>
                </div>
              )}
              {p.category !== "commerce" &&
                creatorMode === "footage" &&
                ["idea", "create"].includes(p.stage) && (
                  <TranscriptStudio
                    key={p.id}
                    p={p}
                    assets={assets}
                    send={send}
                    busy={busy}
                    jobs={jobs}
                    upload={upload}
                    select={setSelection}
                  />
                )}
              {p.stage === "idea" &&
                (p.category === "commerce" || creatorMode === "script") && (
                  <Idea
                    key={p.id}
                    project={p}
                    send={send}
                    busy={busy}
                    ready={Boolean(settings.defaults.director)}
                    openSettings={() => setView("settings")}
                    upload={upload}
                    assets={assets.filter((a) => p.asset_ids.includes(a.id))}
                  />
                )}
              {p.stage === "create" &&
                (p.category === "commerce" || creatorMode === "script") && (
                  <MediaWorkbench
                    key={p.id}
                    p={p}
                    assets={assets}
                    send={send}
                    busy={busy}
                    select={setSelection}
                  >
                    <Creation
                      key={p.id}
                      project={p}
                      settings={settings}
                      assets={assets}
                      send={send}
                      busy={busy}
                      jobs={jobs}
                      select={setSelection}
                      openSettings={() => setView("settings")}
                      upload={upload}
                    />
                  </MediaWorkbench>
                )}
              {["route", "video", "audio", "review"].includes(p.stage) && (
                <Production
                  key={p.id}
                  project={p}
                  settings={settings}
                  assets={assets}
                  budget={budget}
                  send={send}
                  busy={busy}
                  jobs={jobs}
                  notify={setToast}
                  refresh={() => refresh()}
                  upload={upload}
                  openSettings={() => setView("settings")}
                />
              )}
            </>
          )}
        </main>
        {panel && (
          <aside className="director-panel">
            <div
              className="panel-resizer"
              role="separator"
              aria-label="调整导演与产物宽度"
              tabIndex={0}
              aria-orientation="vertical"
              aria-valuemin={290}
              aria-valuemax={480}
              aria-valuenow={panelWidth}
              onKeyDown={(e) => {
                if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
                  e.preventDefault();
                  setPanelWidth((w) =>
                    Math.max(
                      290,
                      Math.min(480, w + (e.key === "ArrowRight" ? 20 : -20)),
                    ),
                  );
                }
              }}
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
              }}
              onPointerMove={(e) => {
                if (e.buttons === 1)
                  setPanelWidth(
                    Math.max(
                      290,
                      Math.min(
                        480,
                        narrowScreen
                          ? window.innerWidth - e.clientX
                          : e.clientX - 220,
                      ),
                    ),
                  );
              }}
            />
            <div className="panel-tabs">
              <button
                className={panelTab === "chat" ? "selected" : ""}
                onClick={() => setPanelTab("chat")}
              >
                导演与制作团队
              </button>
              <button
                className={panelTab === "files" ? "selected" : ""}
                onClick={() => setPanelTab("files")}
              >
                作品文件
              </button>
            </div>
            {panelTab === "chat" ? (
              <>
                <div className="director-identity">
                  <span className="director-avatar">
                    <Clapperboard size={17} />
                  </span>
                  <div>
                    <strong>导演</strong>
                    <small>
                      {selection.anchor_id
                        ? "已选中关键帧"
                        : selection.shot_id
                          ? "已选中镜头"
                          : selection.transcript_id
                            ? "已选中原片文稿"
                            : "围绕当前作品共创"}
                    </small>
                  </div>
                </div>
                <div className="messages" ref={messages}>
                  {p && (
                    <div className="v12-director-progress">
                      <small>当前交付</small>
                      <strong>
                        {phases.find((s) => s.id === p.stage)?.name}
                      </strong>
                      <p>
                        {p.shots.length} 个镜头 / 段落 ·{" "}
                        {
                          Object.values(p._computed?.clips || {}).filter(
                            Boolean,
                          ).length
                        }{" "}
                        个片段已就绪
                      </p>
                      <span>
                        {inflight.length
                          ? `${inflight.length} 项任务进行中`
                          : "等待你的下一步决定"}
                      </span>
                    </div>
                  )}
                  {p?.edit_proposals?.slice(-3).map((e) => (
                    <div
                      className="message assistant v12-director-proposal"
                      key={e.id}
                    >
                      <small>
                        {e.kind === "shot" ? "品牌镜头设计" : "个人 IP 粗剪"} ·{" "}
                        {e.skill_version || "导演建议"}
                      </small>
                      <p>{e.summary}</p>
                      <ul>
                        {e.impacts.map((x, i) => (
                          <li key={i}>{x}</li>
                        ))}
                      </ul>
                      {e.status === "proposed" ? (
                        <div className="inline-actions">
                          <Button
                            disabled={busy}
                            onClick={() =>
                              void send("apply_edit", { proposal_id: e.id })
                            }
                          >
                            采用修改
                          </Button>
                          <Button
                            disabled={busy}
                            onClick={() =>
                              void send("reject_edit", { proposal_id: e.id })
                            }
                          >
                            保留原内容
                          </Button>
                        </div>
                      ) : (
                        <small>
                          {e.status === "applied"
                            ? "已应用，保留原版本"
                            : e.status === "rejected"
                              ? "已保留原内容"
                              : "内容已变化，需重新提案"}
                        </small>
                      )}
                    </div>
                  ))}
                  {!p?.messages.length && !p?.edit_proposals?.length && (
                    <div className="message assistant">
                      <p>
                        写下你的想法，或选中镜头告诉我想怎么改。模型需要先配置；新的内容建议由你确认采用。
                      </p>
                    </div>
                  )}
                  {p?.messages.map((m, i) => (
                    <div className={`message ${m.role}`} key={m.id || i}>
                      <small>
                        {m.role === "user"
                          ? "你"
                          : "导演" +
                            (m.models?.length
                              ? " · " + m.models.join(" / ")
                              : "")}
                      </small>
                      <p>{m.text}</p>
                      {m.question && <p>{m.question}</p>}
                    </div>
                  ))}
                  {jobs
                    .filter(
                      (j) =>
                        j.state === "succeeded" &&
                        j.kind === "director" &&
                        j.result.changes?.length,
                    )
                    .slice(0, 2)
                    .map((j) => (
                      <div className="live-suggestions" key={j.id}>
                        {j.result.changes.map((change: any, i: number) => (
                          <div key={i}>
                            <small>{change.reason}</small>
                            <p>{change.value}</p>
                            <Button
                              disabled={busy}
                              onClick={() =>
                                void send("apply_suggestion", {
                                  job_id: j.id,
                                  index: i,
                                })
                              }
                            >
                              采用这条建议
                            </Button>
                          </div>
                        ))}
                      </div>
                    ))}
                  {jobs
                    .filter(
                      (j) =>
                        j.kind === "director" &&
                        j.state === "succeeded" &&
                        j.result.actions?.length,
                    )
                    .slice(0, 1)
                    .map((j) => (
                      <div className="live-suggestions" key={"actions-" + j.id}>
                        {j.result.actions.map((action: any, index: number) => {
                          const targetShot = p?.shots.find(
                            (s) =>
                              s.id === action.target_id ||
                              s.anchors.some((a) => a.id === action.target_id),
                          );
                          const targetAnchor = targetShot?.anchors.find(
                            (a) => a.id === action.target_id,
                          );
                          const image = settings?.models.find(
                            (m) => m.id === settings.defaults.image,
                          );
                          return (
                            <div key={index}>
                              <strong>{jobName(action.kind)}</strong>
                              <small>
                                {targetShot
                                  ? "目标：" +
                                    targetShot.title +
                                    (targetAnchor
                                      ? " · K" +
                                        (targetShot.anchors.indexOf(
                                          targetAnchor,
                                        ) +
                                          1)
                                      : "")
                                  : "目标：当前作品"}
                              </small>
                              <p>{action.reason}</p>
                              {action.kind === "generate_image" && (
                                <small>
                                  {image?.price_confirmed
                                    ? "图像费用 / 上限 ¥" + image.price_cny
                                    : "先配置生图模型与价格"}
                                  ，计入探索预算。
                                </small>
                              )}
                              <Button
                                disabled={busy}
                                onClick={() => {
                                  const payload: Record<string, unknown> = {};
                                  if (action.kind === "generate_image")
                                    payload.anchor_id = action.target_id;
                                  if (action.kind === "refine_shot") {
                                    payload.shot_id = action.target_id;
                                    payload.instruction = action.instruction;
                                  }
                                  void send(action.kind, payload);
                                }}
                              >
                                执行：{jobName(action.kind)}
                              </Button>
                            </div>
                          );
                        })}
                      </div>
                    ))}
                  {inflight.map((j) => (
                    <div className="live-job" key={j.id}>
                      <span className="status-dot" />
                      <div>
                        <strong>{jobName(j.kind)}</strong>
                        <small>
                          {jobState(j.state)}
                          {j.models?.length
                            ? " · " + j.models.map((m) => m.name).join(" / ")
                            : ""}
                        </small>
                        {j.error && <p>{j.error}</p>}
                      </div>
                    </div>
                  ))}
                  {jobs
                    .filter(
                      (j, i) =>
                        j.state === "failed" &&
                        !jobs
                          .slice(0, i)
                          .some(
                            (n) =>
                              n.kind === j.kind &&
                              n.target_id === j.target_id &&
                              n.state !== "failed",
                          ),
                    )
                    .slice(0, 2)
                    .map((j) => (
                      <Notice key={j.id} tone="warning">
                        {jobName(j.kind)}：{j.error}
                      </Notice>
                    ))}
                </div>
                <form
                  className="chat-composer"
                  onSubmit={(e) => {
                    e.preventDefault();
                    void chatSend();
                  }}
                >
                  <textarea
                    aria-label="与导演对话"
                    placeholder="说出想法，或针对选中的镜头提出修改…"
                    value={chat}
                    onChange={(e) => setChat(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void chatSend();
                      }
                    }}
                  />
                  <div>
                    <small>
                      {settings?.models.find(
                        (m) => m.id === settings.defaults.director,
                      )?.name || "先配置导演模型"}
                    </small>
                    <button
                      className="send"
                      aria-label="发送给导演"
                      disabled={!chat.trim() || busy || !p}
                    >
                      <ArrowUp size={16} />
                    </button>
                  </div>
                </form>
                <p className="chat-disclaimer">
                  只在授权范围内执行；费用与采用图由你决定。
                </p>
              </>
            ) : (
              <div className="files-panel">
                <div className="eyebrow">完整脚本</div>
                {p?.blocks.map((b) => (
                  <details key={b.id}>
                    <summary>{b.title}</summary>
                    <p>{b.text}</p>
                  </details>
                ))}
                <div className="eyebrow history-label">素材与过程产物</div>
                {assets
                  .filter((a) => p?.asset_ids.includes(a.id))
                  .map((a) => (
                    <a
                      className="live-file-link"
                      key={a.id}
                      href={fileUrl(a.id)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <FileText size={16} />
                      <span>
                        {a.name}
                        <small>
                          {a.mime} · {(a.size / 1048576).toFixed(1)} MB
                        </small>
                      </span>
                    </a>
                  ))}
                <div className="eyebrow history-label">最近任务</div>
                {jobs.slice(0, 12).map((j) => (
                  <div className="event" key={j.id}>
                    <span />
                    <div>
                      {jobName(j.kind)} · {jobState(j.state)}
                      {j.error && <small>{j.error}</small>}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </aside>
        )}
      </div>
      {modal === "new" && (
        <Modal title="开启新作品" onClose={() => setModal(null)}>
          <label className="field">
            作品名称
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="为你的故事起一个名字"
            />
          </label>
          <label className="field">
            类型
            <select
              value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)}
            >
              <option value="commerce">商品 / 电商短片</option>
              <option value="creator">个人 / 自媒体内容</option>
            </select>
          </label>
          <div className="dialog-actions">
            {createError && <div className="notice warning" role="alert"><span>{createError}<br />请启动片场后重试；作品名称和类型已保留。</span><Button disabled={creating} onClick={connect}>重新连接</Button></div>}
            <Button onClick={() => setModal(null)}>取消</Button>
            <Button kind="primary" disabled={creating || !newName.trim()} onClick={() => void createProject()}>
              {creating ? "创建中…" : "创建作品"}
            </Button>
          </div>
        </Modal>
      )}
      {modal === "budget" && budget && (
        <Modal title="预算、预留与实际记录" onClose={() => setModal(null)} wide>
          <BudgetEditor budget={budget} send={send} />
        </Modal>
      )}
      {modal === "help" && (
        <Modal title="使用与保存说明" onClose={() => setModal(null)}>
          <p>
            先配置强策划与高质量生图能力。脚本与候选图在同一个创作工作区打磨，确认后才选择视频模型。
          </p>
          <Notice>
            接口价格采用你确认的价格或保守上限，账本中的“保守暂计”仍需要与供应商账单核对。Codex
            订阅用量不混算为 API 现金账单。
          </Notice>
          <p className="muted">
            本地数据：{boot?.data_dir}
            <br />
            凭据保存：
            {boot?.vault === "macos_keychain"
              ? "macOS 钥匙串保护"
              : "本地加密存储"}
            <br />
            已生成文件保留原件和版本。B0 模拟项目仍保存在原浏览器空间，可通过{" "}
            <a href="/b0">旧版入口</a> 回看。
          </p>
        </Modal>
      )}
      {toast && (
        <div className="toast" role="status">
          {toast}
        </div>
      )}
    </DraftContext.Provider>
  );
}

export function jobName(kind: string) {
  return (
    (
      {
        director: "导演共创",
        plan_content: "编剧与镜头设计",
        refine_shot: "镜头打磨",
        refine_transcript: "文稿粗剪提案",
        transcribe: "本地转写",
        generate_image: "生成关键帧候选",
        generate_shot: "视频制作",
        generate_tts: "旁白制作",
        generate_music: "音乐制作",
        render: "本地合成",
        ai_review: "AI 审片",
      } as Record<string, string>
    )[kind] || kind
  );
}
export function jobState(state: string) {
  return (
    (
      {
        queued: "等待任务进程",
        submitting: "请求已发送",
        submitted: "服务商已接收",
        running: "执行中",
        downloading: "获取原始产物",
        unknown: "结果不明 · 保留预留",
        succeeded: "完成",
        failed: "未完成",
        superseded: "旧版结果已保留",
        cancel_requested: "已请求停止，可能仍计费",
        cancelled: "已停止",
      } as Record<string, string>
    )[state] || state
  );
}

function Idea({
  project: p,
  send,
  busy,
  ready,
  openSettings,
  upload,
  assets,
}: {
  project: Project;
  send: Send;
  busy: boolean;
  ready: boolean;
  openSettings: () => void;
  upload: (files: FileList | File[]) => Promise<void>;
  assets: Asset[];
}) {
  const [brief, setBrief] = useState(p.brief);
  const [audience, setAudience] = useState(p.audience);
  const [duration, setDuration] = useState(p.target_duration);
  const [aspect, setAspect] = useState(p.aspect);
  const [proposal, setProposal] = useState(p.proposal);
  useDraftGuard(
    "创作想法",
    brief !== p.brief ||
      audience !== p.audience ||
      duration !== p.target_duration ||
      aspect !== p.aspect,
  );
  useDraftGuard("导演提案", proposal !== p.proposal);
  useEffect(() => {
    setBrief(p.brief);
    setAudience(p.audience);
    setDuration(p.target_duration);
    setAspect(p.aspect);
  }, [p.id]);
  useEffect(() => setProposal(p.proposal), [p.proposal]);
  return (
    <>
      <div className="page-title">
        <div>
          <div className="eyebrow">DIRECTOR'S ROOM</div>
          <h1>先把你想讲的故事，说给导演听。</h1>
          <p>人物、商品、观点都可以成为起点；脚本与画面会围绕你的需求展开。</p>
        </div>
      </div>
      {!ready && (
        <Notice>
          <Button onClick={openSettings}>配置导演与生图能力</Button>
        </Notice>
      )}
      <section className="idea-sheet">
        <label className="field">
          创作想法
          <textarea
            value={brief}
            onChange={(e) => setBrief(e.target.value)}
            placeholder="我想讲一个怎样的故事？希望观众看到什么、感受到什么？"
          />
        </label>
        <div className="idea-details">
          <label>
            目标受众
            <input
              value={audience}
              onChange={(e) => setAudience(e.target.value)}
            />
          </label>
          <label>
            目标时长（秒）
            <input
              type="number"
              min="3"
              max="300"
              value={duration}
              onChange={(e) => setDuration(Number(e.target.value))}
            />
          </label>
          <label>
            画幅
            <select
              value={aspect}
              onChange={(e) => setAspect(e.target.value as Project["aspect"])}
            >
              <option>9:16</option>
              <option>16:9</option>
              <option>1:1</option>
            </select>
          </label>
        </div>
        <div className="upload-zone">
          <div>
            <strong>上传原始参考</strong>
            <p>
              {assets.length
                ? assets.map((a) => a.name).join(" · ")
                : "商品白底图、人物图片、已有视频或录音"}
            </p>
          </div>
          <label className="btn">
            选择文件
            <input
              hidden
              multiple
              type="file"
              accept="image/*,audio/*,video/*"
              onChange={(e) => {
                if (e.target.files) void upload(e.target.files);
              }}
            />
          </label>
        </div>
        <div className="sheet-footer">
          <Button
            disabled={busy}
            onClick={() =>
              void send("update_brief", {
                brief,
                audience,
                target_duration: duration,
                aspect,
              })
            }
          >
            保存想法
          </Button>
          <Button
            kind="primary"
            disabled={busy || !brief.trim()}
            onClick={async () => {
              const r = await send("update_brief", {
                brief,
                audience,
                target_duration: duration,
                aspect,
              });
              if (r)
                await send("director", {
                  message:
                    "请根据当前创作想法提出具体叙事方案，并指出缺少的关键素材。",
                });
            }}
          >
            请导演提案
          </Button>
        </div>
      </section>
      {p.proposal && (
        <section className="proposal-sheet">
          <div className="eyebrow">导演提案 · 可编辑</div>
          <textarea
            className="live-proposal"
            value={proposal}
            onChange={(e) => setProposal(e.target.value)}
          />
          <div className="dialog-actions">
            <Button
              disabled={busy}
              onClick={() => void send("update_proposal", { text: proposal })}
            >
              保存提案修改
            </Button>
            <Button
              kind="primary"
              disabled={busy}
              onClick={async () => {
                if (proposal !== p.proposal) {
                  const r = await send("update_proposal", { text: proposal });
                  if (!r) return;
                }
                await send("approve_proposal");
              }}
            >
              确认方向，进入脚本与画面
            </Button>
          </div>
        </section>
      )}
      <button
        className="text-button"
        onClick={() => void send("add_block", { title: "我的脚本", text: "" })}
      >
        已有脚本，直接进入共创编辑
      </button>
    </>
  );
}

function BudgetEditor({ budget: b, send }: { budget: Budget; send: Send }) {
  const [reconcileId, setReconcileId] = useState("");
  const [actual, setActual] = useState("");
  const [billConfirmed, setBillConfirmed] = useState(false);
  const [billMessage, setBillMessage] = useState("");
  const [demo, setDemo] = useState(b.demo_limit / 1e6),
    [total, setTotal] = useState(b.total_limit / 1e6),
    [cognitive, setCognitive] = useState(b.cognitive_limit / 1e6),
    [include, setInclude] = useState(Boolean(b.include_demo)),
    [confirm, setConfirm] = useState(false);
  return (
    <>
      <div className="budget-totals">
        <div>
          <small>媒体已计</small>
          <strong>{cash(b.media.spent)}</strong>
        </div>
        <div>
          <small>媒体在途</small>
          <strong>{cash(b.media.reserved)}</strong>
        </div>
        <div>
          <small>探索已计 / 上限</small>
          <strong>
            {cash(b.demo.spent)} / {cash(b.demo_limit)}
          </strong>
        </div>
      </div>
      {b.subscription_equivalent && (
        <p className="live-equivalent-cost">
          订阅 Token 折算 API 参考价值：
          <strong>{cash(b.subscription_equivalent.micros)}</strong>
          。这是按官方单价换算的用量价值，不是实际 API 扣费；未计入媒体预算。
          {b.subscription_equivalent.missing_calls > 0
            ? ` ${b.subscription_equivalent.missing_calls} 次缺少可换算用量。`
            : ""}
        </p>
      )}
      {b.tokens && (
        <Notice>
          已记录 Token{" "}
          {b.tokens.calls_with_usage
            ? b.tokens.total.toLocaleString()
            : "接口尚未返回用量"}{" "}
          · 缓存输入 {b.tokens.cached_input.toLocaleString()} ·{" "}
          {b.tokens.calls_with_usage} 次有用量记录，
          {b.tokens.calls_missing_usage} 次缺失。不把缺失视为零。
        </Notice>
      )}
      <Notice>
        认知 API 已计 {cash(b.cognitive.spent)}，在途{" "}
        {cash(b.cognitive.reserved)}。Codex 订阅单列用量，不以 API
        单价虚构现金支出。
      </Notice>
      <div className="form-two">
        <label className="field">
          探索 / Demo 上限（元）
          <input
            type="number"
            min="0"
            step="0.01"
            value={demo}
            onChange={(e) => {
              setDemo(Number(e.target.value));
              setConfirm(false);
            }}
          />
        </label>
        <label className="field">
          正式媒体上限（元）
          <input
            type="number"
            min="0"
            step="0.01"
            value={total}
            onChange={(e) => {
              setTotal(Number(e.target.value));
              setConfirm(false);
            }}
          />
        </label>
        <label className="field">
          认知 API 上限（元）
          <input
            type="number"
            min="0"
            step="0.01"
            value={cognitive}
            onChange={(e) => {
              setCognitive(Number(e.target.value));
              setConfirm(false);
            }}
          />
        </label>
      </div>
      <label className="check-label">
        <input
          type="checkbox"
          checked={include}
          onChange={(e) => {
            setInclude(e.target.checked);
            setConfirm(false);
          }}
        />
        正式上限包含探索费用
      </label>
      <label className="check-label explicit-approval">
        <input
          type="checkbox"
          checked={confirm}
          onChange={(e) => setConfirm(e.target.checked)}
        />
        我明确授权本项目使用上述上限
      </label>
      <Button
        disabled={!confirm}
        onClick={() =>
          void send("set_budget", {
            demo_limit: Math.round(demo * 1e6),
            total_limit: Math.round(total * 1e6),
            cognitive_limit: Math.round(cognitive * 1e6),
            include_demo: include ? 1 : 0,
            explicit_authorization: true,
          })
        }
      >
        保存预算授权
      </Button>
      <div className="ledger">
        {b.attempts.map((a) => (
          <div key={a.id}>
            <span>
              <strong>
                {a.phase === "demo" ? "探索" : "正式"} ·{" "}
                {a.category === "cognitive" ? "认知任务" : "媒体任务"}
              </strong>
              <small>
                {a.state === "reserved"
                  ? "在途预留"
                  : a.settlement_kind === "ceiling_estimate"
                    ? "保守暂计，待对账"
                    : a.settlement_kind === "codex_subscription"
                      ? "Codex 订阅"
                      : a.settlement_kind === "local"
                        ? "本地处理"
                        : a.settlement_kind}
              </small>
            </span>
            <b>{cash(a.settled ?? a.reserved)}</b>
            {a.settlement_kind === "ceiling_estimate" && (
              <button
                className="text-button"
                onClick={() => {
                  setReconcileId(a.job_id);
                  setActual("");
                  setBillConfirmed(false);
                  setBillMessage("");
                }}
              >
                核对实际账单
              </button>
            )}
          </div>
        ))}
      </div>
      {reconcileId && (
        <section className="budget-authorize">
          <h3>核对这次调用的实际支出</h3>
          <label className="field">
            实际人民币金额
            <input
              type="number"
              min="0"
              step="0.01"
              value={actual}
              onChange={(e) => {
                setActual(e.target.value);
                setBillConfirmed(false);
              }}
            />
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={billConfirmed}
              onChange={(e) => setBillConfirmed(e.target.checked)}
            />
            已核对服务商对应任务的最终账单
          </label>
          <div className="inline-actions">
            <Button onClick={() => setReconcileId("")}>取消</Button>
            <Button
              disabled={!billConfirmed || actual === ""}
              onClick={async () => {
                try {
                  await api("/jobs/" + reconcileId + "/reconcile", "POST", {
                    actual_micros: Math.round(Number(actual) * 1e6),
                    explicit_confirmation: true,
                    note: "用户在账本核对最终金额",
                  });
                  setReconcileId("");
                } catch (e) {
                  setBillMessage((e as Error).message);
                }
              }}
            >
              保存实际支出
            </Button>
          </div>
          {billMessage && <p>{billMessage}</p>}
        </section>
      )}
    </>
  );
}
