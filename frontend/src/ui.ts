export const btn = {
  // button.primary
  primary: "bg-accent-strong border-accent-strong text-white font-semibold hover:bg-accent",
  // button.danger
  danger: "bg-matte-red border-matte-red text-white font-semibold hover:bg-matte-red-hover hover:border-matte-red-hover",
  // button.ghost
  ghost: "bg-transparent border-line text-ink-muted hover:border-line-strong hover:text-ink",
  // button.matte-blue
  matteBlue: "bg-matte-blue border-matte-blue text-white font-semibold hover:bg-matte-blue-hover hover:border-matte-blue-hover",
  // button.small (combine with a button color above)
  small: "min-h-9 px-3 text-[0.85rem]",
  // button.link-button
  link: "min-h-0 p-0 border-0 bg-transparent text-accent text-[0.9rem] underline hover:text-accent-strong",
} as const;

// .panel (outer margins belong to the call site)
export const panel = "bg-panel border border-line rounded-card p-4.5";
// .panel h2
export const panelTitle = "mb-1.5 text-[1.05rem] font-bold";
// .auth-panel.panel (standalone, not combined with panel)
export const authPanel = "bg-panel border border-line rounded-card p-4.5 w-full max-w-[400px] mx-auto my-10";
// .auth-actions
export const authActions = "flex justify-center w-full";
// .auth-submit-btn (combine with btn.primary or btn.danger)
export const authSubmit = "min-h-[42px] min-w-40 px-9 py-2 text-[0.95rem] font-semibold rounded-control";

export const msg = {
  // .msg.error
  error: "rounded-control border border-error-line bg-error-wash text-error-ink px-3.5 py-3 text-[0.9rem]",
  // .msg.warn
  warn: "rounded-control border border-warn-line bg-warn-wash text-warn-ink px-3.5 py-3 text-[0.9rem]",
  // .msg.info
  info: "rounded-control border border-info-line bg-info-wash text-info-ink px-3.5 py-3 text-[0.9rem]",
} as const;

// .field
export const field = "flex flex-col gap-1.5";
// .field label
export const fieldLabel = "text-[0.85rem] font-semibold text-ink-muted";
// .field .hint
export const fieldHint = "text-[0.78rem] text-ink-faint";
// .field-error
export const fieldError = "mt-1.25 text-[0.84rem] font-medium leading-[1.35] text-poor";

// .spinner (size-free for the compact ExplainPanel spinner)
export const spinner = "inline-block rounded-full border-line-strong border-t-accent animate-spinner print:hidden";
// .spinner (standalone inline size)
export const spinnerInline = "inline-block rounded-full border-line-strong border-t-accent animate-spinner print:hidden size-4.5 border-2 mr-2 align-[-3px]";
// .loading-block.screen-center .spinner (standalone large size)
export const spinnerLarge = "inline-block rounded-full border-line-strong border-t-accent animate-spinner print:hidden size-8 border-3";
// .loading-block
export const loadingBlock = "px-5 py-10 text-center text-ink-muted";
// .loading-block.screen-center (standalone, not combined with loadingBlock)
export const loadingScreen = "flex flex-col items-center justify-center gap-3.5 min-h-[calc(100dvh-160px)] p-5 text-center text-ink-muted";

// .section-title (bottom margin belongs to the call site)
export const sectionTitle = "text-[1.2rem] font-bold";
// .section-sub
export const sectionSub = "mb-4 text-[0.9rem] text-ink-muted";
// .negative-labels
export const disclosure = "mt-3.5 border-t border-line pt-3";
// .negative-labels summary
export const disclosureSummary = "cursor-pointer font-semibold text-ink-muted list-inside";
// .score-value (font size belongs to the call site)
export const scoreValue = "font-bold leading-[1.1] tabular-nums text-ink";
