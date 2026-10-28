import type { QualityMetrics } from "../api/types";
import { msg } from "../ui";

// One line per backend "warn" flag (services/quality.py). Every poor_* flag
// is raised together with its warn counterpart, and a "poor" image is
// rejected by the server (422 POOR_IMAGE_QUALITY) unless blocking is off, so
// listing the warn flags covers both.
const WARNINGS: Record<string, string> = {
  low_brightness: "The photo is dark.",
  high_brightness: "The photo is very bright.",
  low_contrast: "The sheet looks faint (low contrast).",
  clipped_highlights: "Some areas are blown out to pure white.",
  clipped_shadows: "Some areas are pure black.",
  glare: "There may be glare on the sheet.",
  small_sheet_area: "The sheet fills only part of the photo.",
  extreme_perspective: "The photo was taken at a steep angle.",
  low_resolution: "The sheet is small in the photo, so fine detail may be lost.",
  low_sharpness: "The photo is slightly blurry.",
  grid_not_resolvable: "The ECG grid isn't clearly visible in the model input.",
};

export default function QualityWarnings({ quality }: { quality: QualityMetrics | null | undefined }) {
  const lines = (quality?.flags ?? []).flatMap((f) => (WARNINGS[f] ? [WARNINGS[f]] : []));
  if (lines.length === 0) return null;
  return (
    <div className={`${msg.warn} mb-3`} role="status">
      <strong>Photo quality:</strong>
      <ul className="list-disc pl-5 my-1">
        {lines.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
      The result may be less reliable. Retake the photo if you can.
    </div>
  );
}
