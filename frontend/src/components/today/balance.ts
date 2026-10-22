/** Today's default card layout: the cards that have something to show are dealt out
 * between the columns by their rough height, so neither column runs long. A user's
 * own saved layout still wins (see ``useCardLayout``). */

export type Weighted = { id: string; weight: number };

/** Each card, in priority order, goes to the shorter column (the first on a tie). */
export function balanceColumns(cards: Weighted[], columns = 2): string[][] {
  const out: string[][] = Array.from({ length: columns }, () => []);
  const height = Array.from({ length: columns }, () => 0);
  for (const { id, weight } of cards) {
    let at = 0;
    for (let i = 1; i < columns; i++) if (height[i] < height[at]) at = i;
    out[at].push(id);
    height[at] += weight;
  }
  return out;
}
