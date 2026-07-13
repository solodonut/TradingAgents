/** 解析要勾选的供应商:localStorage 记录 ∩ 当前可用供应商。
 *  无记录 → 全选;交集为空(记录全过期)→ 回退全选,避免“全不选”死锁。 */
export function resolveVendorSelection(
  saved: string[] | null,
  available: string[],
): string[] {
  if (saved === null) return [...available];
  const availableSet = new Set(available);
  const kept = saved.filter((v) => availableSet.has(v));
  return kept.length ? kept : [...available];
}
