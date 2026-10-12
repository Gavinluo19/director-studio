import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  Download,
  Plus,
  Play,
  RotateCcw,
  AudioLines,
} from "lucide-react";
import { Button, Modal, Notice, PageTitle, Tag } from "../components.tsx";
import { api } from "./api.ts";
import { cash, fileUrl, uid } from "./types.ts";
import type {
  Asset,
  AudioPlan,
  Budget,
  Cue,
  Job,
  Project,
  Route,
  RouteItem,
  Settings,
} from "./types.ts";
import { jobName, jobState } from "./App.tsx";
import { useDraftGuard } from "./drafts.tsx";
import { VideoCandidates } from "./Workbench.tsx";
import type { Send } from "./App.tsx";

type Props = {
  project: Project;
  settings: Settings;
  assets: Asset[];
  budget?: Budget;
  send: Send;
  busy: boolean;
  jobs: Job[];
  notify: (s: string) => void;
  refresh: () => Promise<void>;
  upload: (files: FileList | File[]) => Promise<void>;
  openSettings: () => void;
};
export function Production({
  project: p,
  settings,
  assets,
  budget,
  send,
  busy,
  jobs,
  notify,
  refresh,
  upload,
  openSettings,
}: Props) {
  const [route, setRoute] = useState(p.route);
  const [dirty, setDirty] = useState(false);
  useDraftGuard("制作路线", dirty);
  const [mode, setMode] = useState(p.route.mode);
  const [resolution, setResolution] = useState(p.route.resolution);
  const [reconcile, setReconcile] = useState<Job | null>(null);
  const [remoteId, setRemoteId] = useState("");
  const [actual, setActual] = useState("");
  const [reconciled, setReconciled] = useState(false);
  const [issue, setIssue] = useState("");
  const [time, setTime] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (!dirty) setRoute(p.route);
  }, [p.route, dirty]);
  const currentJob = (shotId: string) =>
    jobs.find(
      (j) =>
        j.kind === "generate_shot" &&
        j.target_id === shotId &&
        [
          "queued",
          "submitting",
          "submitted",
          "running",
          "downloading",
          "unknown",
        ].includes(j.state),
    );
  const waiting = jobs.filter((j) =>
    [
      "queued",
      "submitting",
      "submitted",
      "running",
      "downloading",
      "unknown",
      "failed",
      "cancel_requested",
    ].includes(j.state),
  );
  function updateRoute(index: number, patch: Partial<RouteItem>) {
    const next = structuredClone(route);
    Object.assign(next.items[index], patch);
    setRoute(next);
    setDirty(true);
  }
  async function refreshResult(fn: () => Promise<unknown>) {
    try {
      await fn();
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    }
  }
  const jobsView = () =>
    waiting.length > 0 && (
      <details
        className="sheet live-job-list"
        open={waiting.some((j) => j.state !== "failed")}
      >
        <summary>任务与异常处理 · {waiting.length} 项</summary>
        {waiting.map((j) => (
          <div className="live-job-row" key={j.id}>
            <div>
              <strong>{jobName(j.kind)}</strong>
              <small>{jobState(j.state)}</small>
              {j.error && <p>{j.error}</p>}
              {j.external_id && <small>服务商任务 ID：{j.external_id}</small>}
            </div>
            {["unknown", "failed", "cancel_requested"].includes(j.state) ? (
              <Button
                onClick={() => {
                  setReconcile(j);
                  setRemoteId(j.external_id || "");
                  setActual("");
                  setReconciled(false);
                }}
              >
                查询 / 对账
              </Button>
            ) : (
              <Button
                onClick={() =>
                  void refreshResult(() =>
                    api("/jobs/" + j.id + "/cancel", "POST"),
                  )
                }
              >
                请求停止
              </Button>
            )}
          </div>
        ))}
      </details>
    );
  return (
    <>
      {p.stage === "route" && (
        <>
          <PageTitle
            eyebrow="PRODUCTION ROUTING"
            title="内容已确定，把钱花在有效的镜头上。"
          >
            按场景、原生规格、已确认价格和可用账户给出路线。静态展示优先原图，复杂动作优先强模型。
          </PageTitle>
          <div className="route-settings">
            <label>
              制作投入
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value as Route["mode"])}
              >
                <option value="economy">经济</option>
                <option value="balanced">均衡</option>
                <option value="quality">高质量</option>
              </select>
            </label>
            <label>
              输出规格
              <select
                value={resolution}
                onChange={(e) => setResolution(e.target.value)}
              >
                <option value="480">480P</option>
                <option value="720">720P</option>
                <option value="1080">1080P</option>
              </select>
            </label>
            <Button
              kind="primary"
              disabled={busy}
              onClick={async () => {
                setDirty(false);
                const r = await send("suggest_route", { mode, resolution });
                if (r?.warnings?.length) notify(r.warnings.join(" "));
              }}
            >
              推荐并核算路线
            </Button>
          </div>
          <section className="sheet">
            <div className="section-heading">
              <h2>逐镜头制作方式</h2>
              <Button onClick={openSettings}>配置视频模型</Button>
            </div>
            {!route.items.length && (
              <Notice>
                先点击推荐路线。没有可用视频模型时，会明确提示配置，不会自动选择未知计费接口。
              </Notice>
            )}
            {route.items.map((item, i) => {
              const shot = p.shots.find((s) => s.id === item.shot_id)!;
              const model = settings.models.find((m) => m.id === item.model_id);
              return (
                <div className="live-route-item" key={item.shot_id}>
                  <div>
                    <strong>{shot.title}</strong>
                    <small>
                      {shot.duration}s ·{" "}
                      {shot.difficulty === "complex"
                        ? "复杂动作"
                        : shot.difficulty === "static"
                          ? "静态表达"
                          : "简单运动"}
                    </small>
                    <p>{item.reason}</p>
                    {!!item.checks?.length && (
                      <details>
                        <summary>推荐依据与待验证项</summary>
                        {item.checks.map((x, i) => (
                          <p key={i}>{x}</p>
                        ))}
                      </details>
                    )}
                    {!!item.alternatives?.length && (
                      <details>
                        <summary>备用方案与报价</summary>
                        {item.alternatives.map((a: any) => (
                          <p key={a.model_id}>
                            {a.name} · {cash(a.cost_micros)} ·{" "}
                            {a.evidence?.length
                              ? `${a.evidence.length} 条证据`
                              : "尚无内部样片证据"}
                          </p>
                        ))}
                      </details>
                    )}
                    {!!item.exclusions?.length && (
                      <details>
                        <summary>已排除的模型</summary>
                        {item.exclusions.map((x: any, i: number) => (
                          <p key={i}>
                            {x.name || x.model_id}：{x.reason}
                          </p>
                        ))}
                      </details>
                    )}
                  </div>
                  <div>
                    <label className="field">
                      制作方式
                      <select
                        value={item.method}
                        onChange={(e) =>
                          updateRoute(i, {
                            method: e.target.value as RouteItem["method"],
                          })
                        }
                      >
                        <option value="local">采用图本地合成</option>
                        {shot.source_video_id && (
                          <option value="reuse">复用已有视频</option>
                        )}
                        <option value="generate">生成运动视频</option>
                      </select>
                    </label>
                    {item.method === "local" && (
                      <label className="field">
                        原图动效
                        <select
                          value={item.local_motion || "none"}
                          onChange={(e) =>
                            updateRoute(i, {
                              local_motion: e.target.value as
                                | "none"
                                | "push_in",
                            })
                          }
                        >
                          <option value="none">固定定版</option>
                          <option value="push_in">缓慢推近 · 本地完成</option>
                        </select>
                      </label>
                    )}
                    {item.method === "generate" && (
                      <>
                        <label className="field">
                          视频模型
                          <select
                            value={item.model_id}
                            onChange={(e) => {
                              const m = settings.models.find(
                                (x) => x.id === e.target.value,
                              )!;
                              const native =
                                m.durations.find((d) => d >= shot.duration) ||
                                Math.ceil(shot.duration);
                              const usage = Object.fromEntries(
                                shot.anchors.map((a, index) => [
                                  a.id,
                                  index === 0
                                    ? "first"
                                    : a.role === "end" && m.first_last
                                      ? "last"
                                      : "review",
                                ]),
                              );
                              updateRoute(i, {
                                model_id: m.id,
                                native_duration: native,
                                anchor_usage: usage,
                              });
                            }}
                          >
                            <option value="">选择模型</option>
                            {settings.models
                              .filter((m) => m.kind === "video" && m.enabled)
                              .map((m) => (
                                <option key={m.id} value={m.id}>
                                  {m.name}
                                </option>
                              ))}
                          </select>
                        </label>
                        <label className="field">
                          原生生成 / 计费时长
                          <input
                            type="number"
                            min={shot.duration}
                            value={item.native_duration}
                            onChange={(e) =>
                              updateRoute(i, {
                                native_duration: Number(e.target.value),
                              })
                            }
                          />
                        </label>
                        <small>
                          采用 {shot.duration}s，按 {item.native_duration}s
                          核算；其余部分裁切。
                          {Object.values(item.anchor_usage).includes("review")
                            ? " 中间设计帧仅作验收参考。"
                            : ""}
                        </small>
                      </>
                    )}
                    <strong className="live-route-cost">
                      {dirty ? "保存后重新核价" : cash(item.estimated_micros)}
                    </strong>
                  </div>
                </div>
              );
            })}
            <div className="inline-actions">
              <Button
                disabled={busy || !dirty}
                onClick={async () => {
                  const r = await send("update_route", { route });
                  if (r) setDirty(false);
                }}
              >
                保存路线并重新核价
              </Button>
            </div>
          </section>
          <div className="quote-card">
            <div>
              <small>本轮视频生成预计费用</small>
              <strong>
                {cash(route.items.reduce((n, i) => n + i.estimated_micros, 0))}
              </strong>
              <p>已花和在途费用另外累计；配音、音乐在声音阶段独立核算。</p>
            </div>
            {budget && (
              <span>
                剩余媒体授权{" "}
                {cash(
                  budget.total_limit -
                    budget.media.spent -
                    budget.media.reserved,
                )}
              </span>
            )}
          </div>
          <div className="next-action">
            <div>
              <strong>确认当前模型、方法和规格</strong>
              <p>后续更换相关配置或内容时，会要求重新确认受影响的路线。</p>
            </div>
            <Button
              kind="primary"
              disabled={busy || dirty || !route.items.length}
              onClick={() => void send("approve_route")}
            >
              确认制作方案
              <Check size={15} />
            </Button>
          </div>
        </>
      )}
      {p.stage === "video" && (
        <>
          <PageTitle
            eyebrow="VIDEO PRODUCTION"
            title="逐个镜头，完成真实画面。"
          >
            已有的当前版本片段可以复用；生成失败时先查看原任务，避免重复收费。
          </PageTitle>
          {jobsView()}
          <div className="live-video-grid">
            {p.shots.map((shot, i) => {
              const item = p.route.items.find((r) => r.shot_id === shot.id);
              const valid = p._computed?.clips[shot.id];
              const j = currentJob(shot.id);
              return (
                <article className="sheet" key={shot.id}>
                  {shot.clip_asset_id ? (
                    <video
                      controls
                      preload="metadata"
                      src={fileUrl(shot.clip_asset_id)}
                    />
                  ) : (
                    <div className="empty">
                      <Play size={22} />
                      <span>等待制作</span>
                    </div>
                  )}
                  <div className="section-heading">
                    <div>
                      <h3>
                        {i + 1}. {shot.title}
                      </h3>
                      <small>
                        {shot.duration}s ·{" "}
                        {item?.method === "local"
                          ? "本地原图合成"
                          : item?.method === "reuse"
                            ? "原视频复用"
                            : settings.models.find(
                                (m) => m.id === item?.model_id,
                              )?.name || "未选模型"}
                      </small>
                    </div>
                    <Tag tone={valid ? "good" : ""}>
                      {valid
                        ? "当前版本可用"
                        : j
                          ? jobState(j.state)
                          : "待制作 / 更新"}
                    </Tag>
                  </div>
                  <Button
                    disabled={busy || Boolean(j)}
                    onClick={() =>
                      void send("generate_shot", {
                        shot_id: shot.id,
                        regenerate: Boolean(valid),
                      })
                    }
                  >
                    {valid
                      ? "重新制作此镜头"
                      : item?.method === "generate"
                        ? "生成此镜头 · " + cash(item.estimated_micros)
                        : "制作本地片段"}
                  </Button>
                  <VideoCandidates shot={shot} send={send} busy={busy} />
                  {shot.clip_asset_id && !valid && (
                    <Button
                      disabled={busy || Boolean(j)}
                      onClick={() =>
                        void send("accept_existing_clip", {
                          shot_id: shot.id,
                          explicit_confirmation: true,
                        })
                      }
                    >
                      已验看，沿用此视频
                    </Button>
                  )}
                </article>
              );
            })}
          </div>
          <div className="next-action">
            <Button
              disabled={busy}
              onClick={async () => {
                for (const shot of p.shots) {
                  if (p._computed?.clips[shot.id] || currentJob(shot.id))
                    continue;
                  if (!(await send("generate_shot", { shot_id: shot.id })))
                    break;
                }
              }}
            >
              制作所有待完成镜头
            </Button>
            <Button
              kind="primary"
              disabled={busy || !p.shots.every((s) => p._computed?.clips[s.id])}
              onClick={() => void send("set_stage", { stage: "audio" })}
            >
              画面就位，进入声音
              <ArrowRight size={15} />
            </Button>
          </div>
        </>
      )}
      {p.stage === "audio" && (
        <>
          <PageTitle
            eyebrow="SOUND & TIMELINE"
            title="旁白、字幕与配乐，独立处理。"
          >
            一句话可以跨多个镜头；改字幕不重做视频，改台词则重新生成对应声音。
          </PageTitle>
          {jobsView()}
          <AudioEditor
            project={p}
            settings={settings}
            assets={assets}
            send={send}
            busy={busy}
            upload={upload}
            openSettings={openSettings}
          />
          <div className="next-action">
            <div>
              <strong>生成完整声画预览</strong>
              <p>合成前校验当前片段、旁白时长、字幕和输出规格。</p>
            </div>
            <Button
              kind="primary"
              disabled={
                busy ||
                jobs.some(
                  (j) =>
                    j.kind === "render" &&
                    ["queued", "running"].includes(j.state),
                )
              }
              onClick={() => void send("render")}
            >
              本地合成并进入审片
            </Button>
          </div>
        </>
      )}
      {p.stage === "review" && (
        <>
          <PageTitle
            eyebrow="REVIEW & DELIVER"
            title="在真实成片上，做最后决定。"
          >
            点击问题可定位到相应时间。任何声画修改后都需合成当前版本再确认。
          </PageTitle>
          {jobsView()}
          {p.preview_asset_id ? (
            <video
              className="live-review-player"
              ref={video}
              controls
              src={fileUrl(p.preview_asset_id)}
              onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
            />
          ) : (
            <Notice>还没有完整预览，请先合成。</Notice>
          )}
          <div className="inline-actions">
            <span className="muted">
              当前位置 {time.toFixed(1)}s ·{" "}
              {p._computed?.render_current
                ? "预览为当前版本"
                : "预览已旧，请重新合成"}
            </span>
            <Button disabled={busy} onClick={() => void send("ai_review")}>
              请 AI 审片
            </Button>
            <Button disabled={busy} onClick={() => void send("render")}>
              重新合成
            </Button>
          </div>
          <section className="sheet">
            <div className="section-heading">
              <h2>审片问题与证据</h2>
              <Tag>
                {p.review_issues.filter((i) => i.status === "open").length}{" "}
                项待处理
              </Tag>
            </div>
            {p.review_issues.map((i) => (
              <div className="live-review-issue" key={i.id}>
                <button
                  className="text-button"
                  onClick={() => {
                    if (video.current) video.current.currentTime = i.start;
                  }}
                >
                  {i.start.toFixed(1)}–{i.end.toFixed(1)}s
                </button>
                <div>
                  <strong>{i.description}</strong>
                  <small>
                    {i.source === "ai" ? "AI 抽样检查" : "人工标记"} ·{" "}
                    {i.severity} · {i.status}
                  </small>
                  {i.evidence_asset_ids.length > 0 && (
                    <div className="live-evidence">
                      {i.evidence_asset_ids.map((id) => (
                        <a
                          href={fileUrl(id)}
                          key={id}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <img src={fileUrl(id)} alt="审片证据" />
                        </a>
                      ))}
                    </div>
                  )}
                </div>
                {i.status === "open" && (
                  <div>
                    <Button
                      disabled={busy}
                      onClick={() =>
                        void send("resolve_review_issue", {
                          issue_id: i.id,
                          status: "resolved",
                          note: "用户已检查并处理",
                        })
                      }
                    >
                      已处理
                    </Button>
                    <button
                      className="text-button"
                      onClick={() =>
                        void send("resolve_review_issue", {
                          issue_id: i.id,
                          status: "accepted",
                          note: "用户核对后接受此偏差",
                        })
                      }
                    >
                      接受此偏差
                    </button>
                  </div>
                )}
              </div>
            ))}
            <label className="field">
              在当前时间点添加意见
              <textarea
                value={issue}
                onChange={(e) => setIssue(e.target.value)}
                placeholder="例如：这一处字幕太长，或商品外观与参考不一致。"
              />
            </label>
            <Button
              disabled={busy || !issue.trim()}
              onClick={async () => {
                const r = await send("add_review_issue", {
                  start: time,
                  end: Math.min(time + 1, p.target_duration),
                  description: issue,
                  severity: "warning",
                });
                if (r) setIssue("");
              }}
            >
              添加审片意见
            </Button>
          </section>
          <details className="sheet">
            <summary>字幕与声音局部修改</summary>
            <AudioEditor
              project={p}
              settings={settings}
              assets={assets}
              send={send}
              busy={busy}
              upload={upload}
              openSettings={openSettings}
            />
          </details>
          <div className="next-action">
            <div>
              <strong>
                {p._computed?.final_current
                  ? "这一版已获最终确认"
                  : "请完整验看后确认当前版本"}
              </strong>
              <p>
                MP4 为真实本地合成产物。项目包包含素材与过程文件，不含凭据。
              </p>
            </div>
            <div className="action-group">
              <Button
                kind="primary"
                disabled={busy || !p._computed?.render_current}
                onClick={() => void send("approve_final")}
              >
                我已审片，确认交付
              </Button>
              {p._computed?.final_current && (
                <a
                  className="btn primary"
                  href={"/api/projects/" + p.id + "/export"}
                >
                  <Download size={14} />
                  导出 MP4
                </a>
              )}
              <a className="btn" href={"/api/projects/" + p.id + "/subtitles"}>
                下载字幕 SRT
              </a>
              <a className="btn" href={"/api/projects/" + p.id + "/archive"}>
                下载项目包
              </a>
            </div>
          </div>
        </>
      )}
      {reconcile && (
        <Modal title="查询原任务 / 账单对账" onClose={() => setReconcile(null)}>
          <Notice>
            不要在结果不明时直接重新付费生成。可先填原供应商任务 ID
            继续查询，或依据账单确认本次实际支出。
          </Notice>
          {reconcile.kind === "generate_shot" && (
            <>
              <label className="field">
                原供应商任务 ID
                <input
                  value={remoteId}
                  onChange={(e) => setRemoteId(e.target.value)}
                />
              </label>
              <Button
                disabled={!remoteId.trim()}
                onClick={() =>
                  void refreshResult(async () => {
                    await api("/jobs/" + reconcile.id + "/reconcile", "POST", {
                      external_id: remoteId,
                    });
                    setReconcile(null);
                  })
                }
              >
                继续查询原任务
              </Button>
            </>
          )}
          <hr />
          <label className="field">
            账单实际金额（元）
            <input
              type="number"
              min="0"
              step="0.01"
              value={actual}
              onChange={(e) => {
                setActual(e.target.value);
                setReconciled(false);
              }}
            />
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={reconciled}
              onChange={(e) => setReconciled(e.target.checked)}
            />
            我已核对原任务已结束及最终账单，明确确认本次金额
          </label>
          <div className="dialog-actions">
            <Button
              disabled={!reconciled || actual === ""}
              onClick={() =>
                void refreshResult(async () => {
                  await api("/jobs/" + reconcile.id + "/reconcile", "POST", {
                    actual_micros: Math.round(Number(actual) * 1e6),
                    explicit_confirmation: true,
                    note: "用户在本地工作台核对",
                  });
                  setReconcile(null);
                })
              }
            >
              保存对账记录
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}

function AudioEditor({
  project: p,
  settings,
  assets,
  send,
  busy,
  upload,
  openSettings,
}: {
  project: Project;
  settings: Settings;
  assets: Asset[];
  send: Send;
  busy: boolean;
  upload: (files: FileList | File[]) => Promise<void>;
  openSettings: () => void;
}) {
  const [visualsUnchanged, setVisualsUnchanged] = useState(false);
  const [audio, setAudio] = useState(p.audio),
    [dirtyKeys, setDirtyKeys] = useState<(keyof AudioPlan)[]>([]),
    [tab, setTab] = useState<"narration" | "subtitles">("narration");
  const dirty = dirtyKeys.length > 0;
  useDraftGuard("声音与字幕", dirty);
  useEffect(() => {
    setAudio((previous) => {
      const next = { ...p.audio };
      for (const key of dirtyKeys) (next as any)[key] = previous[key];
      return next;
    });
  }, [p.audio, dirtyKeys]);
  const markSaved = (key: keyof AudioPlan) =>
    setDirtyKeys((keys) => keys.filter((k) => k !== key));
  const change = (key: keyof AudioPlan, value: any) => {
    if (key === "narration") setVisualsUnchanged(false);
    setAudio((previous) => ({ ...previous, [key]: value }));
    setDirtyKeys((keys) => (keys.includes(key) ? keys : [...keys, key]));
  };
  const cues = audio[tab];
  const audios = assets.filter(
    (a) => p.asset_ids.includes(a.id) && a.mime.startsWith("audio/"),
  );
  function cueEdit(index: number, patch: Partial<Cue>) {
    const list = cues.map((c, i) => (i === index ? { ...c, ...patch } : c));
    change(tab, list);
  }
  function scriptToVoice() {
    const total = p.blocks.reduce((n, b) => n + b.text.length, 0) || 1;
    let t = 0;
    const list = p.blocks
      .filter((b) => b.text.trim())
      .map((b, i, arr) => {
        const duration =
          i === arr.length - 1
            ? p.target_duration - t
            : Math.round(((p.target_duration * b.text.length) / total) * 10) /
              10;
        const cue = {
          id: uid(),
          text: b.text,
          start: t,
          duration,
          shot_ids: [],
        };
        t += duration;
        return cue;
      });
    change("narration", list);
  }
  return (
    <section className="live-audio-editor">
      <div className="tab-row">
        <div>
          <button
            className={tab === "narration" ? "active" : ""}
            onClick={() => setTab("narration")}
          >
            旁白时间轨
          </button>
          <button
            className={tab === "subtitles" ? "active" : ""}
            onClick={() => setTab("subtitles")}
          >
            字幕时间轨
          </button>
        </div>
        <label className="btn">
          上传录音 / 配乐
          <input
            hidden
            multiple
            type="file"
            accept="audio/*"
            onChange={(e) => {
              if (e.target.files) void upload(e.target.files);
            }}
          />
        </label>
        <Button onClick={openSettings}>声音模型配置</Button>
      </div>
      <div className="inline-actions">
        {tab === "narration" ? (
          <Button onClick={scriptToVoice}>从脚本建立旁白草稿</Button>
        ) : (
          <Button
            onClick={() =>
              change(
                "subtitles",
                audio.narration.map((c) => ({ ...c, id: uid() })),
              )
            }
          >
            复制旁白为字幕草稿
          </Button>
        )}
        <Button
          onClick={() =>
            change(tab, [
              ...cues,
              { id: uid(), text: "", start: 0, duration: 5, shot_ids: [] },
            ])
          }
        >
          <Plus size={14} />
          添加一段
        </Button>
      </div>
      <Notice>
        {tab === "narration"
          ? "生成时按每段实际语音长度检查，过长则提示调整，不擅自截断台词。"
          : "字幕轨可以独立修订，保存字幕不会触发视频或配音重新生成。"}
      </Notice>
      {cues.map((cue, i) => (
        <div className="live-cue" key={cue.id}>
          <textarea
            aria-label={tab === "narration" ? "旁白文字" : "字幕文字"}
            value={cue.text}
            onChange={(e) => cueEdit(i, { text: e.target.value })}
          />
          <label>
            开始（秒）
            <input
              type="number"
              min="0"
              step="0.1"
              value={cue.start}
              onChange={(e) => cueEdit(i, { start: Number(e.target.value) })}
            />
          </label>
          <label>
            时长（秒）
            <input
              type="number"
              min="0.1"
              step="0.1"
              value={cue.duration}
              onChange={(e) => cueEdit(i, { duration: Number(e.target.value) })}
            />
          </label>
          <button
            className="text-button"
            onClick={() =>
              change(
                tab,
                cues.filter((_, j) => j !== i),
              )
            }
          >
            移除
          </button>
        </div>
      ))}
      {tab === "narration" && dirtyKeys.includes("narration") && (
        <label className="check-label">
          <input
            type="checkbox"
            checked={visualsUnchanged}
            onChange={(e) => setVisualsUnchanged(e.target.checked)}
          />
          我已核对：本次台词修改不改变已确认画面，可沿用视频制作方案
        </label>
      )}
      <div className="inline-actions">
        <span className="muted">
          {dirty ? "有未保存修改" : "当前时间轨已保存"}
        </span>
        <Button
          disabled={busy || !dirty}
          onClick={async () => {
            const r = await send("update_audio", {
              [tab]: audio[tab],
              confirm_visuals_unchanged:
                tab === "narration" && visualsUnchanged,
            });
            if (r) markSaved(tab);
          }}
        >
          保存{tab === "narration" ? "旁白" : "字幕"}修改
        </Button>
      </div>
      <div className="form-two">
        <section className="sheet">
          <h3>旁白声音</h3>
          <p className="muted">
            {settings.models.find((m) => m.id === settings.defaults.tts)
              ?.name || "尚未选择 TTS；可上传录音"}
          </p>
          {p.audio.narration_asset_id && (
            <audio controls src={fileUrl(p.audio.narration_asset_id)} />
          )}
          <label className="field">
            用本地音频作为旁白
            <select
              value={audio.narration_asset_id || ""}
              onChange={(e) => {
                const value = e.target.value || null;
                void send("update_audio", { narration_asset_id: value });
              }}
            >
              <option value="">未选录音</option>
              {audios.map((a) => (
                <option value={a.id} key={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <Button
            disabled={busy || dirty}
            onClick={() => void send("generate_tts")}
          >
            生成当前旁白
          </Button>
        </section>
        <section className="sheet">
          <h3>背景音乐</h3>
          {p.audio.music_asset_id && (
            <audio controls src={fileUrl(p.audio.music_asset_id)} />
          )}
          <label className="field">
            已授权本地配乐
            <select
              value={audio.music_asset_id || ""}
              onChange={(e) =>
                void send("update_audio", {
                  music_asset_id: e.target.value || null,
                })
              }
            >
              <option value="">不使用本地配乐</option>
              {audios.map((a) => (
                <option value={a.id} key={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            音乐生成要求
            <textarea
              value={audio.music_prompt}
              onChange={(e) => change("music_prompt", e.target.value)}
            />
          </label>
          <div className="inline-actions">
            <Button
              disabled={busy}
              onClick={async () => {
                const r = await send("update_audio", {
                  music_prompt: audio.music_prompt,
                });
                if (r) {
                  markSaved("music_prompt");
                  await send("generate_music");
                }
              }}
            >
              生成纯音乐
            </Button>
          </div>
        </section>
      </div>
      <section className="sheet">
        <div className="section-heading">
          <h3>音效与场景声音</h3>
          <Button
            disabled={!audios.length}
            onClick={() =>
              change("effects", [
                ...(audio.effects || []),
                {
                  id: uid(),
                  asset_id: audios[0].id,
                  start: 0,
                  duration: Math.min(
                    Number(audios[0].metadata.duration) || 1,
                    p.target_duration,
                  ),
                  gain: 1,
                },
              ])
            }
          >
            添加音效
          </Button>
        </div>
        {(audio.effects || []).map((effect, index) => (
          <div className="live-cue" key={effect.id}>
            <select
              value={effect.asset_id}
              onChange={(e) =>
                change(
                  "effects",
                  (audio.effects || []).map((x, i) =>
                    i === index ? { ...x, asset_id: e.target.value } : x,
                  ),
                )
              }
            >
              {audios.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
            <label>
              开始（秒）
              <input
                type="number"
                min="0"
                value={effect.start}
                onChange={(e) =>
                  change(
                    "effects",
                    (audio.effects || []).map((x, i) =>
                      i === index ? { ...x, start: Number(e.target.value) } : x,
                    ),
                  )
                }
              />
            </label>
            <label>
              时长（秒）
              <input
                type="number"
                min="0.1"
                step="0.1"
                value={effect.duration}
                onChange={(e) =>
                  change(
                    "effects",
                    (audio.effects || []).map((x, i) =>
                      i === index
                        ? { ...x, duration: Number(e.target.value) }
                        : x,
                    ),
                  )
                }
              />
            </label>
            <button
              className="text-button"
              onClick={() =>
                change(
                  "effects",
                  (audio.effects || []).filter((_, i) => i !== index),
                )
              }
            >
              移除
            </button>
          </div>
        ))}
        <Button
          disabled={busy || !dirtyKeys.includes("effects")}
          onClick={async () => {
            if (await send("update_audio", { effects: audio.effects || [] }))
              markSaved("effects");
          }}
        >
          保存音效时间轨
        </Button>
        <label className="check-label explicit-approval">
          <input
            type="checkbox"
            checked={audio.duck_music !== false}
            onChange={(e) =>
              void send("update_audio", { duck_music: e.target.checked })
            }
          />
          旁白出现时自动降低配乐
        </label>
      </section>
      <div className="live-checks">
        <label className="check-label">
          <input
            type="checkbox"
            checked={audio.allow_silent}
            onChange={(e) =>
              void send("update_audio", { allow_silent: e.target.checked })
            }
          />
          这条作品明确采用无声方案
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={!audio.mute_native_audio}
            onChange={(e) =>
              void send("update_audio", {
                mute_native_audio: !e.target.checked,
              })
            }
          />
          保留原视频中的音频
        </label>
      </div>
      <label className="field">
        配乐音量（0–1）
        <input
          type="range"
          min="0"
          max="1"
          step="0.01"
          value={audio.music_gain}
          onChange={(e) => change("music_gain", Number(e.target.value))}
        />
      </label>
      <Button
        disabled={busy}
        onClick={async () => {
          if (await send("update_audio", { music_gain: audio.music_gain }))
            markSaved("music_gain");
        }}
      >
        保存混音音量
      </Button>
    </section>
  );
}
