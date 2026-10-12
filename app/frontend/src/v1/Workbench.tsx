import { useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  ArrowDown,
  ArrowUp,
  Clapperboard,
  FileText,
  Film,
  RotateCcw,
  Scissors,
  Upload,
  WandSparkles,
  Layers,
  Check,
} from "lucide-react";
import { Button, Modal, Notice, Tag } from "../components.tsx";
import { api } from "./api.ts";
import { fileUrl, cash } from "./types.ts";
import type {
  Asset,
  Project,
  Shot,
  Job,
  TranscriptSegment,
  Transcript,
} from "./types.ts";
import type { Send } from "./App.tsx";
import { jobState } from "./App.tsx";
import { DraftContext, useDraftGuard } from "./drafts.tsx";

const time = (s: number) =>
  `${Math.floor(s / 60)
    .toString()
    .padStart(2, "0")}:${(s % 60).toFixed(2).padStart(5, "0")}`;

export function ContextNotes({
  p,
  send,
  busy,
}: {
  p: Project;
  send: Send;
  busy: boolean;
}) {
  const [text, setText] = useState(p.context_notes || "");
  useEffect(() => setText(p.context_notes || ""), [p.context_notes]);
  useDraftGuard("项目上下文", text !== (p.context_notes || ""));
  return (
    <>
      {(p.workbench_version || 1) < 2 && (
        <div className="v12-context">
          <small>此作品保留旧版生成行为。</small>
          <Button
            disabled={busy}
            onClick={() => void send("upgrade_workbench")}
          >
            启用候选式编辑
          </Button>
        </div>
      )}
      <History p={p} send={send} busy={busy} />
      <details className="v12-context">
        <summary>品牌 / IP 上下文</summary>
        <label>
          必须保留的事实与表达
          <textarea
            aria-label="项目上下文"
            rows={5}
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="商品事实、品牌风格、本人语气、术语和不能改动的内容…"
          />
        </label>
        <Button
          disabled={busy || text === (p.context_notes || "")}
          onClick={() => void send("update_context", { text })}
        >
          保存上下文
        </Button>
      </details>
    </>
  );
}

export function ProposalList({
  p,
  send,
  busy,
}: {
  p: Project;
  send: Send;
  busy: boolean;
}) {
  const items = (p.edit_proposals || []).filter((e) => e.status === "proposed");
  if (!items.length) return null;
  return (
    <section className="v12-proposals">
      <div className="section-heading">
        <h2>导演的修改提案</h2>
        <Tag>{items.length} 项待审阅</Tag>
      </div>
      {items
        .slice()
        .reverse()
        .map((e) => (
          <article key={e.id}>
            <small>
              {e.kind === "shot" ? "镜头" : "文稿"} ·{" "}
              {e.skill_id ? `${e.skill_id} ${e.skill_version}` : "导演建议"}
            </small>
            <p>{e.summary}</p>
            <ul>
              {e.impacts.map((x, i) => (
                <li key={i}>{x}</li>
              ))}
            </ul>
            <details>
              <summary>查看修改内容</summary>
              <div>
                {e.kind === "transcript" ? (
                  <p>
                    保留 {(e.changes.keep_ids as string[])?.length || 0}{" "}
                    个段落，其余标为剪除；应用后仍需确认剪辑。
                  </p>
                ) : (
                  Object.entries(e.changes).map(([key, value]) => (
                    <p key={key}>
                      <strong>
                        {{
                          visual: "画面",
                          motion: "动作",
                          title: "标题",
                          duration: "时长",
                          prompts: "关键帧提示词",
                        }[key] || "镜头要求"}
                        ：
                      </strong>
                      {Array.isArray(value)
                        ? value.map((x: any) => x.prompt || "").join("；")
                        : typeof value === "object"
                          ? "更新镜头能力要求"
                          : String(value)}
                    </p>
                  ))
                )}
              </div>
            </details>
            <div className="inline-actions">
              <Button
                kind="primary"
                disabled={busy}
                onClick={() => void send("apply_edit", { proposal_id: e.id })}
              >
                应用提案
              </Button>
              <Button
                disabled={busy}
                onClick={() => void send("reject_edit", { proposal_id: e.id })}
              >
                保留原内容
              </Button>
            </div>
          </article>
        ))}
    </section>
  );
}

