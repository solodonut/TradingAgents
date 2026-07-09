import type { ServiceHealthItem } from "./types";

const STATUS_ORDER: Record<ServiceHealthItem["status"], number> = {
  ok: 0,
  error: 1,
  warning: 2,
  checking: 3,
  disabled: 4,
};

export function sortServiceHealthItems(items: ServiceHealthItem[]): ServiceHealthItem[] {
  return [...items].sort((a, b) => {
    const statusDiff = STATUS_ORDER[a.status] - STATUS_ORDER[b.status];
    if (statusDiff !== 0) return statusDiff;
    return a.name.localeCompare(b.name, "zh-Hans-CN");
  });
}
