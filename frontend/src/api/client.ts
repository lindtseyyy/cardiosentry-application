/**
 * Typed API client for CardioSentry. Every error response is {code, message};
 * we surface the server's message text and fall back to a friendly message per
 * code. Uploads use XMLHttpRequest (fetch has no upload progress).
 */
import type {
  AccountUpdateRequest,
  AnnotationRequest,
  AppConfig,
  AuthRequest,
  AuthUser,
  CaptureListResponse,
  CaptureRecord,
  CaptureUploadResponse,
  DeleteResponse,
  ExplainListResponse,
  ExplainRequest,
  ExplainResponse,
  GuidanceRequest,
  GuidanceResponse,
  HealthResponse,
  LogoutResponse,
  ModelsResponse,
  Point,
  PredictRequest,
  PredictionResponse,
  RectifyRequest,
  RectifyResponse,
} from "./types";

export const AUTH_REQUIRED_EVENT = "cardiosentry:auth-required";

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

const FALLBACKS: Record<string, string> = {
  AUTH_REQUIRED: "Sign in to continue.",
  INVALID_CREDENTIALS: "Wrong username or password.",
  WRONG_PASSWORD: "Current password is incorrect.",
  USERNAME_TAKEN: "That username is already taken.",
  INVALID_USERNAME: "Use 3–32 letters, numbers, dots, dashes or underscores.",
  INVALID_PASSWORD: "Use a password with 8–128 characters.",
  UNSUPPORTED_FORMAT: "That file isn't a JPEG or PNG.",
  CORRUPT_IMAGE: "The photo didn't upload completely — try again.",
  IMAGE_TOO_LARGE: "That image is too large to upload.",
  STORAGE_FULL: "Out of disk space — free some space and retry.",
  INVALID_QUAD: "Those corners cross over — reset and try again.",
  UNKNOWN_LABEL: "Unknown label sent to the server.",
  THRESHOLD_OUT_OF_RANGE: "Thresholds must be between 0 and 1.",
  UNKNOWN_MODEL: "That model isn't available on the server.",
  CAPTURE_NOT_FOUND: "That capture no longer exists.",
  MISSING_MODEL_INPUT: "Rectify this capture before running the model.",
  INFERENCE_FAILED: "Inference failed — you can retry.",
  RECTIFY_FAILED: "Rectification failed.",
  UNAUTHORIZED: "Not authorized — check the app token.",
  INTERNAL_ERROR: "Something went wrong on the server.",
  FRONTEND_NOT_BUILT: "The frontend isn't built on the server.",
  UNKNOWN_FILE: "That file isn't available for this capture.",
  BAD_PAGE: "Invalid page number.",
  EXPLAIN_DISABLED: "Explainability is switched off on this server.",
  EXPLAIN_UNSUPPORTED: "This model doesn't support attribution maps.",
  EXPLAIN_NOT_FOUND: "That attribution run no longer exists.",
  EXPLAIN_FAILED: "Building the attribution map failed — you can retry.",
  EXPLAIN_OUT_OF_MEMORY:
    "Out of memory building the map — try fewer labels.",
  EXPLAIN_INSUFFICIENT_MEMORY:
    "Not enough free memory for Grad-CAM right now — close something and retry.",
  UNKNOWN_TARGET_LAYER: "That layer doesn't exist in this model.",
  UNKNOWN_METHOD: "Unknown explainability method.",
  TOO_MANY_EXPLAIN_RUNS: "This capture already has too many attribution runs.",
  RUN_MODEL_MISMATCH: "That prediction run came from a different model.",
  RUN_NOT_FOUND: "That prediction run no longer exists.",
  GUIDANCE_UNSUPPORTED_MODEL:
    "Urgency guidance is not reviewed for the model that produced this run.",
  GUIDANCE_RUN_INCOMPATIBLE:
    "This prediction run does not contain the data needed for safe guidance.",
  EMPTY_UPLOAD: "The upload was empty.",
  NETWORK_ERROR: "Backend unreachable — is the server running?",
};

/** The human-facing message for an error: server text first, friendly fallback second. */
export function friendlyMessage(code: string, serverMessage?: string): string {
  if (serverMessage && serverMessage.trim().length > 0) return serverMessage;
  return FALLBACKS[code] ?? "Something went wrong.";
}

export function isApiError(e: unknown): e is ApiError {
  return e instanceof ApiError;
}