export function VideoCandidates({
  shot,
  send,
  busy,
}: {
  shot: Shot;
  send: Send;
  busy: boolean;
}) {
  const [restore, setRestore] = useState<string | null>(null);
  if (!shot.video_candidates?.length) return null;
  return (
    <details className="v12-candidates" open>
      <summary>视频候选与历史 · {shot.video_candidates.length}</summary>
      <div className="v12-candidate-grid">
        {shot.video_candidates
          .slice()
          .reverse()
          .map((v) => (
            <article key={v.id}>
              <video controls preload="metadata" src={fileUrl(v.asset_id)} />
              <div className="section-heading">
                <small>
                  {v.model_id} ·{" "}
                  {new Date(v.created_at * 1000).toLocaleTimeString()}
                </small>
                {shot.selected_video_id === v.id && (
                  <Tag tone="good">已采用</Tag>
                )}
              </div>
              <div className="inline-actions">
                <Button
                  disabled={busy || shot.selected_video_id === v.id}
                  onClick={() =>
                    void send("adopt_video_candidate", {
                      shot_id: shot.id,
                      candidate_id: v.id,
                    })
                  }
                >
                  采用候选
                </Button>
                <Button disabled={busy} onClick={() => setRestore(v.id)}>
                  <RotateCcw size={13} />
                  恢复镜头并采用
                </Button>
              </div>
            </article>
          ))}
      </div>
      {restore && (
        <Modal title="恢复这个候选对应的镜头" onClose={() => setRestore(null)}>
          <p>
            恢复当时的画面、动作与输入版本。其他镜头保留；制作路线将需要重新确认，现有费用不变。
          </p>
          <Button
            kind="primary"
            onClick={async () => {
              if (
                await send("adopt_video_candidate", {
                  shot_id: shot.id,
                  candidate_id: restore,
                  restore_design: true,
                })
              )
                setRestore(null);
            }}
          >
            恢复并采用
          </Button>
        </Modal>
      )}
    </details>
  );
}

