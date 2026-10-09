/**
 * TypeScript types mirroring the CardioSentry backend API contract.
 * The frontend holds NO model knowledge: labels, display names, thresholds and
 * input size all come from GET /api/config (or the response payloads).
 */

/** Normalized [0,1] point. The API represents quads as [[x,y] x4] (TL,TR,BR,BL). */
export type Point = [number, number];

// -------------------------------------------------------------------- auth
export interface AuthRequest {
  username: string;
  password: string;
}

export interface AccountUpdateRequest {
  current_password: string;
  username?: string;
  new_password?: string;
}

export interface AuthUser {
  username: string;
  is_admin?: boolean;
}

export interface LogoutResponse {
  logged_out: boolean;
}

// ---------------------------------------------------------------- health
export interface HealthResponse {
  status: string;
  model_loaded: boolean;
  active_model: string | null;
  device: string;
  torch_version: string;
  uptime_s: number;
  free_space_gb: number;
  free_space_warn: boolean;
}

/** Model input geometry as [height, width] — torch order, the same order the
 *  descriptor's `preprocess.input_size` uses. Square models report [768, 768]. */
export type ModelInputSize = [number, number];

/** What the stored capture record and the rectify response record about the input chain. */
export interface PreprocessRecord {
  input_size: ModelInputSize;
  tensor_shape: number[];
  tensor_dtype: string;
  tensor_sha256: string;
  preprocess_ms: number;
  [key: string]: unknown;
}

// ----------------------------------------------------------------- config
export interface ActiveModelConfig {
  id: string;
  display_name: string;
  version: string;
  labels: string[];
  display_names: Record<string, string>;
  suppressed_labels: string[];
  input_size: ModelInputSize;
  views: ModelInputSize[];
  checkpoint_sha256_short: string;
  thresholds: Record<string, number>;
  threshold_source: string;
}

export interface AppConfig {
  app: { version: string; git_sha: string | null };
  active_model: ActiveModelConfig;
  quality: {
    block_on_poor: boolean;
    warn_blur_varlap: number;
    warn_brightness_lo: number;
    warn_brightness_hi: number;
    warn_contrast_p5p95: number;
    warn_px_per_mm: number;
    warn_area_fraction: number;
    warn_skew_deg: number;
  };
  detection: { confidence_warn: number; expected_aspect: number | null };
  rectify: {
    canvas_px: [number, number];
    margin_px: number;
    geometry_modes: string[];
    default_geometry_mode: string;
  };
  capture: { max_upload_bytes: number; blind_mode_available: boolean };
  guidance: GuidanceConfig;
  explain: ExplainConfig;
  notice: string;
  privacy: PrivacyConfig;
}

/** Data Privacy Notice (RA 10173) — who controls the data and the text version. */
export interface PrivacyConfig {
  /** Bumped on material changes; the browser re-asks for acknowledgment. */
  notice_version: string;
  controller: string | null;
  contact: string | null;
}

export interface GuidanceConfig {
  /** True when the ACTIVE model has reviewed rules. */
  enabled: boolean;
  /** The active model's id when enabled, else null. */
  model_id: string | null;
  /** Every model with reviewed rules — older stored runs keep their guidance. */
  model_ids: string[];
  rule_version: string;
  supported_labels: string[];
  urgency_levels: UrgencyTier[];
  disclaimer: string;
}

export interface UrgencyTier {
  id: UrgencyLevel;
  label: string;
  action: string;
  description: string;
}

// ----------------------------------------------------------------- explain
export type ExplainMethod = "gradcam";

/** Whole model passes one run will cost, from GET /api/config. The UI quotes
 *  this BEFORE starting a run. */
export interface ExplainCost {
  forward: number;
  backward_full: number;
  backward_partial: number;
  note?: string;
}

export interface ExplainConfig {
  enabled: boolean;
  methods: ExplainMethod[];
  default_colormap: string;
  default_overlay_alpha: number;
  /** The printed ID/Age/Sex block as [x0, y0, x1, y1] fractions. */
  header_box: [number, number, number, number] | null;
  header_redacted_in_training: boolean;
  cost: Record<ExplainMethod, ExplainCost>;
}

/** Attribution mass inside the header box. `lift` is that fraction over the
 *  box's share of the sheet AREA: 1.0 is its fair share, 4.0 is a shortcut. */
export interface HeaderCheck {
  box: [number, number, number, number];
  box_area_frac: number;
  frac: number;
  lift: number | null;
  peak_inside: boolean;
}

export interface MapSummary {
  empty: boolean;
  centroid_xy: [number, number] | null;
  peak_xy: [number, number] | null;
  peak_value: number | null;
  /** Smallest fraction of the sheet holding half the attribution mass. */
  mass_half_area_frac: number | null;
}