function parseErrorBody(status: number, body: unknown): ApiError {
  if (body && typeof body === "object") {
    const b = body as { code?: unknown; message?: unknown };
    const code = typeof b.code === "string" && b.code ? b.code : "INTERNAL_ERROR";
    const message = typeof b.message === "string" ? b.message : "";
    if (code === "AUTH_REQUIRED") window.dispatchEvent(new Event(AUTH_REQUIRED_EVENT));
    return new ApiError(status, code, friendlyMessage(code, message));
  }
  return new ApiError(status, "INTERNAL_ERROR", friendlyMessage("INTERNAL_ERROR"));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError(0, "NETWORK_ERROR", friendlyMessage("NETWORK_ERROR"));
  }
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error body */
    }
    throw parseErrorBody(res.status, body);
  }
  const ct = res.headers.get("content-type") ?? "";
  if (res.status === 204) return undefined as T;
  if (ct.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

function jsonInit(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export interface UploadOptions {
  file: File;
  sheetId?: string;
  notes?: string;
  retakeOf?: string;
  blindMode?: boolean;
  mode?: "upload" | "camera";
  /** Data Privacy Notice version acknowledged before this upload. */
  privacyNotice?: string;
  onProgress?: (loaded: number, total: number) => void;
}

/** Upload the raw File object as-is (no client-side image processing). */
export function uploadCapture(opts: UploadOptions): Promise<CaptureUploadResponse> {
  return new Promise<CaptureUploadResponse>((resolve, reject) => {
    const form = new FormData();
    form.append("file", opts.file, opts.file.name);
    if (opts.sheetId) form.append("sheet_id", opts.sheetId);
    if (opts.notes) form.append("notes", opts.notes);
    if (opts.retakeOf) form.append("retake_of", opts.retakeOf);
    form.append("blind_mode", opts.blindMode ? "true" : "false");
    form.append("mode", opts.mode ?? "upload");
    if (opts.privacyNotice) form.append("privacy_notice", opts.privacyNotice);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/captures");
    xhr.responseType = "json";

    xhr.upload.onprogress = (e: ProgressEvent) => {
      if (e.lengthComputable && opts.onProgress) {
        opts.onProgress(e.loaded, e.total);
      }
    };

    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as CaptureUploadResponse);
      } else {
        reject(parseErrorBody(xhr.status, xhr.response));
      }
    };

    xhr.onerror = () => {
      reject(new ApiError(0, "NETWORK_ERROR", friendlyMessage("NETWORK_ERROR")));
    };
    xhr.ontimeout = () => {
      reject(new ApiError(0, "NETWORK_ERROR", "Upload timed out — try again."));
    };

    xhr.send(form);
  });
}

export const api = {
  me: () => request<AuthUser>("/api/auth/me"),
  login: (body: AuthRequest) =>
    request<AuthUser>("/api/auth/login", jsonInit("POST", body)),
  register: (body: AuthRequest) =>
    request<AuthUser>("/api/auth/register", jsonInit("POST", body)),
  logout: () => request<LogoutResponse>("/api/auth/logout", { method: "POST" }),
  updateAccount: (body: AccountUpdateRequest) =>
    request<AuthUser>("/api/auth/account", jsonInit("PATCH", body)),

  getHealth: () => request<HealthResponse>("/api/health"),
  getConfig: () => request<AppConfig>("/api/config"),
  getModels: () => request<ModelsResponse>("/api/models"),

  listCaptures: (page = 1) =>
    request<CaptureListResponse>(`/api/captures?page=${page}`),
  getCapture: (id: string) =>
    request<CaptureRecord>(`/api/captures/${encodeURIComponent(id)}`),

  rectify: (id: string, quad: Point[], source: "auto" | "manual") =>
    request<RectifyResponse>(
      `/api/captures/${encodeURIComponent(id)}/rectify`,
      jsonInit("POST", {
        quad_norm: quad,
        source,
        geometry_mode: "training_canvas",
      } satisfies RectifyRequest)
    ),

  predict: (id: string, body: PredictRequest) =>
    request<PredictionResponse>(
      `/api/captures/${encodeURIComponent(id)}/predict`,
      jsonInit("POST", body)
    ),

  guidance: (id: string, body: GuidanceRequest) =>
    request<GuidanceResponse>(
      `/api/captures/${encodeURIComponent(id)}/guidance`,
      jsonInit("POST", body)
    ),

  /**
   * Build Grad-CAM maps for a capture. Seconds on CPU, so callers should
   * still show progress. No client timeout: aborting mid-run wastes the work.
   */
  explain: (id: string, body: ExplainRequest) =>
    request<ExplainResponse>(
      `/api/captures/${encodeURIComponent(id)}/explain`,
      jsonInit("POST", body)
    ),

  listExplanations: (id: string) =>
    request<ExplainListResponse>(
      `/api/captures/${encodeURIComponent(id)}/explain`
    ),

  getExplanation: (id: string, explainId: string) =>
    request<ExplainResponse>(
      `/api/captures/${encodeURIComponent(id)}/explain/${encodeURIComponent(explainId)}`
    ),

  deleteExplanation: (id: string, explainId: string) =>
    request<{ deleted: boolean }>(
      `/api/captures/${encodeURIComponent(id)}/explain/${encodeURIComponent(explainId)}`,
      { method: "DELETE" }
    ),

  patchAnnotation: (id: string, body: AnnotationRequest) =>
    request<CaptureRecord>(
      `/api/captures/${encodeURIComponent(id)}/annotation`,
      jsonInit("PATCH", body)
    ),

  deleteCapture: (id: string) =>
    request<DeleteResponse>(
      `/api/captures/${encodeURIComponent(id)}`,
      { method: "DELETE" }
    ),
};