function RangeEditor({
  p,
  shot,
  assets,
  send,
  busy,
}: {
  p: Project;
  shot: Shot;
  assets: Asset[];
  send: Send;
  busy: boolean;
}) {
  const ranges = p.source_ranges || [];
  const current = ranges.find((r) => r.id === shot.source_range_id);
  const media = assets.filter(
    (a) => p.asset_ids.includes(a.id) && /^(video|audio)\//.test(a.mime),
  );
  const [assetId, setAsset] = useState(
    current?.asset_id || shot.source_video_id || media[0]?.id || "",
  );
  const [touched, setTouched] = useState(false);
  useDraftGuard("源区间", touched);
  const [start, setStart] = useState(current?.start || 0);
  const [end, setEnd] = useState(current?.end || shot.duration);
  useEffect(() => {
    setAsset(current?.asset_id || shot.source_video_id || media[0]?.id || "");
    setStart(current?.start || 0);
    setEnd(current?.end || shot.duration);
    setTouched(false);
  }, [current?.id, current?.start, current?.end, shot.source_video_id]);
  const selected = media.find((a) => a.id === assetId);
  return (
    <details className="v12-range">
      <summary>
        <Scissors size={14} /> 从原片选择可用区间
      </summary>
      <div className="v12-range-fields">
        <label>
          源素材
          <select
            aria-label="源素材"
            value={assetId}
            onChange={(e) => {
              setAsset(e.target.value);
              setTouched(true);
            }}
          >
            <option value="">选择原片或录音</option>
            {media.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          开始（秒）
          <input
            aria-label="区间开始"
            type="number"
            min="0"
            step="0.01"
            value={start}
            onChange={(e) => {
              setStart(Number(e.target.value));
              setTouched(true);
            }}
          />
        </label>
        <label>
          结束（秒）
          <input
            aria-label="区间结束"
            type="number"
            min="0"
            step="0.01"
            value={end}
            onChange={(e) => {
              setEnd(Number(e.target.value));
              setTouched(true);
            }}
          />
        </label>
      </div>
      {selected &&
        (selected.mime.startsWith("video/") ? (
          <video
            controls
            preload="metadata"
            src={`${fileUrl(assetId)}#t=${start},${end}`}
          />
        ) : (
          <audio controls src={`${fileUrl(assetId)}#t=${start},${end}`} />
        ))}
      <small>源时间与成片时间分别保存；原片不改动，画面和原声同步裁切。</small>
      <Button
        disabled={busy || !assetId || end <= start}
        onClick={async () => {
          if (
            await send("save_source_range", {
              shot_id: shot.id,
              range: {
                ...(current ? { id: current.id } : {}),
                asset_id: assetId,
                start,
                end,
                label: shot.title,
                status: "usable",
              },
            })
          )
            setTouched(false);
        }}
      >
        采用这个源区间
      </Button>
    </details>
  );
}

function Requirements({
  shot,
  send,
  busy,
}: {
  shot: Shot;
  send: Send;
  busy: boolean;
}) {
  const empty = {
    product_fidelity: false,
    identity: false,
    action: "",
    audio: "post" as const,
    notes: "",
  };
  const [req, setReq] = useState(shot.requirements || empty);
  const [group, setGroup] = useState(shot.continuity_group || "");
  useEffect(() => {
    setReq(shot.requirements || empty);
    setGroup(shot.continuity_group || "");
  }, [shot.id, JSON.stringify(shot.requirements), shot.continuity_group]);
  const dirty =
    JSON.stringify(req) !== JSON.stringify(shot.requirements || empty) ||
    group !== (shot.continuity_group || "");
  useDraftGuard("镜头能力要求", dirty);
  return (
    <details className="v12-requirements">
      <summary>这段画面需要什么能力</summary>
      <div className="inline-actions">
        <label>
          <input
            type="checkbox"
            checked={req.product_fidelity}
            onChange={(e) =>
              setReq({ ...req, product_fidelity: e.target.checked })
            }
          />
          重点检查商品保真
        </label>
        <label>
          <input
            type="checkbox"
            checked={req.identity}
            onChange={(e) => setReq({ ...req, identity: e.target.checked })}
          />
          人物身份一致
        </label>
      </div>
      <label>
        动作难点
        <input
          value={req.action}
          onChange={(e) => setReq({ ...req, action: e.target.value })}
          placeholder="例如：手握杯把、倒液体、跨镜头连续动作"
        />
      </label>
      <label>
        连续性组
        <input
          value={group}
          onChange={(e) => setGroup(e.target.value)}
          placeholder="例如：同一人物 / 同一场景 A"
        />
      </label>
      <label>
        必须保留的细节
        <input
          value={req.notes}
          onChange={(e) => setReq({ ...req, notes: e.target.value })}
          placeholder="商品文字、服装、方向、光线等"
        />
      </label>
      <label>
        声音要求
        <select
          value={req.audio}
          onChange={(e) =>
            setReq({ ...req, audio: e.target.value as typeof req.audio })
          }
        >
          <option value="post">后配旁白 / 保留原声</option>
          <option value="native_dialogue">
            必须原生对白（当前接口未接通）
          </option>
        </select>
      </label>
      <Button
        disabled={busy || !dirty}
        onClick={() =>
          void send("update_shot", {
            shot_id: shot.id,
            requirements: req,
            continuity_group: group,
          })
        }
      >
        保存能力要求
      </Button>
    </details>
  );
}

export function MediaWorkbench({
  p,
  assets,
  send,
  busy,
  select,
  children,
}: {
  p: Project;
  assets: Asset[];
  send: Send;
  busy: boolean;
  select: (x: { shot_id?: string; anchor_id?: string }) => void;
  children: ReactNode;
}) {
  const { canProceed } = useContext(DraftContext);
  const [id, setId] = useState(p.shots[0]?.id || "");
  const s = p.shots.find((s) => s.id === id) || p.shots[0];
  const [instruction, setInstruction] = useState(
    "保留商品与人物，改善这个镜头的动作和画面表达",
  );
  useEffect(() => {
    if (s) select({ shot_id: s.id });
  }, [s?.id]);
  const imageId = s?.anchors.flatMap((a) =>
    a.candidates.filter((c) => c.id === a.selected_id).map((c) => c.asset_id),
  )[0];
  return (
    <>
      <div className="v12-heading">
        <div>
          <span className="eyebrow">SCRIPT TO SCREEN</span>
          <h1>让想法成为画面。</h1>
          <p>选择一个镜头，与导演一起打磨。</p>
        </div>
        <Tag>{p.shots.length} 个镜头</Tag>
      </div>
      {s && (
        <>
          <div className="v12-hero">
            {s.clip_asset_id ? (
              <video controls src={fileUrl(s.clip_asset_id)} />
            ) : imageId ? (
              <img src={fileUrl(imageId)} alt={s.title} />
            ) : (
              <div className="v12-empty">
                <Clapperboard size={34} />
                <p>选定关键帧后，在这里比较画面。</p>
              </div>
            )}
            <div className="v12-hero-caption">
              <strong>{s.title}</strong>
              <span>
                {s.duration.toFixed(2)} 秒 ·{" "}
                {s.clip_asset_id
                  ? p._computed?.clips[s.id]
                    ? "当前采用视频"
                    : "旧版采用 · 待重新制作"
                  : "关键帧共创"}
              </span>
            </div>
          </div>
          <div className="v12-filmstrip">
            {p.shots.map((shot, i) => {
              const image = shot.anchors.flatMap((a) =>
                a.candidates
                  .filter((c) => c.id === a.selected_id)
                  .map((c) => c.asset_id),
              )[0];
              return (
                <button
                  key={shot.id}
                  className={shot.id === s.id ? "selected" : ""}
                  onClick={() => {
                    if (!canProceed()) return;
                    setId(shot.id);
                    select({ shot_id: shot.id });
                  }}
                >
                  {image ? (
                    <img src={fileUrl(image)} alt="" />
                  ) : shot.clip_asset_id ? (
                    <video
                      muted
                      preload="metadata"
                      src={fileUrl(shot.clip_asset_id)}
                    />
                  ) : (
                    <Film size={23} />
                  )}
                  <strong>
                    {String(i + 1).padStart(2, "0")} · {shot.title}
                  </strong>
                  <small>{shot.duration.toFixed(2)} 秒</small>
                </button>
              );
            })}
          </div>
          <div className="v12-shot-action">
            <label>
              这次只修改这个镜头
              <input
                aria-label="镜头修改要求"
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
              />
            </label>
            <Button
              kind="primary"
              disabled={busy}
              onClick={() =>
                void send("run_skill", {
                  skill_id: "brand-shot",
                  shot_id: s.id,
                  instruction,
                })
              }
            >
              <WandSparkles size={15} />
              让导演提出修改
            </Button>
          </div>
          <Requirements key={"req-" + s.id} shot={s} send={send} busy={busy} />
          <RangeEditor
            key={"range-" + s.id}
            p={p}
            shot={s}
            assets={assets}
            send={send}
            busy={busy}
          />
          <VideoCandidates shot={s} send={send} busy={busy} />
        </>
      )}
      <ProposalList p={p} send={send} busy={busy} />
      <details className="v12-creation-detail" open={!s}>
        <summary>完整脚本、分镜与关键帧编辑</summary>
        {children}
      </details>
    </>
  );
}

function Segment({
  seg,
  t,
  send,
  busy,
  onSeek,
}: {
  seg: TranscriptSegment;
  t: Transcript;
  send: Send;
  busy: boolean;
  onSeek: () => void;
}) {
  const [text, setText] = useState(seg.text);
  useEffect(() => setText(seg.text), [seg.text]);
  useDraftGuard("转写文字", text !== seg.text);
  const at = t.segments.findIndex((x) => x.id === seg.id);
  function move(delta: number) {
    const ids = t.segments.map((s) => s.id);
    [ids[at], ids[at + delta]] = [ids[at + delta], ids[at]];
    void send("reorder_transcript", { transcript_id: t.id, segment_ids: ids });
  }
  return (
    <article className={`v12-segment ${seg.included ? "" : "excluded"}`}>
      <div className="v12-segment-meta">
        <button onClick={onSeek}>
          {time(seg.start)}–{time(seg.end)}
        </button>
        <label>
          <input
            type="checkbox"
            checked={seg.included}
            disabled={busy}
            onChange={(e) =>
              void send("update_transcript_segment", {
                transcript_id: t.id,
                segment_id: seg.id,
                included: e.target.checked,
              })
            }
          />
          {seg.included ? "保留" : "剪除原片"}
        </label>
        <button
          aria-label="段落上移"
          disabled={busy || at === 0}
          onClick={() => move(-1)}
        >
          <ArrowUp size={14} />
        </button>
        <button
          aria-label="段落下移"
          disabled={busy || at === t.segments.length - 1}
          onClick={() => move(1)}
        >
          <ArrowDown size={14} />
        </button>
      </div>
      <textarea
        aria-label={`段落文字 ${at + 1}`}
        rows={Math.min(8, Math.max(2, Math.ceil(text.length / 22)))}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      {text !== seg.text && (
        <Button
          disabled={busy}
          onClick={() =>
            void send("update_transcript_segment", {
              transcript_id: t.id,
              segment_id: seg.id,
              text,
            })
          }
        >
          保存字幕文字（不改原声）
        </Button>
      )}
      <SegmentBounds seg={seg} tid={t.id} send={send} busy={busy} />
      {seg.text !== seg.original_text && (
        <details>
          <summary>原始转写</summary>
          <p>{seg.original_text}</p>
        </details>
      )}
    </article>
  );
}

export function TranscriptStudio({
  p,
  assets,
  send,
  busy,
  jobs,
  upload,
  select,
}: {
  p: Project;
  assets: Asset[];
  send: Send;
  busy: boolean;
  jobs: Job[];
  upload: (f: FileList | File[]) => Promise<void>;
  select: (x: { transcript_id?: string }) => void;
}) {
  const media = assets.filter(
    (a) => p.asset_ids.includes(a.id) && /^(video|audio)\//.test(a.mime),
  );
  const [source, setSource] = useState(
    p.transcripts?.at(-1)?.asset_id || media[0]?.id || "",
  );
  const [tid, setTid] = useState("");
  const [cap, setCap] = useState<any>();
  const [error, setError] = useState("");
  const [replace, setReplace] = useState(false);
  const [instruction, setInstruction] = useState(
    "保留核心观点、限定条件和自然语气，建议剪除重复表达",
  );
  const player = useRef<HTMLVideoElement>(null);
  const audio = useRef<HTMLAudioElement>(null);
  const t =
    p.transcripts?.find((t) => t.id === tid) ||
    p.transcripts?.filter((t) => t.asset_id === source).at(-1);
  const asset = media.find((a) => a.id === (t?.asset_id || source));
  useEffect(() => {
    api("/capabilities")
      .then(setCap)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!source && media[0]) setSource(media[0].id);
  }, [media.length]);
  useEffect(() => select({ transcript_id: t?.id }), [t?.id]);
  const active = jobs.some(
    (j) =>
      j.kind === "transcribe" &&
      ["queued", "running", "submitting"].includes(j.state),
  );
  const total =
    t?.segments
      .filter((s) => s.included)
      .reduce((sum, s) => sum + s.end - s.start, 0) || 0;
  async function apply() {
    const unrelated = p.shots.some(
      (s) =>
        !s.id.startsWith("shot-") ||
        !t?.segments.some((seg) => "shot-" + seg.id === s.id),
    );
    if (unrelated) {
      setReplace(true);
      return;
    }
    await send("apply_transcript", { transcript_id: t!.id });
  }
  return (
    <>
      <div className="v12-heading">
        <div>
          <span className="eyebrow">YOUR VOICE, YOUR STORY</span>
          <h1>保留你的观点，剪出清晰表达。</h1>
          <p>文稿连接原片。改字幕、剪内容，是两个明确的动作。</p>
        </div>
      </div>
      {error && <Notice>{error}</Notice>}
      <div className="v12-import">
        <label className="btn">
          <Upload size={15} />
          导入原片或录音
          <input
            hidden
            type="file"
            accept="video/*,audio/*"
            multiple
            onChange={(e) => {
              if (e.target.files) void upload(e.target.files);
            }}
          />
        </label>
        <select
          aria-label="转写源素材"
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            setTid("");
          }}
        >
          <option value="">选择转写素材</option>
          {media.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <Button
          kind="primary"
          disabled={busy || active || !source || !cap?.asr?.ready}
          onClick={() => void send("transcribe", { asset_id: source })}
        >
          {active ? "本地转写中…" : "本地转写"}
        </Button>
        <label className="btn">
          导入 SRT
          <input
            hidden
            type="file"
            accept=".srt"
            disabled={!source || busy}
            onChange={async (e) => {
              const f = e.target.files?.[0];
              if (f)
                await send("import_transcript", {
                  asset_id: source,
                  srt: await f.text(),
                });
            }}
          />
        </label>
      </div>
      <small className="v12-local-note">
        {cap?.asr?.note || "正在检查本地转写能力…"}
      </small>
      {jobs
        .filter((j) => j.kind === "transcribe")
        .slice(0, 2)
        .map((j) => (
          <Notice key={j.id}>
            转写任务：{j.state === "cancel_requested" ? "正在停止本地任务" : jobState(j.state)}
            {j.error ? " · " + j.error : ""}
          </Notice>
        ))}
      {t ? (
        <>
          <div className="v12-transcript-toolbar">
            <select
              aria-label="转写版本"
              value={t.id}
              onChange={(e) => {
                setTid(e.target.value);
              }}
            >
              {p.transcripts
                ?.filter((x) => x.asset_id === source)
                .map((x, i) => (
                  <option key={x.id} value={x.id}>
                    转写 {i + 1} · {x.engine}
                  </option>
                ))}
            </select>
            <Tag>保留 {total.toFixed(2)} 秒</Tag>
            <Button
              kind="primary"
              disabled={busy || total === 0}
              onClick={() => void apply()}
            >
              <Scissors size={14} />
              应用到剪辑
            </Button>
          </div>
          <div className="v12-transcript-grid">
            <section>
              {t.segments.map((seg) => (
                <Segment
                  key={seg.id}
                  seg={seg}
                  t={t}
                  send={send}
                  busy={busy}
                  onSeek={() => {
                    const el = player.current || audio.current;
                    if (el) el.currentTime = seg.start;
                  }}
                />
              ))}
            </section>
            <aside>
              {asset?.mime.startsWith("video/") ? (
                <video
                  ref={player}
                  key={asset.id}
                  controls
                  src={fileUrl(asset.id)}
                />
              ) : (
                asset && (
                  <audio
                    ref={audio}
                    key={asset.id}
                    controls
                    src={fileUrl(asset.id)}
                  />
                )
              )}
              <small>原片定位 · 与成片时间分别保存</small>
              <label>
                交给导演的要求
                <textarea
                  rows={4}
                  value={instruction}
                  onChange={(e) => setInstruction(e.target.value)}
                />
              </label>
              <Button
                disabled={busy}
                onClick={() =>
                  void send("run_skill", {
                    skill_id: "ip-rough-cut",
                    transcript_id: t.id,
                    instruction,
                  })
                }
              >
                <WandSparkles size={14} />
                生成粗剪提案
              </Button>
              <p>提案只改变段落选择。审阅后再应用到剪辑，原片始终保留。</p>
            </aside>
          </div>
          <ProposalList p={p} send={send} busy={busy} />
          {p.shots.length > 0 && (
            <div className="next-action">
              <span>
                {p.shots.length} 个剪辑片段 · {p.target_duration.toFixed(2)} 秒
              </span>
              <Button
                kind="primary"
                disabled={busy}
                onClick={() => void send("approve_creative")}
              >
                确认剪辑，查看制作路线
              </Button>
            </div>
          )}
        </>
      ) : (
        <div className="v12-empty">
          <FileText size={34} />
          <h2>从一段真实表达开始。</h2>
          <p>上传访谈、口播或录音，生成可定位的文稿，再决定保留什么。</p>
        </div>
      )}
      {replace && (
        <Modal title="替换当前剪辑结构" onClose={() => setReplace(false)}>
          <p>
            将按这份文稿重新建立剪辑。原始素材和项目历史保留，当前其他镜头将从本次剪辑中移除。
          </p>
          <Button
            kind="primary"
            onClick={async () => {
              if (
                await send("apply_transcript", {
                  transcript_id: t!.id,
                  replace_existing: true,
                })
              )
                setReplace(false);
            }}
          >
            确认替换
          </Button>
        </Modal>
      )}
    </>
  );
}

