import { useEffect, useState } from "react";
import {
  Plus,
  Check,
  Image as ImageIcon,
  WandSparkles,
  ChevronDown,
  Trash2,
  ArrowRight,
  ArrowUp,
  ArrowDown,
} from "lucide-react";
import { Button, Modal, Notice, PageTitle, Tag } from "../components.tsx";
import { cash, fileUrl } from "./types.ts";
import type {
  Anchor,
  Asset,
  Job,
  Model,
  Project,
  ScriptBlock,
  Settings,
  Shot,
} from "./types.ts";
import { useDraftGuard } from "./drafts.tsx";
import type { Send } from "./App.tsx";

type Props = {
  project: Project;
  settings: Settings;
  assets: Asset[];
  send: Send;
  busy: boolean;
  jobs: Job[];
  select: (s: { shot_id?: string; anchor_id?: string }) => void;
  openSettings: () => void;
  upload: (files: FileList | File[]) => Promise<void>;
};
export function Creation({
  project: p,
  settings,
  assets,
  send,
  busy,
  jobs,
  select,
  openSettings,
  upload,
}: Props) {
  const [shotId, setShotId] = useState("");
  const [anchorId, setAnchorId] = useState("");
  const [confirmReplace, setConfirmReplace] = useState(false);
  const [style, setStyle] = useState(p.global_style);
  const canProceed = useDraftGuard("共同视觉风格", style !== p.global_style);
  const [remove, setRemove] = useState<{
    type: string;
    id: string;
    name: string;
  } | null>(null);
  const shot = p.shots.find((s) => s.id === shotId) || p.shots[0];
  const anchor =
    shot?.anchors.find((a) => a.id === anchorId) || shot?.anchors[0];
  const draft = jobs.find(
    (j) => j.kind === "plan_content" && j.state === "succeeded",
  );
  const activePlan = jobs.some(
    (j) =>
      j.kind === "plan_content" &&
      ["queued", "submitting", "running"].includes(j.state),
  );
  useEffect(() => {
    select({ shot_id: shot?.id, anchor_id: anchor?.id });
  }, [shot?.id, anchor?.id]);
  return (
    <>
      <PageTitle
        eyebrow="SCRIPT & VISUAL CO-CREATION"
        title="让脚本和画面，一起变好。"
      >
        完整脚本可以有多个镜头；一个镜头可以设计多个关键帧位置，每个位置单独比较候选图。
      </PageTitle>
      <div className="live-creation-actions">
        <Button
          kind="primary"
          disabled={busy || activePlan}
          onClick={() => void send("plan_content")}
        >
          {activePlan ? "编剧与镜头设计中…" : "让团队展开脚本与镜头"}
          <WandSparkles size={14} />
        </Button>
        <Button
          disabled={busy}
          onClick={() => void send("add_block", { title: "新段落", text: "" })}
        >
          <Plus size={14} />
          手动添加脚本段落
        </Button>
      </div>
      {jobs.some((j) => j.kind === "plan_content" && j.state === "failed") && (
        <Notice>
          <span>
            规划失败时可保留编剧草稿，修改后只重新生成分镜，避免重复调用编剧。
          </span>
          <Button
            disabled={busy || p.blocks.length > 0}
            onClick={() =>
              void send("recover_script", {
                job_id: jobs.find(
                  (j) => j.kind === "plan_content" && j.state === "failed",
                )!.id,
              })
            }
          >
            恢复已保存脚本
          </Button>
        </Notice>
      )}
      {p.blocks.length > 0 && (
        <Button
          disabled={busy || activePlan}
          onClick={() => void send("plan_content", { reuse_script: true })}
        >
          沿用当前脚本，只重做分镜
        </Button>
      )}
      {draft && !draft.result.auto_applied && (
        <details className="sheet live-plan-result">
          <summary>
            团队生成的创作草稿 · {draft.result.blocks?.length} 段脚本 /{" "}
            {draft.result.shots?.length} 个镜头
          </summary>
          {draft.result.normalization_notes?.length > 0 && (
            <Notice>
              {draft.result.normalization_notes.join("；")}
              。确认创作包前请核对。
            </Notice>
          )}
          {draft.result.blocks?.map((b: ScriptBlock) => (
            <div className="live-draft-block" key={b.id}>
              <h3>{b.title}</h3>
              <p>{b.text}</p>
            </div>
          ))}
          {p.blocks.length > 0 && (
            <label className="check-label">
              <input
                type="checkbox"
                checked={confirmReplace}
                onChange={(e) => setConfirmReplace(e.target.checked)}
              />
              用这版草稿替换当前内容（旧版仍保存在历史中）
            </label>
          )}
          <div className="inline-actions">
            <Button
              disabled={busy || (p.blocks.length > 0 && !confirmReplace)}
              onClick={() =>
                void send("adopt_plan", {
                  job_id: draft.id,
                  replace_existing: confirmReplace,
                })
              }
            >
              采用这版脚本与分镜
            </Button>
          </div>
        </details>
      )}
      <div className="live-creation-grid">
        <section className="live-script-column">
          <div className="section-heading">
            <h2>完整脚本</h2>
            <span className="muted">
              {p.blocks.length} 段 · {p.shots.length} 个镜头
            </span>
          </div>
          {!p.blocks.length && (
            <Notice>先由团队展开提案，或直接添加自己的脚本段落。</Notice>
          )}
          {p.blocks.map((block, i) => (
            <section className="live-block" key={block.id}>
              <BlockEditor block={block} send={send} busy={busy} />
              <div className="live-block-shots">
                {p.shots
                  .filter((s) => s.block_id === block.id)
                  .map((s) => (
                    <button
                      key={s.id}
                      className={shot?.id === s.id ? "selected" : ""}
                      onClick={() => {
                        if (!canProceed()) return;
                        setShotId(s.id);
                        setAnchorId("");
                      }}
                    >
                      <span>{s.title}</span>
                      <small>
                        {s.duration}s · {s.anchors.length} 个关键帧位置
                      </small>
                    </button>
                  ))}
              </div>
              <div className="live-add-shots">
                <span>增加分镜</span>
                {[1, 2, 3].map((n) => (
                  <button
                    key={n}
                    disabled={busy}
                    onClick={() =>
                      void send("add_shot", { block_id: block.id, count: n })
                    }
                  >
                    +{n}
                  </button>
                ))}
                <button
                  className="text-button"
                  onClick={() =>
                    setRemove({
                      type: "remove_block",
                      id: block.id,
                      name: "这段脚本及其镜头",
                    })
                  }
                >
                  移除段落
                </button>
              </div>
            </section>
          ))}
          <details className="live-advanced">
            <summary>共同视觉风格</summary>
            <textarea
              value={style}
              onChange={(e) => setStyle(e.target.value)}
            />
            <Button
              disabled={busy}
              onClick={() => void send("update_style", { text: style })}
            >
              保存共同风格
            </Button>
          </details>
          <div className="live-duration">
            <span>镜头总时长</span>
            <strong>
              {p.shots.reduce((n, s) => n + s.duration, 0)} /{" "}
              {p.target_duration} 秒
            </strong>
          </div>
        </section>
        <section className="live-shot-column">
          {shot ? (
            <>
              <ShotEditor
                key={shot.id}
                shot={shot}
                project={p}
                assets={assets}
                send={send}
                busy={busy}
                jobs={jobs}
              />
              <div className="live-shot-order">
                <Button
                  disabled={busy || p.shots.indexOf(shot) === 0}
                  onClick={() => {
                    const ids = p.shots.map((s) => s.id);
                    const i = ids.indexOf(shot.id);
                    [ids[i - 1], ids[i]] = [ids[i], ids[i - 1]];
                    void send("reorder_shots", { shot_ids: ids });
                  }}
                >
                  <ArrowUp size={13} />
                  前移
                </Button>
                <Button
                  disabled={
                    busy || p.shots.indexOf(shot) === p.shots.length - 1
                  }
                  onClick={() => {
                    const ids = p.shots.map((s) => s.id);
                    const i = ids.indexOf(shot.id);
                    [ids[i + 1], ids[i]] = [ids[i], ids[i + 1]];
                    void send("reorder_shots", { shot_ids: ids });
                  }}
                >
                  <ArrowDown size={13} />
                  后移
                </Button>
                <button
                  className="text-button"
                  onClick={() =>
                    setRemove({
                      type: "remove_shot",
                      id: shot.id,
                      name: shot.title,
                    })
                  }
                >
                  移除镜头
                </button>
              </div>
              <div className="section-heading">
                <h2>关键帧与候选</h2>
                <Button
                  disabled={busy}
                  onClick={() =>
                    void send("add_anchor", {
                      shot_id: shot.id,
                      role: "action",
                      at_seconds: shot.duration / 2,
                      prompt: shot.visual,
                    })
                  }
                >
                  <Plus size={13} />
                  增加位置
                </Button>
              </div>
              <div className="live-anchor-tabs">
                {shot.anchors.map((a, i) => (
                  <button
                    key={a.id}
                    className={anchor?.id === a.id ? "selected" : ""}
                    onClick={() => {
                      if (canProceed()) setAnchorId(a.id);
                    }}
                  >
                    <span>
                      K{i + 1} ·{" "}
                      {
                        {
                          start: "起始",
                          action: "动作",
                          end: "结束",
                          reference: "参考",
                        }[a.role]
                      }
                    </span>
                    <small>
                      {a.at_seconds}s · {a.candidates.length} 张候选{" "}
                      {p._computed?.frames[a.id] ? "· 已确认" : ""}
                    </small>
                  </button>
                ))}
              </div>
              {anchor && (
                <AnchorEditor
                  key={anchor.id}
                  anchor={anchor}
                  shot={shot}
                  project={p}
                  settings={settings}
                  assets={assets}
                  send={send}
                  busy={busy}
                  jobs={jobs}
                  upload={upload}
                  openSettings={openSettings}
                  remove={() =>
                    setRemove({
                      type: "remove_anchor",
                      id: anchor.id,
                      name: "这个关键帧位置",
                    })
                  }
                />
              )}
            </>
          ) : (
            <div className="empty">
              <ImageIcon size={28} />
              <strong>为脚本添加第一个镜头</strong>
              <p>每段可以先加 1、2 或 3 个，之后继续调整。</p>
            </div>
          )}
        </section>
      </div>
      <div className="next-action">
        <div>
          <strong>文字与采用图都确定了吗？</strong>
          <p>只有必需关键帧确认、总时长匹配后，才进入正式视频路线与报价。</p>
        </div>
        <Button
          kind="primary"
          disabled={busy || !p.shots.length}
          onClick={() => void send("approve_creative")}
        >
          确认创作包，查看制作方案
          <ArrowRight size={15} />
        </Button>
      </div>
      {remove && (
        <Modal title="确认移除当前内容" onClose={() => setRemove(null)}>
          <p>移除{remove.name}后，相关创作批准会失效；旧版和素材文件保留。</p>
          <div className="dialog-actions">
            <Button onClick={() => setRemove(null)}>取消</Button>
            <Button
              onClick={async () => {
                const field =
                  remove.type === "remove_block"
                    ? "block_id"
                    : remove.type === "remove_shot"
                      ? "shot_id"
                      : "anchor_id";
                const r = await send(remove.type, { [field]: remove.id });
                if (r) setRemove(null);
              }}
            >
              确认移除
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}

function BlockEditor({
  block,
  send,
  busy,
}: {
  block: ScriptBlock;
  send: Send;
  busy: boolean;
}) {
  const [title, setTitle] = useState(block.title),
    [text, setText] = useState(block.text),
    [dirtyKeys, setDirtyKeys] = useState<("title" | "text")[]>([]);
  const dirty = dirtyKeys.length > 0;
  useDraftGuard("脚本段落", dirty);
  useEffect(() => {
    if (!dirtyKeys.includes("title")) setTitle(block.title);
    if (!dirtyKeys.includes("text")) setText(block.text);
  }, [block, dirty]);
  return (
    <>
      <input
        className="live-block-title"
        aria-label="脚本段落标题"
        value={title}
        onChange={(e) => {
          setTitle(e.target.value);
          setDirtyKeys((keys) =>
            keys.includes("title") ? keys : [...keys, "title"],
          );
        }}
      />
      <textarea
        aria-label="脚本段落正文"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setDirtyKeys((keys) =>
            keys.includes("text") ? keys : [...keys, "text"],
          );
        }}
        placeholder="在这里写完整段落，不必为每个镜头拆成一句话…"
      />
      <div className="live-save-line">
        <small>{dirty ? "有未保存修改" : "已保存"}</small>
        <button
          className="text-button"
          disabled={busy || !dirty}
          onClick={async () => {
            if (
              await send("update_block", {
                block_id: block.id,
                ...Object.fromEntries(
                  dirtyKeys.map((k) => [k, k === "title" ? title : text]),
                ),
              })
            )
              setDirtyKeys([]);
          }}
        >
          保存段落
        </button>
      </div>
    </>
  );
}

function ShotEditor({
  shot: s,
  project: p,
  assets,
  send,
  busy,
  jobs,
}: {
  shot: Shot;
  project: Project;
  assets: Asset[];
  send: Send;
  busy: boolean;
  jobs: Job[];
}) {
  const [draft, setDraft] = useState(s),
    [dirtyKeys, setDirtyKeys] = useState<(keyof Shot)[]>([]),
    [instruction, setInstruction] = useState("");
  const dirty = dirtyKeys.length > 0;
  useDraftGuard("镜头或关键帧", dirty);
  useEffect(() => {
    setDraft((previous) => {
      const next = { ...s };
      for (const key of dirtyKeys) (next as any)[key] = previous[key];
      return next;
    });
  }, [s, dirtyKeys]);
  const refined = jobs.find(
    (j) =>
      j.kind === "refine_shot" &&
      j.target_id === s.id &&
      j.state === "succeeded",
  );
  const field = (key: keyof Shot, value: any) => {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setDirtyKeys((keys) => (keys.includes(key) ? keys : [...keys, key]));
  };
  return (
    <section className="live-shot-editor">
      <div className="eyebrow">SHOT {p.shots.indexOf(s) + 1}</div>
      <div className="form-two">
        <label className="field">
          镜头名称
          <input
            value={draft.title}
            onChange={(e) => field("title", e.target.value)}
          />
        </label>
        <label className="field">
          时长（秒）
          <input
            type="number"
            min="1"
            max="60"
            step="0.5"
            value={draft.duration}
            onChange={(e) => field("duration", Number(e.target.value))}
          />
        </label>
      </div>
      <label className="field">
        画面要求
        <textarea
          value={draft.visual}
          onChange={(e) => field("visual", e.target.value)}
          placeholder="这个镜头需要表达什么？主体、构图、景别和环境是什么？"
        />
      </label>
      <label className="field">
        动作与运镜
        <textarea
          value={draft.motion}
          onChange={(e) => field("motion", e.target.value)}
          placeholder="动作如何开始、发展和结束？与静态图片提示词分开。"
        />
      </label>
      <div className="form-two">
        <label className="field">
          场景难度
          <select
            value={draft.difficulty}
            onChange={(e) => field("difficulty", e.target.value)}
          >
            <option value="static">静态 / 原图表达</option>
            <option value="simple">简单运动</option>
            <option value="complex">复杂动作 / 主体互动</option>
          </select>
        </label>
        <label className="field">
          已有视频（可选）
          <select
            value={draft.source_video_id || ""}
            onChange={(e) => field("source_video_id", e.target.value || null)}
          >
            <option value="">使用候选图制作</option>
            {assets
              .filter(
                (a) =>
                  p.asset_ids.includes(a.id) && a.mime.startsWith("video/"),
              )
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
      </div>
      <div className="inline-actions">
        <span className="muted">
          {dirty ? "有未保存修改" : "画面要求可独立修改"}
        </span>
        <Button
          disabled={busy || !dirty}
          onClick={async () => {
            if (
              await send("update_shot", {
                shot_id: s.id,
                ...Object.fromEntries(dirtyKeys.map((k) => [k, draft[k]])),
              })
            )
              setDirtyKeys([]);
          }}
        >
          保存镜头
        </Button>
      </div>
      <details className="live-advanced">
        <summary>让镜头设计 Agent 帮我打磨</summary>
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          placeholder="例如：这个开场更有生活感，只调整构图与光线，保留人物和产品。"
        />
        <Button
          disabled={busy || dirty}
          onClick={() =>
            void send("refine_shot", { shot_id: s.id, instruction })
          }
        >
          生成镜头与提示词建议
        </Button>
        {refined && (
          <div className="live-suggestions">
            <p>{refined.result.explanation}</p>
            <strong>建议画面</strong>
            <p>{refined.result.visual}</p>
            <strong>建议动作</strong>
            <p>{refined.result.motion}</p>
            {refined.result.prompts?.map((a: any) => (
              <p key={a.anchor_id}>{a.prompt}</p>
            ))}
            <Button
              disabled={busy}
              onClick={() =>
                void send("apply_suggestion", { job_id: refined.id })
              }
            >
              采用这组建议
            </Button>
          </div>
        )}
      </details>
    </section>
  );
}

function AnchorEditor({
  anchor: a,
  shot,
  project: p,
  settings,
  assets,
  send,
  busy,
  jobs,
  upload,
  openSettings,
  remove,
}: {
  anchor: Anchor;
  shot: Shot;
  project: Project;
  settings: Settings;
  assets: Asset[];
  send: Send;
  busy: boolean;
  jobs: Job[];
  upload: (files: FileList | File[]) => Promise<void>;
  openSettings: () => void;
  remove: () => void;
}) {
  const [crop, setCrop] = useState({ x: 0, y: 0, width: 1, height: 1 });
  const [draft, setDraft] = useState(a),
    [dirtyKeys, setDirtyKeys] = useState<(keyof Anchor)[]>([]),
    [reuse, setReuse] = useState(false),
    [imageModel, setImageModel] = useState(settings.defaults.image);
  const dirty = dirtyKeys.length > 0;
  useDraftGuard("镜头或关键帧", dirty);
  useEffect(() => {
    setDraft((previous) => {
      const next = { ...a };
      for (const key of dirtyKeys) (next as any)[key] = previous[key];
      return next;
    });
  }, [a, dirtyKeys]);
  const field = (key: keyof Anchor, value: any) => {
    setDraft((previous) => ({ ...previous, [key]: value }));
    setDirtyKeys((keys) => (keys.includes(key) ? keys : [...keys, key]));
  };
  const current = a.candidates.find((c) => c.id === a.selected_id);
  const model = settings.models.find((m) => m.id === imageModel);
  const running = jobs.some(
    (j) =>
      j.target_id === a.id &&
      j.kind === "generate_image" &&
      ["queued", "submitting", "running", "downloading", "unknown"].includes(
        j.state,
      ),
  );
  const images = assets.filter(
    (asset) =>
      p.asset_ids.includes(asset.id) && asset.mime.startsWith("image/"),
  );
  const [assetChoice, setAssetChoice] = useState("");
  return (
    <section className="live-anchor-editor">
      <div className="form-two">
        <label className="field">
          关键帧作用
          <select
            value={draft.role}
            onChange={(e) => field("role", e.target.value)}
          >
            <option value="start">起始状态</option>
            <option value="action">动作节点</option>
            <option value="end">结束状态</option>
            <option value="reference">视觉参考</option>
          </select>
        </label>
        <label className="field">
          镜头内时间（秒）
          <input
            type="number"
            min="0"
            max={shot.duration}
            step="0.1"
            value={draft.at_seconds}
            onChange={(e) => field("at_seconds", Number(e.target.value))}
          />
        </label>
      </div>
      <label className="field">
        本帧图片提示词
        <textarea
          className="live-prompt"
          value={draft.prompt}
          onChange={(e) => field("prompt", e.target.value)}
          placeholder="描述这一时刻的姿态和物体状态；可以单独打磨，不必重写整个脚本。"
        />
      </label>
      <details className="live-advanced">
        <summary>
          参考图片与约束 · {draft.reference_asset_ids.length} 张参考
        </summary>
        <p>
          无参考图时为文生图；选择参考图后使用图生图 /
          编辑能力。只发送本次选择的图片。
        </p>
        <div className="live-reference-grid">
          {images.map((asset) => (
            <label key={asset.id}>
              <input
                type="checkbox"
                checked={draft.reference_asset_ids.includes(asset.id)}
                onChange={(e) =>
                  field(
                    "reference_asset_ids",
                    e.target.checked
                      ? [...draft.reference_asset_ids, asset.id]
                      : draft.reference_asset_ids.filter((i) => i !== asset.id),
                  )
                }
              />
              <img src={fileUrl(asset.id)} alt={asset.name} />
              <span>{asset.name}</span>
            </label>
          ))}
        </div>
        <label className="btn">
          上传新的参考图
          <input
            type="file"
            hidden
            accept="image/*"
            multiple
            onChange={(e) => {
              if (e.target.files) void upload(e.target.files);
            }}
          />
        </label>
        <div className="live-checks">
          <label className="check-label">
            <input
              type="checkbox"
              checked={draft.required}
              onChange={(e) => field("required", e.target.checked)}
            />
            创作包必须确认这个位置
          </label>
          <label className="check-label">
            <input
              type="checkbox"
              checked={draft.control_required}
              onChange={(e) => field("control_required", e.target.checked)}
            />
            视频必须硬控制此状态；不支持的路线不可采用
          </label>
        </div>
      </details>
      <div className="inline-actions">
        <button className="text-button" onClick={remove}>
          移除此位置
        </button>
        <Button
          disabled={busy || !dirty}
          onClick={async () => {
            const r = await send("update_anchor", {
              anchor_id: a.id,
              ...Object.fromEntries(dirtyKeys.map((k) => [k, draft[k]])),
            });
            if (r) setDirtyKeys([]);
          }}
        >
          保存提示词与参考
        </Button>
      </div>
      <div className="live-generate-row">
        <label>
          生成模型
          <select
            aria-label="关键帧生图模型"
            value={imageModel}
            onChange={(e) => setImageModel(e.target.value)}
          >
            <option value="">选择已配置生图模型</option>
            {settings.models
              .filter((m) => m.kind === "image" && m.enabled)
              .map((m) => (
                <option value={m.id} key={m.id}>
                  {m.name}
                </option>
              ))}
          </select>
        </label>
        <Button
          kind="primary"
          disabled={busy || dirty || running || !draft.prompt.trim()}
          onClick={() =>
            void send("generate_image", {
              anchor_id: a.id,
              model_id: imageModel,
            })
          }
        >
          {running ? "候选生成 / 对账中…" : "生成一张候选图"}
        </Button>
      </div>
      <div className="live-save-line">
        <small>
          {model?.price_confirmed && model.price_cny !== null
            ? "本次预估 / 上限 ¥" + model.price_cny + "，计入探索预算"
            : "价格未确认时，后端将阻止收费请求。"}
        </small>
        <button className="text-button" onClick={openSettings}>
          模型配置与说明
        </button>
      </div>
      <div className="live-candidate-grid">
        {a.candidates.map((candidate, i) => (
          <article
            className={candidate.id === a.selected_id ? "selected" : ""}
            key={candidate.id}
          >
            <a
              href={fileUrl(candidate.asset_id)}
              target="_blank"
              rel="noreferrer"
            >
              <img src={fileUrl(candidate.asset_id)} alt={"候选 " + (i + 1)} />
            </a>
            <div>
              <span>候选 {i + 1}</span>
              <small>
                {candidate.model_name ||
                  (candidate.model_id === "uploaded"
                    ? "用户素材"
                    : "真实生成产物")}
              </small>
            </div>
            <Button
              disabled={busy || candidate.id === a.selected_id}
              onClick={() =>
                void send("select_candidate", {
                  anchor_id: a.id,
                  candidate_id: candidate.id,
                })
              }
            >
              {candidate.id === a.selected_id ? "当前采用" : "选用这张"}
            </Button>
            <details>
              <summary>查看生成提示词</summary>
              <p>{candidate.prompt}</p>
            </details>
          </article>
        ))}
      </div>
      {!a.candidates.length && (
        <div className="empty">
          <ImageIcon size={25} />
          <strong>这个位置还没有候选图</strong>
          <p>按当前提示词生成，或直接采用已有图片。</p>
        </div>
      )}
      <details className="live-advanced">
        <summary>使用已有图片作为候选（不产生生成费用）</summary>
        <select
          value={assetChoice}
          onChange={(e) => setAssetChoice(e.target.value)}
        >
          <option value="">选择当前项目图片</option>
          {images.map((asset) => (
            <option key={asset.id} value={asset.id}>
              {asset.name}
            </option>
          ))}
        </select>
        <Button
          disabled={busy || !assetChoice}
          onClick={() =>
            void send("candidate_from_asset", {
              anchor_id: a.id,
              asset_id: assetChoice,
            })
          }
        >
          加入这个候选组
        </Button>
        {assetChoice && (
          <details className="live-crop-tool">
            <summary>原图局部作为关键帧 · 不重绘、不产生模型费用</summary>
            <div
              style={{
                position: "relative",
                maxWidth: 420,
                overflow: "hidden",
              }}
            >
              <img
                src={fileUrl(assetChoice)}
                alt="裁剪预览"
                style={{ width: "100%", display: "block" }}
              />
              <div
                style={{
                  position: "absolute",
                  left: crop.x * 100 + "%",
                  top: crop.y * 100 + "%",
                  width: crop.width * 100 + "%",
                  height: crop.height * 100 + "%",
                  border: "2px solid var(--accent)",
                  boxShadow: "0 0 0 2000px #0006",
                  pointerEvents: "none",
                }}
              />
            </div>
            <div className="form-two">
              {(["x", "y", "width", "height"] as const).map((k, i) => (
                <label className="field" key={k}>
                  {["左边", "上边", "宽度", "高度"][i]}（%）
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={Math.round(crop[k] * 100)}
                    onChange={(e) =>
                      setCrop({ ...crop, [k]: Number(e.target.value) / 100 })
                    }
                  />
                </label>
              ))}
            </div>
            <Button
              disabled={busy || dirty}
              onClick={() =>
                void send("crop_candidate", {
                  anchor_id: a.id,
                  asset_id: assetChoice,
                  crop,
                })
              }
            >
              裁剪后加入候选组
            </Button>
          </details>
        )}
      </details>
      {current && (
        <div className="live-anchor-approve">
          <div>
            <strong>
              {p._computed?.frames[a.id]
                ? "已确认采用图"
                : "请核对图文是否一致"}
            </strong>
            <p>
              检查主体、动作状态、光线与上下文。提示词变化后，可以明确确认沿用已有图。
            </p>
            <label className="check-label">
              <input
                type="checkbox"
                checked={reuse}
                onChange={(e) => setReuse(e.target.checked)}
              />
              如画面要求已变化，我已核对并确认沿用这张图
            </label>
          </div>
          <Button
            disabled={busy || dirty}
            onClick={() =>
              void send("approve_anchor", {
                anchor_id: a.id,
                accept_existing: reuse,
              })
            }
          >
            确认采用图
            <Check size={14} />
          </Button>
        </div>
      )}
    </section>
  );
}
