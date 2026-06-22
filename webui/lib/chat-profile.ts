import type { ChatMessageT, SessionProfile } from "@/lib/types";

const PROFILE_FIELDS: (keyof SessionProfile)[] = [
  "available_capital",
  "capital_currency",
  "risk_tolerance",
  "max_single_position_pct",
  "horizon",
  "constraints",
];

export function sessionFactsProposal(
  message: ChatMessageT,
): Partial<SessionProfile> | null {
  const call = message.tool_calls.find(
    (item) => item.tool === "propose_session_facts",
  );
  const args = call?.args;
  if (!args || typeof args !== "object") return null;
  // 后端工具返回 {proposal: {...}}; LangChain 记录的是入参本身，故二者都兼容
  const source = ((args as { proposal?: unknown }).proposal ?? args) as Record<
    string,
    unknown
  >;
  const proposal: Partial<SessionProfile> = {};
  for (const field of PROFILE_FIELDS) {
    if (source[field] !== undefined && source[field] !== null) {
      // @ts-expect-error narrow per-field assignment from untrusted payload
      proposal[field] = source[field];
    }
  }
  return Object.keys(proposal).length > 0 ? proposal : null;
}
