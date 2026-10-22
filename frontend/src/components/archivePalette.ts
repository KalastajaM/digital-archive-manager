/** The colours an archive can be shown with (the same list the server picks from). */
export const ARCHIVE_COLORS: { name: string; value: string }[] = [
  { name: "Blue", value: "#3b6fd4" },
  { name: "Orange", value: "#d9822b" },
  { name: "Purple", value: "#8a5cc7" },
  { name: "Teal", value: "#1f8a8a" },
  { name: "Red", value: "#c84b4b" },
  { name: "Green", value: "#2f8f5b" },
  { name: "Pink", value: "#c44f8f" },
  { name: "Gray", value: "#6b7280" },
];

/** The first colour no archive uses yet (for a new archive's suggestion). */
export function freeColor(used: string[]): string {
  const taken = new Set(used.map((c) => c.toLowerCase()));
  const free = ARCHIVE_COLORS.slice(1).concat(ARCHIVE_COLORS.slice(0, 1)).find((c) => !taken.has(c.value));
  return (free ?? ARCHIVE_COLORS[1]).value;
}

/** Archive "main" is the one every install starts with: it gets no colour band. */
export const hasBand = (archive: { id: string } | null | undefined, count: number | undefined) =>
  !!archive && (count ?? 1) > 1 && archive.id !== "main";