export interface LabelAttribution {
  label: string;
  display_name: string;
  score: number | null;
  threshold: number | null;
  positive: boolean | null;
  stats: Record<string, number | boolean | null>;
  summary: MapSummary;
  header: HeaderCheck | null;
  normalization: Record<string, unknown>;
  files: { heatmap?: string; overlay?: string };
}

export interface ExplainResponse {
  explain_id: string;
  capture_id: string;
  method: ExplainMethod;
  model: ModelRunInfo;
  run_id: string | null;
  labels: string[];
  attributions: LabelAttribution[];
  meta: Record<string, unknown>;
  timing_ms: Record<string, number>;
  created_utc: string;
  model_input_sha256: string;
  caveats: string[];
}

export interface ExplainSummary {
  explain_id: string;
  /** A string, not ExplainMethod: older captures can hold runs of methods
   *  since removed (integrated_gradients, jacobian). */
  method: string;
  model_id: string;
  created_utc: string;
  labels: string[];
  run_id: string | null;
  /** The capture was re-rectified: this map explains pixels it no longer has. */
  stale: boolean;
  max_header_frac: number | null;
  thumbnail_url: string | null;
}

export interface ExplainListResponse {
  capture_id: string;
  explanations: ExplainSummary[];
  total: number;
}

export interface ExplainRequest {
  method: ExplainMethod;
  model_id?: string | null;
  labels?: string[] | null;
  target_layer?: string | null;
  colormap?: string | null;
  overlay_alpha?: number | null;
  run_id?: string | null;
}

// ----------------------------------------------------------------- models
export interface ModelListItem {
  id: string;
  display_name: string;
  version: string;
  notes: string;
  labels: string[];
  model_labels: string[];
  suppressed_labels: string[];
  views: ModelInputSize[];
  call_style: string;
  input_size: ModelInputSize;
  checkpoint_sha256_short: string;
  weights: string;
  active: boolean;
  loaded: boolean;
}

export interface ModelsResponse {
  models: ModelListItem[];
  active_id: string;
}

// ----------------------------------------------------------------- quality
export interface QualityMetrics {
  level: "ok" | "warn" | "poor";
  blur_varlap: number | null;
  brightness: number | null;
  contrast_p5p95: number | null;
  clipped_high_frac: number | null;
  clipped_low_frac: number | null;
  glare_blob_frac: number | null;
  est_px_per_mm: number | null;
  area_fraction: number | null;
  skew_deg: number | null;
  grid_period_px: number | null;
  grid_detected: boolean | null;
  flags: string[];
}

// ---------------------------------------------------------------- detection
export interface DetectionInfo {
  attempted?: boolean;
  success: boolean;
  method: string;
  confidence: number;
  quad_auto_px: Point[] | null;
  quad_norm: Point[] | null;
  area_fraction: number | null;
  aspect_ratio: number | null;
  params: Record<string, unknown>;
  score_breakdown: Record<string, unknown>;
}

// ----------------------------------------------------------------- original
export interface OriginalInfo {
  width: number;
  height: number;
  oriented_width: number;
  oriented_height: number;
  sha256: string;
  uploaded_sha256?: string;
  bytes: number;
  format: string;
  exif_orientation?: number;
  orientation_applied?: boolean;
  exif_gps_present?: boolean;
  gps_stripped?: boolean;
  [key: string]: unknown;
}

// --------------------------------------------------------------- upload 201
export interface CaptureUploadResponse {
  capture_id: string;
  original: OriginalInfo;
  detection: DetectionInfo;
  quality: QualityMetrics;
  files: { preview: string; overlay: string };
}

// ----------------------------------------------------------------- rectify
export interface RectifyResponse {
  capture_id: string;
  corrected_px: [number, number];
  geometry_mode: string;
  mean_corner_shift_px: number | null;
  quality: QualityMetrics;
  preprocess: PreprocessRecord;
  files: { corrected: string; model_input: string };
}

// ---------------------------------------------------------------- prediction
export interface ModelRunInfo {
  id: string;
  display_name: string;
  version: string;
  checkpoint_sha256: string;
  checkpoint_sha256_short: string;
  protocol_fingerprint: string | null;
  epoch: number | null;
  weight_source?: string | null;
  views: ModelInputSize[];
  input_size: ModelInputSize;
  device: string;
  dtype: string;
  amp: boolean;
  torch_num_threads: number | null;
}

export interface PredictionResponse {
  run_id: string;
  capture_id: string;
  model: ModelRunInfo;
  scores: Record<string, number>;
  logits: Record<string, number>;
  thresholds: Record<string, number>;
  threshold_source: string;
  positive: string[];
  timing_ms: { preprocess: number; forward: number; total: number };
  created_utc: string;
  model_input_sha256: string;
}

export interface PredictionRecord extends PredictionResponse {
  schema_version: number;
  descriptor_snapshot?: {
    labels?: string[];
    display_names?: Record<string, string>;
    [key: string]: unknown;
  };
  env: Record<string, unknown>;
}