export function CapabilityPanel() {
  const [data, setData] = useState<any>();
  const [error, setError] = useState("");
  useEffect(() => {
    api("/capabilities")
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);
  return (
    <section className="v12-capabilities">
      <div className="v12-heading">
        <div>
          <span className="eyebrow">CAPABILITIES & SKILLS</span>
          <h1>方法有边界，工具有依据。</h1>
          <p>只加载当前任务需要的能力，所有动作经过同一权限与预算入口。</p>
        </div>
      </div>
      {error && <Notice>{error}</Notice>}
      <Button
        onClick={() => {
          api("/capabilities")
            .then(setData)
            .catch((e) => setError(e.message));
        }}
      >
        刷新本机能力状态
      </Button>
      {data && (
        <>
          <Notice>
            {data.asr.name} · {data.asr.ready ? "已就绪" : "未就绪"} ·{" "}
            {data.asr.note}
          </Notice>
          <div className="v12-skill-grid">
            {data.skills.map((s: any) => (
              <article key={s.id}>
                <Layers size={22} />
                <h2>{s.name}</h2>
                <Tag>{s.version}</Tag>
                <p>输入：{s.input}</p>
                <p>输出：{s.output}</p>
                <small>{s.permissions}</small>
              </article>
            ))}
          </div>
          <details>
            <summary>模型能力与验证状态</summary>
            <div className="v12-model-list">
              {data.models.map((m: any) => (
                <div key={m.id}>
                  <strong>{m.name}</strong>
                  <span>
                    {m.api_model || "待填精确型号"} · {m.connection_status}
                  </span>
                  <small>{m.boundary}</small>
                  <span>
                    采用记录：{m.adoption_samples?.length || 0} 个素材
                  </span>
                  {m.evidence?.map((e: any, i: number) => (
                    <p key={i}>
                      {e.source || "评测来源"} · 样本{" "}
                      {e.sample_count ?? "未披露"} ·{" "}
                      {e.collected_at || "日期待补充"}
                      {e.url && /^https?:\/\//.test(e.url) && (
                        <a href={e.url} target="_blank" rel="noreferrer">
                          {" "}
                          查看来源
                        </a>
                      )}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          </details>
        </>
      )}
    </section>
  );
}

function History({ p, send, busy }: { p: Project; send: Send; busy: boolean }) {
  const [versions, setVersions] = useState<
    { revision: number; created: number; shots: number }[]
  >([]);
  const [selected, setSelected] = useState("");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  return (
    <details
      className="v12-context"
      onToggle={(e) => {
        if (e.currentTarget.open)
          api<typeof versions>(`/projects/${p.id}/revisions`)
            .then(setVersions)
            .catch((e) => setError(e.message));
      }}
    >
      <summary>版本历史与恢复</summary>
      {error && <p>{error}</p>}
      <select
        aria-label="历史内容版本"
        value={selected}
        onChange={(e) => setSelected(e.target.value)}
      >
        <option value="">选择历史版本</option>
        {versions
          .filter((v) => v.revision !== p.revision)
          .map((v) => (
            <option key={v.revision} value={v.revision}>
              v{v.revision} · {v.shots} 镜头 ·{" "}
              {new Date(v.created * 1000).toLocaleTimeString()}
            </option>
          ))}
      </select>
      <Button disabled={!selected || busy} onClick={() => setConfirm(true)}>
        恢复内容…
      </Button>
      {confirm && (
        <Modal
          title={`恢复到内容版本 v${selected}`}
          onClose={() => setConfirm(false)}
        >
          <p>
            恢复这个版本的完整脚本、镜头、转写选择与声音计划。保留原始素材、当前历史和全部费用记录。恢复后需要重新确认制作与交付。
          </p>
          <Button
            kind="primary"
            disabled={busy}
            onClick={async () => {
              if (
                await send("restore_content_revision", {
                  revision: Number(selected),
                })
              )
                setConfirm(false);
            }}
          >
            恢复这个内容版本
          </Button>
        </Modal>
      )}
    </details>
  );
}

function SegmentBounds({
  seg,
  tid,
  send,
  busy,
}: {
  seg: TranscriptSegment;
  tid: string;
  send: Send;
  busy: boolean;
}) {
  const [start, setStart] = useState(seg.start);
  const [end, setEnd] = useState(seg.end);
  useEffect(() => {
    setStart(seg.start);
    setEnd(seg.end);
  }, [seg.start, seg.end]);
  const dirty = start !== seg.start || end !== seg.end;
  useDraftGuard("句段边界", dirty);
  return (
    <details>
      <summary>调整句段边界</summary>
      <div className="v12-range-fields">
        <label>
          开始（秒）
          <input
            aria-label={`段落开始 ${seg.id}`}
            type="number"
            step="0.01"
            value={start}
            onChange={(e) => setStart(Number(e.target.value))}
          />
        </label>
        <label>
          结束（秒）
          <input
            aria-label={`段落结束 ${seg.id}`}
            type="number"
            step="0.01"
            value={end}
            onChange={(e) => setEnd(Number(e.target.value))}
          />
        </label>
      </div>
      <p>这会改变要保留的原片范围；保存后点击“应用到剪辑”才更新声音和画面。</p>
      <Button
        disabled={busy || !dirty || end <= start || start < 0}
        onClick={() =>
          void send("update_transcript_segment", {
            transcript_id: tid,
            segment_id: seg.id,
            start,
            end,
          })
        }
      >
        保存句段边界
      </Button>
    </details>
  );
}
