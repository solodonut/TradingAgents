// Turns the backend's `indicator_text` blob (a per-date value dump for each
// technical indicator) into structured, glanceable data: latest value, a
// chronological series for a sparkline, and a short interpretation.

export type IndicatorPoint = { date: string; value: number };

export type ParsedIndicator = {
  key: string;
  label: string;
  series: IndicatorPoint[]; // oldest → newest, N/A rows removed
  latest: IndicatorPoint | null; // most recent non-N/A value
  description: string;
};

export type IndicatorTone = "up" | "down" | "warn" | "muted";
export type IndicatorVerdict = { label: string; tone: IndicatorTone };

const LABELS: Record<string, string> = {
  macd: "MACD",
  rsi: "RSI",
  close_50_sma: "50日均线",
  close_200_sma: "200日均线",
  close_10_ema: "10日EMA",
  boll: "布林中轨",
  boll_ub: "布林上轨",
  boll_lb: "布林下轨",
  atr: "ATR",
  vwma: "VWMA",
  mfi: "MFI",
};

function labelFor(key: string): string {
  return LABELS[key] ?? key.toUpperCase();
}

const SECTION_RE = /^##\s+(\S+)\s*$/; // "## macd" — key only, not "## macd values from …"
const ROW_RE = /^(\d{4}-\d{2}-\d{2}):\s*(.+)$/;

export function parseIndicatorText(text: string | undefined | null): ParsedIndicator[] {
  if (!text) return [];
  const lines = text.split("\n");
  const out: ParsedIndicator[] = [];
  let current: ParsedIndicator | null = null;
  const descLines: string[] = [];

  const flush = () => {
    if (!current) return;
    current.description = descLines.join(" ").trim();
    // Rows arrive newest-first; latest = first non-N/A, series = chronological.
    current.latest = current.series[0] ?? null;
    current.series = [...current.series].reverse();
    out.push(current);
  };

  for (const raw of lines) {
    const line = raw.trim();
    const section = line.match(SECTION_RE);
    if (section) {
      flush();
      current = { key: section[1], label: labelFor(section[1]), series: [], latest: null, description: "" };
      descLines.length = 0;
      continue;
    }
    if (!current) continue;
    if (line.startsWith("##")) continue; // the "values from … to …" header

    const row = line.match(ROW_RE);
    if (row) {
      const value = Number.parseFloat(row[2]);
      if (Number.isFinite(value) && !row[2].startsWith("N/A")) {
        current.series.push({ date: row[1], value });
      }
      continue;
    }
    if (line.length > 0) descLines.push(line);
  }
  flush();
  return out;
}

// Short, colour-coded read on where an indicator sits. `latestClose` is the
// most recent daily close, needed to place price relative to a moving average.
export function interpretIndicator(
  key: string,
  value: number,
  latestClose: number | null,
): IndicatorVerdict {
  if (key === "rsi") {
    if (value >= 70) return { label: "超买", tone: "warn" };
    if (value <= 30) return { label: "超卖", tone: "warn" };
    return { label: "中性", tone: "muted" };
  }
  if (key === "macd") {
    if (value > 0.005) return { label: "多头动能", tone: "up" };
    if (value < -0.005) return { label: "空头动能", tone: "down" };
    return { label: "动能转折", tone: "muted" };
  }
  // Moving-average / band families: compare the latest close to the level.
  if (latestClose != null) {
    if (latestClose > value) return { label: "价在上方", tone: "up" };
    if (latestClose < value) return { label: "价在下方", tone: "down" };
    return { label: "贴合", tone: "muted" };
  }
  return { label: "—", tone: "muted" };
}
