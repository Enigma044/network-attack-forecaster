// Types and fetch helpers for the local FastAPI server (netforecast/api.py).

export interface BinaryMetrics {
  precision: number;
  recall: number;
  f1: number;
  false_positive_rate: number;
  average_precision: number | null;
  threshold: number;
  tp: number;
  fp: number;
  tn: number;
  fn: number;
  n: number;
  positives: number;
}

export interface MetricBlock {
  world_model: BinaryMetrics;
  logistic_regression: BinaryMetrics;
  persistence_reference?: BinaryMetrics | null;
}

export interface Metrics {
  data_kind?: string;
  evaluated_on: string;
  k: number;
  targets: Record<string, MetricBlock | null>;
  onset: { any?: MetricBlock | null };
  stage_head?: { n: number; accuracy?: number; true_stage_counts?: Record<string, number>; stages_unseen_in_training?: string[] };
  test_hours?: { evaluated_on: string; n: number; targets: Record<string, MetricBlock | null>; onset: { any?: MetricBlock | null } };
}

export interface Split {
  method: string;
  train: string[];
  val: string[];
  test: string[];
  test_hours?: string[];
  note: string;
}

export interface ModelInfo {
  name: string;
  data_kind: 'synthetic' | 'external';
  created_at: string;
  window_seconds: number;
  seq_len: number;
  k: number;
  attack_fraction_threshold: number;
  target: string;
  thresholds: {
    world_model: { any: number; steps: number[] };
    logistic_regression: { any: number; steps: number[] };
  };
  threshold_source: string;
  stages_seen_in_training: string[];
  split: Split;
  training_files: string[];
  metrics: Metrics | null;
}

export interface StageRule {
  'label contains': string;
  stage: string;
  confidence: string;
  rationale: string;
}

export interface Info {
  public: boolean;
  max_upload_mb: number;
  required_columns: string[];
  optional_columns: string[];
  stage_mapping: StageRule[];
  score_note: string;
  demo_model: string;
  n_features: number;
  feature_descriptions: Record<string, string>;
}

export interface Sample {
  id: string;
  name: string;
  stem: string;
  kind: 'real' | 'synthetic';
  size_mb: number;
}

export interface Report {
  source: string;
  ok: boolean;
  errors: string[];
  warnings: string[];
  n_rows_read: number;
  n_rows_valid: number;
  columns_found: string[];
  optional_missing: string[];
  has_labels: boolean;
  data_kind: 'synthetic' | 'external';
  time_start: string | null;
  time_end: string | null;
  label_counts: Record<string, number>;
}

export interface Forecast {
  row: number;
  capture_id: string;
  input_start: string;
  input_end: string;
  forecast_start: string;
  n_future_in_data: number;
  wm_any: number;
  lr_any: number;
  wm_alert: boolean;
  lr_alert: boolean;
  peak_step: number;
  peak_p: number;
  first_step_over_threshold: number;
  stage_prob: number;
  predicted_stage: string | null;
  actual_any: number | null;
  actual_first_attack_step: number;
  actual_stage: string | null;
  now_is_attack: number | null;
}

export interface WindowRow {
  capture_id: string;
  window_start: string;
  n_flows: number;
  is_attack: number | null;
  stage: string | null;
  top_label: string | null;
}

export interface AnalysisResult {
  id: string;
  model: string;
  report: Report;
  missing_features: string[];
  has_labels: boolean;
  n_flows: number;
  forecasts: Forecast[];
  windows: WindowRow[];
  metrics: Metrics | null;
}

export interface ShapFeature {
  feature: string;
  description: string;
  group: string;
  shap_logodds: number;
  z_last: number;
  z_peak: number;
}

export interface FlowGroup {
  'Dst Port': number;
  Protocol: string;
  flows: number;
  recent: number;
  rate_recent: number;
  rate_before: number;
  growth: number;
  syn_share?: number;
  rst_share?: number;
  no_reply_share: number;
  labels?: string;
}

export interface ForecastDetail {
  row: number;
  rollout: {
    times: string[];
    world_model: number[];
    q10: number[];
    q90: number[];
    baseline: number[];
    actual: (number | null)[];
    step_thresholds: number[];
  };
  shap: { base_logodds: number; pred_logodds: number; features: ShapFeature[]; groups: { group: string; value: number }[] };
  temporal: { window_start: string; importance: number; is_attack: number | null; n_flows: number }[];
  summary: string[];
  evidence: { feature: string; description: string; points: { window_start: string; value: number }[] }[];
  flows: FlowGroup[];
  labels_in_input: Record<string, number>;
}

export class ApiError extends Error {
  report?: Report;
  constructor(message: string, report?: Report) {
    super(message);
    this.report = report;
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    if (body?.report) throw new ApiError(body.report.errors.join(' '), body.report);
    throw new ApiError(body?.detail ?? `Request failed (${res.status})`);
  }
  return body as T;
}

export const api = {
  info: () => request<Info>('/api/info'),
  models: () => request<ModelInfo[]>('/api/models'),
  samples: () => request<Sample[]>('/api/samples'),
  buildDemo: () => request<{ ok: boolean; model: string }>('/api/demo/build', { method: 'POST' }),
  analyze: (model: string, source: { file?: File; sample?: string }) => {
    const form = new FormData();
    form.append('model', model);
    if (source.file) form.append('file', source.file);
    if (source.sample) form.append('sample', source.sample);
    return request<AnalysisResult>('/api/analyze', { method: 'POST', body: form });
  },
  forecast: (id: string, row: number) => request<ForecastDetail>(`/api/forecast/${id}/${row}`)
};
