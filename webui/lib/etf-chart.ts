export function buildLinePath(
  points: { t: string; price: number }[],
  width: number,
  height: number,
  pad: number,
): string {
  if (points.length === 0) return "";
  const prices = points.map((p) => p.price);
  const min = Math.min(...prices);
  const max = Math.max(...prices);
  const span = max - min || 1;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const step = points.length > 1 ? innerW / (points.length - 1) : 0;
  return points
    .map((p, i) => {
      const x = pad + step * i;
      const y = pad + innerH - ((p.price - min) / span) * innerH;
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}
