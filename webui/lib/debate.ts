// Parse a debate `history` string (accumulated as `history + "\n" + argument`,
// each argument prefixed with "<Speaker> Analyst:") into ordered turns.

export type DebateTurn = { round: number; speakerLabel: string; content: string };

export const INVEST_LABELS: Record<string, string> = {
  Bull: "多方",
  Bear: "空方",
};

export const RISK_LABELS: Record<string, string> = {
  Aggressive: "激进",
  Conservative: "保守",
  Neutral: "中立",
};

export function parseDebateHistory(
  history: unknown,
  groupSize: number,
  labels: Record<string, string>,
): DebateTurn[] {
  if (typeof history !== "string" || !history.trim()) return [];
  const re = /(Bull|Bear|Aggressive|Conservative|Neutral) Analyst:/g;
  const marks: { speaker: string; start: number; contentStart: number }[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(history)) !== null) {
    marks.push({ speaker: m[1], start: m.index, contentStart: m.index + m[0].length });
  }
  return marks.map((mark, i) => {
    const end = i + 1 < marks.length ? marks[i + 1].start : history.length;
    return {
      round: Math.floor(i / groupSize) + 1,
      speakerLabel: labels[mark.speaker] ?? mark.speaker,
      content: history.slice(mark.contentStart, end).trim(),
    };
  });
}