// ------------------------------------------------------ clinical guidance
export type AgeGroup = "under_18" | "18_64" | "65_74" | "75_plus" | "unknown";
export type GuidanceSymptom =
  | "chest_pain"
  | "severe_shortness_of_breath"
  | "fainting"
  | "palpitations"
  | "dizziness"
  | "stroke_signs";
export type GuidanceRiskFactor =
  | "heart_failure"
  | "hypertension"
  | "diabetes"
  | "prior_stroke_tia"
  | "vascular_disease"
  | "known_heart_disease";
/** Four tiers of increasing urgency; Green is reserved for a Normal read. */
export type UrgencyLevel = "green" | "yellow" | "orange" | "red";

export interface GuidanceRequest {
  run_id: string;
  age_group?: AgeGroup;
  symptoms?: GuidanceSymptom[];
  risk_factors?: GuidanceRiskFactor[];
  context_complete?: boolean;
}

export interface GuidanceSource {
  id: string;
  title: string;
  organization: string;
  url: string;
}

export interface FindingGuidance {
  finding: string;
  display_name: string;
  /** The condition's own baseline tier, before symptoms and combinations. */
  tier: UrgencyLevel;
  summary: string;
  next_steps: string[];
  source_ids: string[];
}

export interface GuidanceResponse {
  rule_version: string;
  cautions: string[];
  model_id: string;
  run_id: string;
  detected_findings: string[];
  abnormal_findings: string[];
  urgency_level: UrgencyLevel;
  urgency_label: string;
  urgency_action: string;
  urgency_description: string;
  headline: string;
  reasons: string[];
  recommended_next_steps: string[];
  safety_net: string;
  context: {
    age_group: AgeGroup;
    symptoms: GuidanceSymptom[];
    risk_factors: GuidanceRiskFactor[];
    complete: boolean;
  };
  context_note: string;
  finding_guidance: FindingGuidance[];
  combination_notes: string[];
  sources: GuidanceSource[];
  disclaimer: string;
}

// ---------------------------------------------------------------- annotation
export interface AnnotationRecord {
  reference_labels: Record<string, boolean> | null;
  labels_entered_utc: string | null;
  labels_entered_before_prediction: boolean | null;
  truth_source: string | null;
  notes: string;
  device_vendor: string;
  paper_size: string;
}

export interface AnnotationRequest {
  reference_labels?: Record<string, boolean> | null;
  labels_entered_before_prediction?: boolean | null;
  truth_source?: string | null;
  notes?: string | null;
  sheet_id?: string | null;
  device_vendor?: string | null;
  paper_size?: string | null;
}

// ----------------------------------------------------------------- correction
export interface CorrectionInfo {
  quad_final_px: Point[] | null;
  quad_auto_px: Point[] | null;
  corners_manually_adjusted: boolean;
  mean_corner_shift_px: number | null;
  source: string;
  geometry_mode: string;
  homography: number[][] | null;
  warp_interpolation: string;
  canvas_px: number[] | null;
  margin_px: number | null;
  paper_fill_rgb: number[] | null;
  corrected_px: number[] | null;
  est_px_per_mm_original: number | null;
  scale_factor_to_input?: number | null;
}

// ------------------------------------------------------------- capture record
export interface CaptureRecord {
  schema_version: number;
  capture_id: string;
  owner?: string | null;
  created_utc: string;
  app: Record<string, unknown>;
  session: {
    sheet_id?: string | null;
    retake_of?: string | null;
    blind_mode?: boolean;
    notes?: string;
    [key: string]: unknown;
  };
  source: {
    mode?: string;
    declared_filename?: string;
    client_ua?: string;
    [key: string]: unknown;
  };
  original: OriginalInfo;
  quality_original: QualityMetrics | null;
  detection: DetectionInfo | null;
  correction: CorrectionInfo | null;
  preprocess: PreprocessRecord | null;
  quality_model_input: QualityMetrics | null;
  annotation: AnnotationRecord;
  predictions: string[];
  explanations?: string[];
  prediction_runs?: PredictionRecord[];
}

// ------------------------------------------------------------------ history
export interface CaptureSummary {
  capture_id: string;
  created_utc: string;
  sheet_id: string | null;
  thumbnail_url: string | null;
  has_correction: boolean;
  latest_model_id: string | null;
  latest_positive: string[];
  quality_level: string;
}

export interface CaptureListResponse {
  captures: CaptureSummary[];
  page: number;
  total: number;
  has_more: boolean;
}

// ---------------------------------------------------------------- requests
export interface RectifyRequest {
  quad_norm: Point[];
  source: "auto" | "manual";
  geometry_mode: "training_canvas";
}

export interface PredictRequest {
  model_id?: string | null;
  thresholds?: Record<string, number> | null;
}

export interface DeleteResponse {
  capture_id: string;
  trashed: string;
}
