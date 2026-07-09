type Pt = { t: string; price: number };

function coords(points: Pt[], width: number, height: number, pad: number) {
  const prices = points.map((p) => p.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const step = points.length > 1 ? innerW / (points.length - 1) : 0;
  const xy = points.map((p, i) => ({
    x: pad + step * i,
    y: pad + innerH - ((p.price - min) / span) * innerH,
    price: p.price,
    t: p.t,
  }));
  return { xy, min, max };
}

export function buildLinePath(points: Pt[], width: number, height: number, pad: number): string {
  if (points.length === 0) return "";
  return coords(points, width, height, pad)
    .xy.map(({ x, y }, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
}

// Closed path (line + drop to baseline) for a gradient area fill under the line.
export function buildAreaPath(points: Pt[], width: number, height: number, pad: number): string {
  if (points.length === 0) return "";
  const { xy } = coords(points, width, height, pad);
  const baseY = height - pad;
  const line = xy
    .map(({ x, y }, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ");
  const first = xy[0];
  const last = xy[xy.length - 1];
  return `${line} L${last.x.toFixed(1)},${baseY.toFixed(1)} L${first.x.toFixed(1)},${baseY.toFixed(1)} Z`;
}

// Key marks for labelling a chart: last point (for the current-value dot) and
// the high / low extremes with their pixel positions.
export function chartMarks(points: Pt[], width: number, height: number, pad: number) {
  if (points.length === 0) return null;
  const { xy, min, max } = coords(points, width, height, pad);
  const last = xy[xy.length - 1];
  const high = xy.reduce((a, b) => (b.price > a.price ? b : a));
  const low = xy.reduce((a, b) => (b.price < a.price ? b : a));
  return { last, high, low, min, max, first: xy[0] };
}
