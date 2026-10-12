export type Connection = {
  id: string;
  name: string;
  base_url: string;
  auth: "bearer" | "api-key" | "x-api-key" | "xi-api-key" | "codex" | "none";
  region: "cn" | "global";
  allow_local: boolean;
  status: string;
  has_key: boolean;
  error: string;
  checked_at?: number;
};
export type Model = {
  id: string;
  name: string;
  api_model: string;
  connection_id: string;
  kind: "text" | "image" | "video" | "tts" | "music";
  adapter: string;
  tier: "primary" | "economy" | "quality";
  enabled: boolean;
  vision: boolean;
  image_edit: boolean;
  first_last: boolean;
  references: boolean;
  resolutions: string[];
  durations: number[];
  min_duration?: number;
  max_duration?: number;
  max_reference_images: number;
  price_mode?: "auto" | "manual";
  pricing_model?: string;
  pricing?: unknown;
  max_input_tokens?: number;
  price_unit: string;
  price_cny: string | null;
  price_currency?: string;
  price_native?: string | null;
  fx_rate?: string;
  fx_date?: string;
  price_confirmed: boolean;
  price_source: string;
  max_output_tokens: number;
  params: Record<string, unknown>;
  notes: string;
};
export type Defaults = {
  region: "cn" | "global";
  director: string;
  writer: string;
  shot_designer: string;
  executor: string;
  reviewer: string;
  image: string;
  tts: string;
  music: string;
  video: string;
};
export type Settings = {
  revision?: number;
  connections: Connection[];
  models: Model[];
  defaults: Defaults;
};
export type Candidate = {
  id: string;
  asset_id: string;
  prompt_hash: string;
  prompt: string;
  model_id: string;
  model_name?: string;
  api_model?: string;
  task_id: string;
  created_at: number;
};
export type Anchor = {
  id: string;
  role: "start" | "action" | "end" | "reference";
  at_seconds: number;
  prompt: string;
  required: boolean;
  control_required: boolean;
  reference_asset_ids: string[];
  candidates: Candidate[];
  selected_id: string | null;
  approved_hash: string | null;
};
export type Shot = {
  source_range_id?: string | null;
  requirements?: {
    product_fidelity: boolean;
    identity: boolean;
    action: string;
    audio: "post" | "native_dialogue";
    notes: string;
  };
  video_candidates?: VideoCandidate[];
  selected_video_id?: string | null;
  id: string;
  block_id: string;
  title: string;
  duration: number;
  visual: string;
  motion: string;
  difficulty: "static" | "simple" | "complex";
  continuity_group: string;
  anchors: Anchor[];
  source_video_id: string | null;
  clip_asset_id: string | null;
  clip_input_hash: string | null;
};
export type ScriptBlock = {
  id: string;
  title: string;
  text: string;
  purpose: string;
};
export type Cue = {
  id: string;
  text: string;
  start: number;
  duration: number;
  shot_ids: string[];
};
export type Effect = {
  id: string;
  asset_id: string;
  start: number;
  duration: number;
  gain: number;
};
export type AudioPlan = {
  effects?: Effect[];
  duck_music?: boolean;
  narration: Cue[];
  subtitles: Cue[];
  voice: string;
  narration_asset_id: string | null;
  narration_hash: string | null;
  music_asset_id: string | null;
  music_prompt: string;
  music_gain: number;
  mute_native_audio: boolean;
  allow_silent: boolean;
};
export type RouteItem = {
  alternatives?: {
    model_id: string;
    name: string;
    cost_micros: number;
    native_duration: number;
  }[];
  exclusions?: { model_id: string; name: string; reason: string }[];
  checks?: string[];
  shot_id: string;
  method: "local" | "reuse" | "generate";
  model_id: string;
  native_duration: number;
  resolution: string;
  local_motion?: "none" | "push_in";
  anchor_usage: Record<string, string>;
  reason: string;
  estimated_micros: number;
  deployment_hash: string;
};
export type Route = {
  mode: "economy" | "balanced" | "quality";
  resolution: string;
  items: RouteItem[];
  creative_hash: string;
  approved_hash: string | null;
  approved_at: number | null;
};
export type Issue = {
  id: string;
  start: number;
  end: number;
  shot_id: string | null;
  category: string;
  severity: "blocker" | "warning" | "note";
  description: string;
  evidence_asset_ids: string[];
  status: "open" | "resolved" | "accepted";
  source: string;
  resolution_note: string;
};
export type Stage = "idea" | "create" | "route" | "video" | "audio" | "review";
export type Project = {
  workbench_version?: number;
  context_notes?: string;
  source_ranges?: SourceRange[];
  transcripts?: Transcript[];
  edit_proposals?: EditProposal[];
  id: string;
  name: string;
  revision: number;
  category: "commerce" | "creator";
  region: "cn" | "global";
  brief: string;
  audience: string;
  target_duration: number;
  aspect: "9:16" | "16:9" | "1:1";
  proposal: string;
  proposal_approved_hash: string | null;
  blocks: ScriptBlock[];
  shots: Shot[];
  audio: AudioPlan;
  asset_ids: string[];
  global_style: string;
  creative_approved_hash: string | null;
  route: Route;
  stage: Stage;
  preview_asset_id: string | null;
  render_hash: string | null;
  final_approved_hash: string | null;
  review_issues: Issue[];
  messages: {
    id: string;
    role: string;
    text: string;
    question?: string;
    models?: string[];
    job_id?: string;
  }[];
  created_at: number;
  updated_at: number;
  _computed?: {
    frames: Record<string, boolean>;
    clips: Record<string, boolean>;
    creative_current: boolean;
    route_current: boolean;
    render_current: boolean;
    final_current: boolean;
  };
};
export type Asset = {
  id: string;
  name: string;
  mime: string;
  size: number;
  hash: string;
  metadata: Record<string, unknown>;
  created: number;
};
export type Job = {
  models?: { id: string; name: string; api_model: string }[];
  id: string;
  project_id: string;
  kind: string;
  target_id: string | null;
  state: string;
  error: string | null;
  external_id: string | null;
  result: Record<string, any>;
  created: number;
  updated: number;
};
export type Budget = {
  subscription_equivalent?: { micros: number; missing_calls: number };
  tokens?: {
    input: number;
    output: number;
    cached_input: number;
    total: number;
    calls_with_usage: number;
    calls_missing_usage: number;
  };
  demo_limit: number;
  total_limit: number;
  cognitive_limit: number;
  include_demo: number;
  paused: number;
  demo: { spent: number; reserved: number };
  media: { spent: number; reserved: number };
  cognitive: { spent: number; reserved: number };
  attempts: {
    id: string;
    job_id: string;
    category: string;
    phase: string;
    reserved: number;
    settled: number | null;
    state: string;
    settlement_kind: string | null;
  }[];
};
export type Bootstrap = {
  version: string;
  csrf: string;
  data_dir: string;
  vault: string;
  mode: string;
  event_cursor?: number;
};
export const cash = (micros: number) => `¥${(micros / 1_000_000).toFixed(2)}`;
export const fileUrl = (id?: string | null) =>
  id ? `/api/assets/${id}/file` : "";
