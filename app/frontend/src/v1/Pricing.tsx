import type { Model } from "./types.ts";
export type PriceView = {
  known: boolean;
  source_url?: string;
  fetched_at?: string;
  unit?: string;
  currency?: string;
  rates?: Record<string, string>;
  rates_cny?: Record<string, string>;
  promo_until?: string;
  promo_active?: boolean;
  fx_rate?: string;
  fx_date?: string;
  sample_micros?: number | null;
  sample_duration?: number;
  notes?: string;
  billing?: string;
  message?: string;
};
export type RoleGuide = {
  role: string;
  label: string;
  kind: Model["kind"];
  requirement: string;
  badge: string;
  reason: string;
  recommended_ids: string[];
  option_ids: string[];
  selected: string;
  ready: boolean;
  status: string;
};
export type ConfigGuide = {
  roles: RoleGuide[];
  required_ready: number;
  required_total: number;
  prices: Record<string, PriceView>;
  fx: { rate: string; date: string; source: string };
  subscriptions: { name: string; monthly_usd: string; source_url: string }[];
  refresh_status: { provider: string; ok: boolean; message?: string }[];
};
const money = (value: unknown) =>
  "¥" +
  Number(value || 0).toLocaleString("zh-CN", { maximumFractionDigits: 4 });
export function priceText(p?: PriceView) {
  if (!p?.known) return "官方报价待匹配";
  const r = p.rates_cny || {};
  if (p.unit === "call") return money(r.per_call) + " / 次（自定义费用上限）";
  if (p.unit === "tokens")
    return `输入 ${money(r.input)} · 缓存 ${money(r.cached)} · 输出 ${money(r.output)} / 百万 Token`;
  if (p.unit === "image")
    return r.large_image
      ? `输出 ${money(r.per_image)}–${money(r.large_image)} / 张 · 额外参考 ${money(r.reference_image)} / 张`
      : `${money(r.per_image)} / 张`;
  if (p.unit === "video_tokens")
    return (
      Object.entries(r)
        .filter(([k]) => /^(480|720|1080)$/.test(k))
        .map(([k, v]) => `${k}P ${money(v)}`)
        .join(" · ") + " / 百万视频 Token"
    );
  if (p.unit === "video_clip")
    return Object.entries(r)
      .map(([k, v]) => `${k.replace("_", "P / ")}s ${money(v)}`)
      .join(" · ");
  if (p.unit === "second") return money(r.per_second) + " / 秒";
  if (p.unit === "1000_characters") return money(r.per_1000) + " / 千字符";
  if (p.unit === "image_tokens")
    return `文字输入 ${money(r.input)} · 图片输入 ${money(r.image_input)} · 图片输出 ${money(r.output)} / 百万 Token`;
  if (p.unit === "tts_tokens")
    return `文字输入 ${money(r.input)} · 音频输出 ${money(r.output)} / 百万 Token`;
  return "按官方规格计价";
}
export function PriceDetails({
  price: p,
  compact = false,
}: {
  price?: PriceView;
  compact?: boolean;
}) {
  if (!p?.known)
    return (
      <p className="muted">
        尚未匹配官方精确型号。系统保留配置，不把未知价格当作免费；无需填写主流预设价格。
      </p>
    );
  return (
    <div className={"live-price-details " + (compact ? "compact" : "")}>
      <strong>
        {p.billing === "subscription"
          ? "订阅 · API 等价参考"
          : p.billing === "manual"
            ? "自定义报价"
            : "API 按量计费"}
        {p.promo_active && <span className="live-price-promo">限时优惠</span>}
      </strong>
      <p>{priceText(p)}</p>
      {p.sample_micros != null && (
        <small>
          {p.unit === "call"
            ? "每次调用上限"
            : p.unit === "tokens"
              ? "参考任务：1 万输入 + 2 千输出 Token"
              : p.unit === "1000_characters"
                ? "参考：1 千字符"
                : p.unit === "image" || p.unit === "image_tokens"
                  ? "当前图片规格的预算估算"
                  : `参考：${p.sample_duration || 5} 秒`}{" "}
          ≈ {money(p.sample_micros / 1e6)}
          {p.billing === "subscription" ? "（折算价值，非 API 实扣）" : ""}
        </small>
      )}
      {!compact && p.notes && <small>{p.notes}</small>}
      {p.promo_active && p.promo_until && (
        <small>
          优惠截止{" "}
          {new Date(p.promo_until).toLocaleString("zh-CN", {
            timeZone: "Asia/Shanghai",
          })}
          （北京时间）；到期自动使用标准价。
        </small>
      )}
      {!compact && p.source_url && (
        <small>
          <a href={p.source_url} target="_blank" rel="noreferrer">
            官方价格来源 ↗
          </a>{" "}
          · 核对 {p.fetched_at?.slice(0, 10)}
          {p.currency === "USD"
            ? ` · 1 USD ≈ ¥${Number(p.fx_rate).toFixed(4)}（${p.fx_date}）`
            : ""}
        </small>
      )}
    </div>
  );
}
