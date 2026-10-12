import { useEffect, useState } from "react";
import { Plus, Check, ExternalLink, Link2 } from "lucide-react";
import { Button, Modal, Notice, PageTitle, Tag } from "../components.tsx";
import { api } from "./api.ts";
import { uid } from "./types.ts";
import { PriceDetails, priceText } from "./Pricing.tsx";
import type { ConfigGuide } from "./Pricing.tsx";
import type { Connection, Defaults, Model, Settings } from "./types.ts";

export function LiveSettings({
  settings,
  save,
  reload,
  notify,
}: {
  settings: Settings;
  save: (s: Settings) => Promise<boolean>;
  reload: () => Promise<void>;
  notify: (s: string) => void;
}) {
  const [tab, setTab] = useState<"create" | "media" | "connections">("create");
  const [draft, setDraft] = useState(settings);
  const [edit, setEdit] = useState<Model | null>(null);
  const [connEdit, setConnEdit] = useState<Connection | null>(null);
  const [key, setKey] = useState("");
  const [codex, setCodex] = useState<{
    logged_in: boolean;
    models: { id: string; name: string }[];
    error?: string;
  }>();
  const [busy, setBusy] = useState(false);
  const [params, setParams] = useState("{}");
  useEffect(() => setDraft(settings), [settings]);
  const [guide, setGuide] = useState<ConfigGuide>();
  const [priceStatus, setPriceStatus] = useState("");
  useEffect(() => {
    api<ConfigGuide>("/configuration-guide")
      .then(setGuide)
      .catch((e) => notify(e.message));
  }, [settings.revision]);
  const origin = (m: Model) =>
    draft.connections.find((c) => c.id === m.connection_id)?.region === "cn"
      ? "cn"
      : "global";
  async function refreshPrices() {
    await run(async () => {
      setPriceStatus("正在核对官方价格与汇率…");
      const result = await api<any>("/prices/refresh", "POST");
      setGuide(result.guide);
      await reload();
      const updated = result.sources.filter((s: any) => s.ok).length;
      setPriceStatus(
        `已更新 ${updated}/${result.sources.length} 个来源；${
          result.sources
            .filter((x: any) => !x.ok)
            .map(
              (x: any) =>
                (
                  ({
                    ark: "火山方舟",
                    zhipu: "智谱",
                    kimi: "Kimi",
                    openai: "OpenAI",
                    minimax: "MiniMax",
                    runway: "Runway",
                    deepseek: "DeepSeek",
                    eleven: "ElevenLabs",
                    fx: "参考汇率",
                  }) as Record<string, string>
                )[x.provider] || x.provider,
            )
            .join("、") || "全部来源均"
        }${updated === result.sources.length ? "已核对" : "沿用上次核价，原核对日期保留"}。`,
      );
    });
  }
  async function fillRecommendations() {
    if (!guide) return;
    const next = structuredClone(draft);
    for (const role of guide.roles.filter(
      (r) => r.requirement === "required",
    )) {
      if ((next.defaults as any)[role.role]) continue;
      const id =
        role.recommended_ids.find((id) => {
          const m = next.models.find((m) => m.id === id);
          const c = next.connections.find((c) => c.id === m?.connection_id);
          return c?.has_key || c?.status === "ready";
        }) || role.recommended_ids[0];
      if (id) {
        (next.defaults as any)[role.role] = id;
        next.models.find((m) => m.id === id)!.enabled = true;
      }
    }
    if (await save(next))
      notify("已填入缺失的建议型号。现有选择保留，接下来补齐对应连接即可。");
  }
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const choose = async (role: keyof Defaults, id: string) => {
    const next = structuredClone(draft);
    (next.defaults as any)[role] = id;
    const model = next.models.find((m) => m.id === id);
    if (model) model.enabled = true;
    await save(next);
  };
  function picker(
    role: keyof Defaults,
    label: string,
    kind: Model["kind"],
    description: string,
  ) {
    const info = guide?.roles.find((r) => r.role === role);
    const selected = draft.models.find((m) => m.id === draft.defaults[role]);
    const candidates = draft.models.filter(
      (m) => m.kind === kind && (!info || info.option_ids.includes(m.id)),
    );
    return (
      <div className="live-role-card">
        <div className="live-role-card-heading">
          <h3>{label}</h3>
          <span
            className={
              "live-requirement " +
              (info?.requirement === "required" ? "required" : "")
            }
          >
            {info?.badge || "选填"}
          </span>
          <small>{info?.status}</small>
        </div>
        <p>{info?.reason || description}</p>
        <label className="field">
          <span className="sr-only">{label}模型</span>
          <select
            aria-label={label + "模型"}
            value={draft.defaults[role]}
            onChange={(e) => void choose(role, e.target.value)}
          >
            <option value="">
              {info?.requirement === "optional"
                ? "留空，按说明复用已有能力"
                : "请选择模型"}
            </option>
            {(["cn", "global"] as const).map((group) => (
              <optgroup
                key={group}
                label={group === "cn" ? "中国大陆模型" : "国际模型"}
              >
                {candidates
                  .filter((m) => origin(m) === group)
                  .map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name.replace(/\s*·\s*(订阅|API)$/, "")}
                      {info?.recommended_ids.includes(m.id)
                        ? "（建议选择）"
                        : ""}
                      {m.adapter === "codex" ? " · 订阅" : " · API"}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
        </label>
        {selected ? (
          <PriceDetails compact price={guide?.prices[selected.id]} />
        ) : (
          <small className="muted">
            建议：
            {info?.recommended_ids
              .slice(0, 3)
              .map((id) => draft.models.find((m) => m.id === id)?.name)
              .join(" / ")}
          </small>
        )}
        {selected && (
          <button className="text-button" onClick={() => editModel(selected)}>
            查看价格、能力与连接
          </button>
        )}
      </div>
    );
  }
  async function readCodex() {
    await run(async () => {
      const result = await api<any>("/codex/status");
      setCodex(result);
      await reload();
    });
  }
  async function useCodex() {
    if (!codex?.logged_in) return;
    const next = structuredClone(draft);
    const ids = codex.models.map((m) => m.id);
    const primary =
      ids.find((i) => i === "gpt-6-astra") ||
      ids.find((i) => i === "gpt-5.6-sol") ||
      ids[0];
    const economic = ids.find((i) => i === "gpt-5.6-terra") || primary;
    for (const [role, id] of Object.entries({
      director: primary,
      writer: primary,
      shot_designer: primary,
      reviewer: primary,
      executor: economic,
    })) {
      const m = next.models.find(
        (m) => m.connection_id === "codex" && m.api_model === id,
      );
      if (m) {
        m.enabled = true;
        (next.defaults as any)[role] = m.id;
      }
    }
    if (!(await save(next))) return;
    notify("已选择本机实际可用的 Codex 模型；生图与视频仍需独立配置。");
  }
  const editModel = (model: Model) => {
    setEdit(structuredClone(model));
    setParams(JSON.stringify(model.params, null, 2));
  };
  const modelRows = (kinds: Model["kind"][]) =>
    (["cn", "global"] as const).map((group) => (
      <div className="live-origin-group" key={group}>
        <h3>
          {group === "cn" ? "中国大陆模型" : "国际模型"}{" "}
          <small>可与另一组混合搭配</small>
        </h3>
        {draft.models
          .filter((m) => kinds.includes(m.kind) && origin(m) === group)
          .map((m) => (
            <div className="model-row" key={m.id}>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={m.enabled}
                  onChange={(e) => {
                    const next = structuredClone(draft);
                    next.models.find((x) => x.id === m.id)!.enabled =
                      e.target.checked;
                    void save(next);
                  }}
                />
                <span>
                  <strong>{m.name.replace(/\s*·\s*(订阅|API)$/, "")}</strong>
                  <small>
                    {
                      draft.connections.find((c) => c.id === m.connection_id)
                        ?.name
                    }{" "}
                    ·{" "}
                    {m.kind === "text"
                      ? m.vision
                        ? "多模态理解"
                        : "文本理解"
                      : m.kind === "image"
                        ? "图片生成"
                        : m.kind === "video"
                          ? "视频生成"
                          : m.kind === "tts"
                            ? "配音"
                            : "音乐"}{" "}
                    · {m.adapter === "codex" ? "订阅制" : "API 按量"}
                  </small>
                  <small>{priceText(guide?.prices[m.id])}</small>
                </span>
              </label>
              <Button onClick={() => editModel(m)}>配置与说明</Button>
            </div>
          ))}
      </div>
    ));
  return (
    <>
      <PageTitle eyebrow="MODELS & CONNECTIONS" title="一次配置，按任务分工。">
        先准备导演与高质量生图，视频与声音可以在制作前再配置。Key
        仅存放在本地后台。
      </PageTitle>
      <section className="live-setup-overview">
        <div>
          <strong>中国大陆与国际模型，自由混合搭配</strong>
          <p>先配齐 4 项创作能力；专业角色可复用，媒体能力按需补齐。</p>
        </div>
        <div className="live-setup-progress">
          <strong>
            {guide?.required_ready ?? 0}
            <small> / {guide?.required_total ?? 4}</small>
          </strong>
          <span>必配项已就绪</span>
          <Button onClick={() => void fillRecommendations()}>
            填入缺失建议
          </Button>
        </div>
      </section>
      <div className="live-price-toolbar">
        <div>
          <strong>官方价格 · 自动填入</strong>
          <small>
            {guide?.fx
              ? `人民币参考汇率：1 USD ≈ ¥${Number(guide.fx.rate).toFixed(4)} · ${guide.fx.date}`
              : "正在读取价格目录…"}
          </small>
        </div>
        <Button disabled={busy} onClick={() => void refreshPrices()}>
          从官网刷新价格
        </Button>
      </div>
      {priceStatus && <Notice>{priceStatus}</Notice>}
      <div className="tab-row">
        <div>
          <button
            className={tab === "create" ? "active" : ""}
            onClick={() => setTab("create")}
          >
            导演与生图
          </button>
          <button
            className={tab === "media" ? "active" : ""}
            onClick={() => setTab("media")}
          >
            视频与声音
          </button>
          <button
            className={tab === "connections" ? "active" : ""}
            onClick={() => setTab("connections")}
          >
            服务连接
          </button>
        </div>
      </div>
      {tab === "create" && (
        <>
          <section className="sheet">
            <div className="section-heading">
              <h2>创作角色</h2>
              <Tag>多个模型同时配置</Tag>
            </div>
            {picker("director", "导演", "text", "理解意图、提案和整体取舍")}
            {picker(
              "shot_designer",
              "镜头设计",
              "text",
              "拆镜头、写关键帧提示词",
            )}
            {picker("executor", "经济执行", "text", "已确认内容下的轻任务")}
            {picker(
              "image",
              "默认高质量生图 / 编辑",
              "image",
              "选定后在共创区直接使用",
            )}
            <details className="live-optional-roles">
              <summary>专业角色（选填，可复用上述模型）</summary>
              {picker("writer", "编剧", "text", "可共用导演")}
              {picker("reviewer", "审片", "text", "可共用视觉主力")}
            </details>
          </section>
          {
            <section className="sheet">
              <div className="section-heading">
                <h2>Sign in with ChatGPT</h2>
                <Tag>Codex 订阅通道</Tag>
              </div>
              <p className="muted">
                使用官方本地运行时。不会借用 Platform API
                Key，也不会自动充值或切换计费方式。
              </p>
              <div className="live-subscription-plans">
                {guide?.subscriptions.map((plan) => (
                  <div key={plan.name}>
                    <strong>{plan.name}</strong>
                    <span>
                      ${plan.monthly_usd}/月 · 约 ¥
                      {(
                        Number(plan.monthly_usd) * Number(guide.fx.rate)
                      ).toFixed(0)}
                      /月
                    </span>
                  </div>
                ))}
              </div>
              <p className="muted">
                已有订阅可先使用；额度不足时再考虑更高套餐。每次 Token
                使用按同型号官方 API 单价折算价值，单独统计，不重复计入实际 API
                账单或媒体预算。
              </p>
              <div className="inline-actions">
                <Button disabled={busy} onClick={readCodex}>
                  读取本机登录与可用模型
                </Button>
                {codex?.logged_in ? (
                  <Button kind="primary" onClick={() => void useCodex()}>
                    采用当前可用配置
                  </Button>
                ) : (
                  <Button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const r = await api<{ auth_url: string }>(
                          "/codex/login",
                          "POST",
                        );
                        window.open(
                          r.auth_url,
                          "_blank",
                          "noopener,noreferrer",
                        );
                        notify("请在官方页面完成登录，再点击读取本机登录。");
                      })
                    }
                  >
                    Sign in with ChatGPT
                    <ExternalLink size={14} />
                  </Button>
                )}
              </div>
              {codex && (
                <Notice>
                  {codex.logged_in
                    ? "已登录。可用模型：" +
                      codex.models.map((m) => m.name).join("、")
                    : codex.error || "尚未登录"}
                  {codex.logged_in &&
                    !codex.models.some((m) => m.id === "gpt-6-astra") &&
                    "。当前 SDK 未列出 Astra，不能将它标为已可用。"}
                </Notice>
              )}
            </section>
          }
          <section className="sheet">
            <h2>可选模型与官方价格</h2>
            {modelRows(["text", "image"])}
          </section>
        </>
      )}
      {tab === "media" && (
        <>
          <Notice>
            先确认脚本和采用图，再按镜头难度、原生规格与价格选择视频模型。图片参考不等于精确时间控制。
          </Notice>
          <section className="sheet">
            {picker(
              "video",
              "默认视频候选",
              "video",
              "系统仍会按各镜头给出路线建议",
            )}
            {picker("tts", "旁白服务", "tts", "也可以直接上传自己的录音")}
            {picker("music", "音乐生成", "music", "也可以复用本地已授权音乐")}
          </section>
          <section className="sheet">
            <h2>视频与声音模型</h2>
            {modelRows(["video", "tts", "music"])}
          </section>
        </>
      )}
      {tab === "connections" && (
        <>
          <div className="inline-actions">
            <Button
              onClick={() =>
                setConnEdit({
                  id: uid(),
                  name: "新服务",
                  base_url: "",
                  auth: "bearer",
                  region: draft.defaults.region,
                  allow_local: false,
                  status: "unconfigured",
                  has_key: false,
                  error: "",
                })
              }
            >
              <Plus size={14} />
              添加服务连接
            </Button>
            <Button
              onClick={() =>
                editModel({
                  id: uid(),
                  name: "新模型",
                  api_model: "",
                  connection_id: draft.connections[0].id,
                  kind: "text",
                  adapter: "chat",
                  tier: "primary",
                  enabled: false,
                  vision: false,
                  image_edit: false,
                  first_last: false,
                  references: false,
                  resolutions: ["720", "1080"],
                  durations: [],
                  max_reference_images: 1,
                  price_unit: "call",
                  price_cny: null,
                  price_confirmed: false,
                  price_source: "",
                  max_output_tokens: 4096,
                  params: {},
                  notes: "自定义精确型号，需验证对应能力。",
                })
              }
            >
              <Plus size={14} />
              添加模型
            </Button>
          </div>
          <section className="sheet">
            {draft.connections.map((c) => (
              <div className="connection-row" key={c.id}>
                <div className="connection-icon">
                  <Link2 size={19} />
                </div>
                <div className="connection-info">
                  <strong>
                    {c.name}{" "}
                    <small>
                      {c.region === "cn" ? "中国大陆服务" : "国际服务"}
                    </small>
                  </strong>
                  <small>
                    {c.auth === "codex"
                      ? "ChatGPT 登录"
                      : "Key " + (c.has_key ? "已保存" : "未配置")}{" "}
                    ·{" "}
                    {c.status === "ready"
                      ? "连接已验证"
                      : c.has_key
                        ? "凭据已保存，连接待验证"
                        : "待配置"}
                  </small>
                  <code>{c.base_url || "官方 Codex 本地运行时"}</code>
                  {c.error && <p className="warning-text">{c.error}</p>}
                </div>
                <div className="connection-actions">
                  <Button
                    onClick={() => {
                      setConnEdit(structuredClone(c));
                      setKey("");
                    }}
                  >
                    编辑连接
                  </Button>
                  <button
                    className="text-button"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const r = await api<any>(
                          "/connections/" + c.id + "/validate",
                          "POST",
                        );
                        notify(
                          r.connection?.error ||
                            (r.logged_in === false
                              ? "尚未登录"
                              : "连接信息已更新"),
                        );
                        await reload();
                      })
                    }
                  >
                    检查连接
                  </button>
                </div>
              </div>
            ))}
          </section>
        </>
      )}
      {edit && (
        <Modal
          title={"模型配置 · " + edit.name}
          onClose={() => setEdit(null)}
          wide
        >
          <Notice>
            {edit.notes || "按实际供应商协议、账户能力和价格配置。"}
            {edit.adapter === "codex"
              ? " 此通道使用订阅配额。"
              : " 已收录型号的官方价格由系统自动填写。"}
          </Notice>
          <div className="form-two">
            <label className="field">
              显示名称
              <input
                value={edit.name}
                onChange={(e) => setEdit({ ...edit, name: e.target.value })}
              />
            </label>
            <label className="field">
              精确 Model ID / 接入点
              <input
                value={edit.api_model}
                onChange={(e) =>
                  setEdit({ ...edit, api_model: e.target.value })
                }
              />
            </label>
            <label className="field">
              服务连接
              <select
                value={edit.connection_id}
                onChange={(e) =>
                  setEdit({ ...edit, connection_id: e.target.value })
                }
              >
                {draft.connections.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              能力类型
              <select
                value={edit.kind}
                onChange={(e) =>
                  setEdit({ ...edit, kind: e.target.value as Model["kind"] })
                }
              >
                {["text", "image", "video", "tts", "music"].map((k) => (
                  <option key={k}>{k}</option>
                ))}
              </select>
            </label>
            <label className="field">
              协议适配器
              <select
                value={edit.adapter}
                onChange={(e) => setEdit({ ...edit, adapter: e.target.value })}
              >
                {[
                  "chat",
                  "responses",
                  "messages",
                  "codex",
                  "ark_image",
                  "openai_image",
                  "minimax_image",
                  "ark_video",
                  "runway_video",
                  "minimax_video",
                  "openai_tts",
                  "minimax_tts",
                  "eleven_music",
                ].map((a) => (
                  <option key={a}>{a}</option>
                ))}
              </select>
            </label>
            <label className="field">
              质量 / 费用角色
              <select
                value={edit.tier}
                onChange={(e) =>
                  setEdit({ ...edit, tier: e.target.value as Model["tier"] })
                }
              >
                <option value="primary">主力</option>
                <option value="economy">经济</option>
                <option value="quality">高质量媒体</option>
              </select>
            </label>
          </div>
          <div className="live-checks">
            {(
              [
                "enabled",
                "vision",
                "image_edit",
                "first_last",
                "references",
              ] as const
            ).map((k, i) => (
              <label className="check-label" key={k}>
                <input
                  type="checkbox"
                  checked={edit[k]}
                  onChange={(e) => setEdit({ ...edit, [k]: e.target.checked })}
                />
                {
                  [
                    "启用模型",
                    "视觉输入",
                    "图生图 / 编辑",
                    "首尾帧控制",
                    "参考图输入",
                  ][i]
                }
              </label>
            ))}
          </div>
          <section className="live-model-price-panel">
            <h3>费用与计费方式</h3>
            <PriceDetails price={guide?.prices[edit.id]} />
            {edit.adapter === "ark_image" || edit.adapter === "ark_video" ? (
              <label className="field">
                价格对应的官方型号
                <select
                  value={edit.pricing_model || ""}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      pricing_model: e.target.value,
                      price_mode: "auto",
                    })
                  }
                >
                  <option value="">从精确模型 ID 自动识别</option>
                  {(edit.kind === "image"
                    ? [
                        "doubao-seedream-5-0-pro",
                        "doubao-seedream-4-5",
                        "doubao-seedream-5-0-lite",
                      ]
                    : [
                        "doubao-seedance-2.0-mini",
                        "doubao-seedance-2.0-fast",
                        "doubao-seedance-2.0",
                        "doubao-seedance-2.5",
                      ]
                  ).map((id) => (
                    <option key={id}>{id}</option>
                  ))}
                </select>
                <small>
                  如果使用接入点 ep-...，请选择它实际绑定的型号；无需输入价格。
                </small>
              </label>
            ) : null}
            <details>
              <summary>自定义服务或合同报价（选填）</summary>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={edit.price_mode === "manual"}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      price_mode: e.target.checked ? "manual" : "auto",
                    })
                  }
                />
                仅自定义中转或合同单价时手动覆盖
              </label>
            </details>
          </section>
          {edit.adapter !== "codex" && edit.price_mode === "manual" && (
            <section className="budget-authorize">
              <label className="field">
                供应商报价币种
                <select
                  value={edit.price_currency || "CNY"}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      price_currency: e.target.value,
                      price_confirmed: false,
                    })
                  }
                >
                  {["CNY", "USD", "JPY", "SGD"].map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </select>
              </label>
              {edit.price_currency && edit.price_currency !== "CNY" && (
                <div className="form-two">
                  <label className="field">
                    原币单价
                    <input
                      type="number"
                      min="0"
                      step="0.0001"
                      value={edit.price_native ?? ""}
                      onChange={(e) =>
                        setEdit({
                          ...edit,
                          price_native: e.target.value || null,
                          price_confirmed: false,
                        })
                      }
                    />
                  </label>
                  <label className="field">
                    1 单位原币＝多少人民币
                    <input
                      type="number"
                      min="0.000001"
                      step="0.000001"
                      value={edit.fx_rate ?? "1"}
                      onChange={(e) =>
                        setEdit({
                          ...edit,
                          fx_rate: e.target.value,
                          price_confirmed: false,
                        })
                      }
                    />
                  </label>
                  <label className="field">
                    汇率核对日期
                    <input
                      type="date"
                      value={edit.fx_date || ""}
                      onChange={(e) =>
                        setEdit({
                          ...edit,
                          fx_date: e.target.value,
                          price_confirmed: false,
                        })
                      }
                    />
                  </label>
                  <p>
                    保存时换算并保留原币信息：¥
                    {(
                      (Number(edit.price_native) || 0) *
                      (Number(edit.fx_rate) || 1)
                    ).toFixed(4)}
                  </p>
                </div>
              )}
              <div className="form-two">
                <label className="field">
                  人民币单价 / 保守费用上限
                  <input
                    type="number"
                    min="0"
                    step="0.0001"
                    value={edit.price_cny ?? ""}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        price_cny: e.target.value || null,
                        price_confirmed: false,
                      })
                    }
                  />
                </label>
                <label className="field">
                  计价单位
                  <select
                    value={edit.price_unit}
                    onChange={(e) =>
                      setEdit({
                        ...edit,
                        price_unit: e.target.value,
                        price_confirmed: false,
                      })
                    }
                  >
                    <option value="call">每次调用上限（含全部输入输出）</option>
                    <option value="image">每张图片</option>
                    <option value="second">每生成秒（按原生时长）</option>
                    <option value="1000_characters">每千字符</option>
                  </select>
                </label>
              </div>
              <label className="field">
                价格依据与核对日期
                <input
                  value={edit.price_source}
                  onChange={(e) =>
                    setEdit({ ...edit, price_source: e.target.value })
                  }
                  placeholder="例如：供应商控制台当前价格，2026-09-09"
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={edit.price_confirmed}
                  onChange={(e) =>
                    setEdit({ ...edit, price_confirmed: e.target.checked })
                  }
                />
                我已核对当前规格的价格 / 单次费用上限
              </label>
            </section>
          )}
          <details className="live-advanced">
            <summary>规格与高级参数</summary>
            {edit.kind === "text" && (
              <label className="field">
                单次输入预算（Token）
                <input
                  type="number"
                  min="1024"
                  max="1048576"
                  step="1024"
                  value={edit.max_input_tokens ?? 32768}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      max_input_tokens: Number(e.target.value),
                    })
                  }
                />
                <small>
                  用于自动预占费用；复杂内容或多张参考图可提高，实际用量另记。
                </small>
              </label>
            )}
            <div className="form-two">
              <label className="field">
                原生分辨率（逗号分隔）
                <input
                  value={edit.resolutions.join(",")}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      resolutions: e.target.value
                        .split(",")
                        .map((x) => x.trim()),
                    })
                  }
                />
              </label>
              <label className="field">
                支持的时长（空＝连续整数秒）
                <input
                  value={edit.durations.join(",")}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      durations: e.target.value
                        ? e.target.value.split(",").map(Number)
                        : [],
                    })
                  }
                />
              </label>
              <label className="field">
                最短生成秒数
                <input
                  type="number"
                  min="1"
                  value={edit.min_duration ?? 1}
                  onChange={(e) =>
                    setEdit({ ...edit, min_duration: Number(e.target.value) })
                  }
                />
              </label>
              <label className="field">
                最长生成秒数
                <input
                  type="number"
                  min="1"
                  value={edit.max_duration ?? 15}
                  onChange={(e) =>
                    setEdit({ ...edit, max_duration: Number(e.target.value) })
                  }
                />
              </label>
              <label className="field">
                最多参考图
                <input
                  type="number"
                  min="0"
                  max="16"
                  value={edit.max_reference_images}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      max_reference_images: Number(e.target.value),
                    })
                  }
                />
              </label>
              <label className="field">
                最大输出 Token
                <input
                  type="number"
                  min="128"
                  max="16384"
                  value={edit.max_output_tokens}
                  onChange={(e) =>
                    setEdit({
                      ...edit,
                      max_output_tokens: Number(e.target.value),
                    })
                  }
                />
              </label>
            </div>
            <label className="field">
              模型参数 JSON
              <textarea
                value={params}
                onChange={(e) => setParams(e.target.value)}
              />
            </label>
          </details>
          <div className="dialog-actions">
            <Button onClick={() => setEdit(null)}>取消</Button>
            <Button
              kind="primary"
              onClick={() =>
                void run(async () => {
                  const m = { ...edit, params: JSON.parse(params) };
                  const next = structuredClone(draft);
                  const i = next.models.findIndex((x) => x.id === m.id);
                  if (i < 0) next.models.push(m);
                  else next.models[i] = m;
                  if (!(await save(next))) return;
                  setEdit(null);
                })
              }
            >
              保存模型配置
            </Button>
          </div>
        </Modal>
      )}
      {connEdit && (
        <Modal
          title={connEdit.name}
          onClose={() => {
            setConnEdit(null);
            setKey("");
          }}
        >
          <label className="field">
            连接名称
            <input
              value={connEdit.name}
              onChange={(e) =>
                setConnEdit({ ...connEdit, name: e.target.value })
              }
            />
          </label>
          <label className="field">
            模型来源（仅用于列表分组）
            <select
              value={connEdit.region}
              onChange={(e) =>
                setConnEdit({
                  ...connEdit,
                  region: e.target.value as Connection["region"],
                })
              }
            >
              <option value="cn">中国大陆模型</option>
              <option value="global">国际模型</option>
            </select>
          </label>
          <label className="field">
            认证方式
            <select
              value={connEdit.auth}
              onChange={(e) =>
                setConnEdit({
                  ...connEdit,
                  auth: e.target.value as Connection["auth"],
                })
              }
            >
              {[
                "bearer",
                "api-key",
                "x-api-key",
                "xi-api-key",
                "codex",
                "none",
              ].map((a) => (
                <option key={a}>{a}</option>
              ))}
            </select>
          </label>
          {connEdit.auth !== "codex" && (
            <>
              <label className="field">
                Base URL
                <input
                  value={connEdit.base_url}
                  onChange={(e) =>
                    setConnEdit({ ...connEdit, base_url: e.target.value })
                  }
                />
              </label>
              <label className="field">
                API Key（留空保留原值）
                <input
                  type="password"
                  autoComplete="new-password"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder={
                    connEdit.has_key
                      ? "已安全保存，无法从浏览器读回"
                      : "输入服务商 API Key"
                  }
                />
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={connEdit.allow_local}
                  onChange={(e) =>
                    setConnEdit({ ...connEdit, allow_local: e.target.checked })
                  }
                />
                这是我明确配置的本地 / 私有网络模型服务
              </label>
            </>
          )}
          <div className="dialog-actions">
            <Button onClick={() => setConnEdit(null)}>取消</Button>
            <Button
              kind="primary"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  const next = structuredClone(draft);
                  const i = next.connections.findIndex(
                    (c) => c.id === connEdit.id,
                  );
                  if (i < 0) next.connections.push(connEdit);
                  else next.connections[i] = connEdit;
                  if (!(await save(next))) return;
                  if (key) {
                    await api("/connections/" + connEdit.id + "/key", "PUT", {
                      key,
                      expected_url: connEdit.base_url,
                    });
                    setKey("");
                  }
                  await reload();
                  setConnEdit(null);
                })
              }
            >
              保存连接与凭据
            </Button>
          </div>
        </Modal>
      )}
    </>
  );
}
