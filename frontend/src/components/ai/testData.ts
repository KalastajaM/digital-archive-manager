/** Shared test fixtures for the AI components (imported by tests only). */
import type { AIPrepared, AIStatus } from "../../api/client";

export const STATUS_ON: AIStatus = {
  enabled: true,
  has_key: true,
  switched_on: true,
  state_error: null,
  month_spend_eur: 1.25,
  budget_eur: 5,
  models: { small: "claude-haiku-5-5", large: "claude-sonnet-5-5" },
  exclude_folders: ["50. Medical"],
};

export function prepared(overrides: Partial<AIPrepared> = {}): AIPrepared {
  return {
    task: "suggest-filing",
    model: "claude-haiku-5-5",
    system: "You help file one document.",
    payload_text: "Document text:\n<document>\nNorthpower Oy lasku‮ 84,20 €\n</document>",
    files: ["d1"],
    estimate_eur: 0.0012,
    blocked: null,
    token: "tok-1",
    cached: null,
    notes: [],
    ...overrides,
  };
}

