/** Patient-facing formatting for an uncalibrated sigmoid model score.
 *
 * Deliberately do not call this confidence or probability. The percentage is
 * only a friendlier representation of the stored [0, 1] model score.
 */
export function formatModelScore(score: number): string {
  const clamped = Math.max(0, Math.min(1, score));
  if (clamped > 0 && clamped < 0.005) return "<1%";
  if (clamped >= 0.995 && clamped < 1) return ">99%";
  return `${Math.round(clamped * 100)}%`;
}