export const uid = () => crypto.randomUUID().replaceAll("-", "");
export const phases: { id: Stage; name: string }[] = [
  { id: "idea", name: "导演共创" },
  { id: "create", name: "脚本与画面" },
  { id: "route", name: "制作方案与费用" },
  { id: "video", name: "视频制作" },
  { id: "audio", name: "声音制作" },
  { id: "review", name: "审片与交付" },
];

export type SourceRange = {
  id: string;
  asset_id: string;
  start: number;
  end: number;
  label: string;
  status: "pending" | "usable" | "rejected";
};
export type VideoCandidate = {
  id: string;
  asset_id: string;
  source_asset_id: string | null;
  task_id: string;
  model_id: string;
  input_hash: string;
  created_at: number;
};
export type TranscriptSegment = {
  id: string;
  start: number;
  end: number;
  original_text: string;
  text: string;
  included: boolean;
};
export type Transcript = {
  id: string;
  asset_id: string;
  language: string;
  engine: string;
  segments: TranscriptSegment[];
  applied_hash: string | null;
  job_id: string;
};
export type EditProposal = {
  id: string;
  kind: "shot" | "transcript";
  target_id: string;
  source_hash: string;
  changes: Record<string, unknown>;
  summary: string;
  impacts: string[];
  status: string;
  skill_id: string | null;
  skill_version: string | null;
};
