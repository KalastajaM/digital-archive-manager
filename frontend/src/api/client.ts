/** Typed JSON client for the dam API, plus TanStack Query hooks. */
import { keepPreviousData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type InboxEntry = Schemas["InboxEntryOut"];
/** A scan field of a file: ``{kind, label, value}`` (``label`` only for ``custom``). */
export type ScanField = Schemas["ScanFieldOut"];
export type ScanFields = Schemas["ScanFieldsOut"];
type FollowUps = "tray_fields" | "collections" | "note" | "star" | "important";
/** A filing request; the tray/collection/note/star/important follow-ups are optional
 * (server defaults). */
export type FileRequest = Omit<Schemas["FileRequestIn"], FollowUps> &
  Partial<Pick<Schemas["FileRequestIn"], FollowUps>>;
export type FileBody = Omit<Schemas["FileBody"], "requests"> & { requests: FileRequest[] };
export type ResolvedOp = Schemas["ResolvedOpOut"];
export type FileItResult = Schemas["FileItResultOut"];
export type Via = FileBody["via"];
export type Rule = Schemas["RuleOut"];
export type RuleIn = Schemas["RuleIn"];
export type RuleDraft = Schemas["RuleDraftOut"];
export type RuleOffer = Schemas["RuleOfferOut"];
export type Replay = Schemas["ReplayOut"];
/** A rule test running in the background: its state, how far it is and the result so far. */
export type ReplayJob = Schemas["ReplayJobOut"];
export type RulesData = Schemas["RulesOut"];
export type RuleExplain = Schemas["RuleExplainOut"];
export type RulesState = Schemas["RulesStateOut"];
/** An area of page 1 behind a suggestion or a rule's explanation (see ``AreaOut``). */
export type Area = Schemas["AreaOut"];
/** A box drawn on page 1: [x0, y0, x1, y1] as fractions of the page, origin top left. */
export type PageBox = number[];
/** Page 1's text lines with their boxes (``read`` false: not read yet, or ``unavailable`` says why). */
export type Page1 = Schemas["Page1Out"];
/** The draft a box drawn on page 1 starts from: a rule draft plus the box. */
export type ZoneDraft = Schemas["ZoneDraftOut"];
/** The crop of a picture area: a base64 PNG (8-bit grayscale, long side at most 300 px) and,
 * once saved with the rule's files, the path a zone's ``image`` names. */
export type AreaPicture = Schemas["AreaPictureOut"];
/** An area of a rule as the save call takes it (words or a picture). */
export type ZoneIn = Schemas["ZoneIn"];
/** One score of a picture rule's replay: a document, how well it matched, and whether the rule did. */
export type PictureScore = Schemas["PictureScoreOut"];
export type People = Schemas["PeopleOut"];
export type Person = Schemas["PersonIO"];
/** Who a document is from (``sender``) and for (``person``), as the owner said or a filing recorded. */
export type Assignment = Schemas["AssignmentOut"];
export type Sender = Schemas["SenderOut"];
export type BatchResult = Schemas["BatchResultOut"];
export type FilingCode = Schemas["FilingCodeIn"];
export type FilingCodes = Schemas["FilingCodesOut"];
export type CodeHit = Schemas["CodeHitOut"];
export type CodeFolders = Schemas["FilingCodeFoldersOut"];
/** A sticker sheet layout (mm on an A4 page): the built-ins and the saved custom one. */
export type SheetLayout = Schemas["SheetLayoutOut"];
export type SheetLayoutIn = Schemas["SheetLayoutIn"];
/** What to print: a count per code, the layout and the options. */
/** The sticker sheet's options: the query of ``GET /api/filing-codes/sheet``
 * (``stickerSheetUrl``); how many stickers of each code, in print order. */
export type StickerSheet = {
  codes: Record<string, number>;
  layout: string;
  start_at: number;
  boxes: boolean;
  blank_labels: boolean;
  outlines_only: boolean;
};
/** A row of the File N marked batch: its codes, the request that files it and a flag. */
export type BatchRow = Schemas["BatchRowOut"];
export type UndoResult = Schemas["UndoResultOut"];
export type Status = Schemas["StatusOut"];
// several archives (profiles)
export type Archive = Schemas["ArchiveOut"];
export type Archives = Schemas["ArchivesOut"];
export type ArchiveForgotten = Schemas["ArchiveForgetOut"];
export type ArchiveSwitched = Schemas["ArchiveSwitchOut"];
// first-run setup (only while no archive folder is configured)
export type SetupCandidate = Schemas["SetupCandidateOut"];
export type SetupCandidates = Schemas["SetupCandidatesOut"];
export type SetupFolder = Schemas["SetupFolderOut"];
export type SetupCheck = Schemas["SetupValidateOut"];
export type SetupResult = Schemas["SetupOut"];
// starting an archive from scratch
export type LayoutTemplate = Schemas["LayoutTemplateOut"];
export type LayoutTemplates = Schemas["LayoutTemplatesOut"];
export type LayoutBody = Schemas["LayoutIn"];
export type LayoutPreview = Schemas["LayoutPreviewOut"];
export type LayoutResult = Schemas["LayoutResultOut"];
export type RecoveryResult = Schemas["RecoveryResultOut"];
export type FileRecord = Schemas["FileRecordOut"];
export type DirEntry = Schemas["DirEntryOut"];
export type SearchHit = Schemas["SearchHitOut"];
export type JournalEntry = Schemas["JournalEntryOut"];
export type BatchSummary = Schemas["BatchSummaryOut"];
export type QuarantineBody = Schemas["QuarantineBody"];
export type UnusedPicturesBody = Schemas["UnusedPicturesIn"];
export type MoveBody = Schemas["MoveBody"];
export type MoveResult = Schemas["MoveResultOut"];
export type RenameBody = Schemas["RenameBody"];
export type FileSuggestions = Schemas["FileSuggestionsOut"];
// Phase 2
export type Today = Schemas["TodayOut"];
export type AttentionItem = Schemas["AttentionItemOut"];
export type TrayCount = Schemas["TrayCountOut"];
export type TrayDef = Schemas["TrayDef"];
export type FieldDef = Schemas["FieldDef"];
export type Trays = Schemas["TraysOut"];
export type Item = Schemas["ItemOut"];
/** An item as a tray list shows it: plus its level, file state and whether it has a note. */
export type TrayItem = Schemas["TrayItemOut"];
export type ItemFile = Schemas["ItemFileOut"];
export type ItemEvent = Schemas["ItemEventOut"];
export type ItemBarcode = Schemas["ItemBarcodeOut"];
export type Collection = Schemas["CollectionOut"];
/** A collection as the list shows it: plus its file count and open checklist entries. */
export type CollectionRow = Schemas["CollectionRowOut"];
export type Member = Schemas["MemberOut"];
export type Group = Schemas["GroupOut"];
/** A member's open tray items (with their urgency) and whether it is still in the inbox. */
export type MemberAttention = Schemas["MemberAttentionOut"];
export type ExportResult = Schemas["ExportOut"];
export type ExportFormat = Schemas["ExportBody"]["format"];
export type CollectionChange = Schemas["CollectionChangeOut"];
export type OngoingEntry = Schemas["EntryOut"];
export type ConvertPlan = Schemas["ConvertPlanOut"];
export type ConvertResult = Schemas["ConvertResultOut"];
export type ConvertBody = Schemas["ConvertBody"];
export type FileLinks = Schemas["FileLinksOut"];
/** A file's marks: ★ Ongoing ("starred") and ! Important ("important"). */
export type Mark = Schemas["FileRecordOut"]["marks"][number];
export type MarkAction = "star" | "unstar" | "important" | "unimportant";
export type FileDetail = Schemas["FileDetailOut"];
/** A file's lock (see ``useFileLock``) and the list of locked files and folders. */
export type LockState = Schemas["LockStateOut"];
export type Locks = Schemas["LocksOut"];
export type ChecklistItem = Schemas["ChecklistItemOut"];
export type InboxStats = Schemas["InboxStatsOut"];
export type Found = Schemas["FoundOut"];
export type QuickResult = Schemas["QuickOut"];
export type NoteKind = "file" | "collection" | "item";
export type ItemState = "open" | "done";
export type CollectionState = "open" | "closed" | "all";
// polish round
export type IndexProblem = Schemas["IndexErrorOut"];
export type IndexProblems = Schemas["IndexErrorsOut"];
export type IndexSummary = Schemas["IndexSummaryOut"];
export type TrayDefaultsDiff = Schemas["TrayDefaultsDiffOut"];
export type TrayDefaultAdded = Schemas["TrayDefaultAddedOut"];
export type TextPreview = Schemas["TextPreviewOut"];
export type AIStatus = Schemas["AIStatusOut"];
export type AIPrepared = Schemas["PreparedOut"];
export type AIRunResult = Schemas["RunOut"];
export type AILogRow = Schemas["AILogRow"];
/** A file's saved summaries: the AI one ("Use this summary") and the user's own. */
export type FileSummaries = Schemas["FileSummaryOut"];
export type SavedSummary = Schemas["SummaryOut"];
/** summarize-document's answer. */
export type DocumentSummary = { summary: string; key_facts: string[] };
/** summarize-collection's answer: ``per_group`` by group id (as a string). */
export type CollectionSummaryAnswer = { summary: string; per_group: Record<string, string>; rejected: Record<string, string> };
/** ask-archive's answer: each citation is a file that was sent, with its name. */
/** ``marks``: the cited file's ★ / ! as they are now (the API adds them on every run). */
export type AskCitation = { drive_id: string; quote: string; name: string; marks?: Mark[] };
export type AskAnswer = { answer: string; citations: AskCitation[]; rejected: Record<string, string> };
/** The AI tasks (``/api/ai/{task}``). */
export type AITask = "suggest-filing" | "summarize-document" | "summarize-collection" | "ask-archive";
/** suggest-filing's answer, after the server's checks: a field it could not use is null
 * (or left out) and ``rejected`` says why, by field (``tray_fields.<name>`` for one field). */
export type FilingSuggestion = {
  name: string | null;
  folder: string | null;
  tags: string[];
  tray: string | null;
  tray_fields: Record<string, string>;
  summary: string;
  confidence: Partial<Record<"name" | "folder" | "tags" | "tray" | "tray_fields", number>>;
  reason: string;
  rejected: Record<string, string>;
};

const STATUS_LABEL: Record<number, string> = {
  400: "Invalid request",
  404: "Not found",
  409: "Conflict",
  413: "Too large",
};

/** A non-2xx answer; ``message`` is ready to show: the API's ``error`` text alone, or a
 * status label when it sent none. */
export class ApiError extends Error {
  readonly status: number;
  /** The API's machine-readable reason, when it sends one (e.g. ``stale_preview``). */
  readonly code: string | null;
  /** The API's own ``error`` text alone (may be ""). */
  readonly detail: string;
  constructor(status: number, detail: string, code: string | null = null) {
    const label =
      status >= 500 ? "Internal error (see the dam log)" : (STATUS_LABEL[status] ?? `Error ${status}`);
    // a sentence from the server stands alone ("Conflict: ..." would be jargon); a
    // server error keeps its label, which says where to look
    super(detail ? (status >= 500 ? `${label}: ${detail}` : detail) : label);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

type Method = "GET" | "POST" | "PATCH" | "PUT" | "DELETE";

// -- the archive (profile) this window shows ------------------------------------

/** The id of the archive this page was loaded for (from ``/api/status``). Every change
 * the page asks for names it (``X-Dam-Archive``), so a window that is left open after
 * the server switched to another archive is refused (409) and cannot change the wrong one. */
let activeArchive: string | null = null;
export const setActiveArchive = (id: string | null) => {
  activeArchive = id;
};
export const getActiveArchive = () => activeArchive;

/** The archive "main" keeps the storage keys older versions used; the others get their
 * own, so what a window remembers (folds, layouts) never leaks between archives. */
export const archiveKey = (key: string) => (activeArchive && activeArchive !== "main" ? `${key}.${activeArchive}` : key);

/** Where to go after switching archives or leaving one: a fresh load of the start page
 * (every screen's ids belong to the archive that was open). A hook for tests. */
export const navigation = {
  leave: () => {
    window.location.assign("/");
  },
};

/** Unlock tokens by file: "unlocked until you leave this file". Memory only: a reload
 * forgets them (and so locks every file again); the server drops them after a while too. */
const unlockTokens = new Map<string, string>();
const unlockListeners = new Set<() => void>();
let unlockVersion = 0;
const unlocksChanged = () => {
  unlockVersion += 1;
  for (const l of unlockListeners) l();
};
export const isUnlockedNow = (driveId: string) => unlockTokens.has(driveId);
/** Forget every unlock (tests; and the page being left). */
export const forgetUnlocks = () => {
  if (unlockTokens.size === 0) return;
  unlockTokens.clear();
  unlocksChanged();
};

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  // the temporary unlocks this page holds: the server accepts a change to a locked file
  // only with the token it issued for it (see "Locks" below)
  if (unlockTokens.size > 0) headers["X-Dam-Unlock"] = [...unlockTokens.values()].join(",");
  const sendsBody = method !== "GET" && method !== "DELETE";
  if (sendsBody) headers["Content-Type"] = "application/json";
  if (method !== "GET" && activeArchive) headers["X-Dam-Archive"] = activeArchive;
  const response = await fetch(path, {
    method,
    headers,
    credentials: "same-origin",
    body: sendsBody ? JSON.stringify(body ?? {}) : undefined,
  });
  if (!response.ok) throw await failure(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function failure(response: Response): Promise<ApiError> {
  let detail = "";
  let code: string | null = null;
  try {
    const parsed = (await response.json()) as { error?: unknown; code?: unknown };
    if (typeof parsed.error === "string") detail = parsed.error;
    if (typeof parsed.code === "string") code = parsed.code;
  } catch {
    detail = response.statusText;
  }
  return new ApiError(response.status, detail, code);
}

export const get = <T>(path: string) => request<T>("GET", path);
export const post = <T>(path: string, body?: unknown) => request<T>("POST", path, body);
export const patch = <T>(path: string, body: unknown) => request<T>("PATCH", path, body);
export const put = <T>(path: string, body: unknown) => request<T>("PUT", path, body);
export const del = <T>(path: string) => request<T>("DELETE", path);

/** Message to show for any thrown value. */
export const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e));

// -- URLs that are not JSON ---------------------------------------------------

/** Width buckets the page renderer uses (others are rounded up to one of these). */
export const PAGE_WIDTHS = [400, 900, 1400, 2000] as const;
export type PageWidth = (typeof PAGE_WIDTHS)[number];

const fileUrl = (driveId: string) => `/api/files/${encodeURIComponent(driveId)}`;
export const pageUrl = (driveId: string, page: number, width: PageWidth = 900) =>
  `${fileUrl(driveId)}/page/${page}.png?w=${width}`;
export const rawUrl = (driveId: string) => `${fileUrl(driveId)}/raw`;
/** A saved picture of a picture area (``image``: ``areas/<name>.png``). */
export const areaPictureUrl = (image: string) =>
  `/api/rules/areas/${encodeURIComponent(image.replace(/^areas\//, ""))}`;
/** The crop as an ``img`` source. */
export const pngSrc = (png: string) => `data:image/png;base64,${png}`;

/** Quick Look thumbnail widths the API renders (others snap up to one of these). */
export type ThumbWidth = 600 | 1200 | 2000;
export const thumbUrl = (driveId: string, width: ThumbWidth = 1200) => `${fileUrl(driveId)}/thumb.png?width=${width}`;

/** The start of a text-like file (404 for other types). */
export const fetchTextPreview = (driveId: string) => get<TextPreview>(`${fileUrl(driveId)}/text`);

/** Open the file in its default macOS app, or show it in Finder (204; 409 for apps and
 * scripts, 404 when it is gone, 501 off macOS). Plain calls, not mutations: previews
 * render outside a query client too. */
export const launchFile = (driveId: string, how: "open" | "reveal") => post<void>(`${fileUrl(driveId)}/${how}`);

// -- hooks --------------------------------------------------------------------

const keys = {
  indexErrors: ["index-errors"],
  trayDefaults: ["tray-defaults"],
  inbox: ["inbox"],
  folders: ["folders"],
  status: ["status"],
  configured: ["configured"],
  setupCandidates: ["setup-candidates"],
  browse: ["browse"],
  activity: ["activity"],
  recovery: ["recovery"],
  today: ["today"],
  trays: ["trays"],
  items: ["items"],
  collections: ["collections"],
  fileLinks: ["file-links"],
  notes: ["notes"],
  checklist: ["checklist"],
  ongoing: ["ongoing"],
  important: ["important"],
  locks: ["locks"],
  file: ["file"],
  ai: ["ai"],
  fileFields: ["file-fields"],
  filingCodes: ["filing-codes"],
  rules: ["rules"],
  people: ["people"],
  senders: ["senders"],
  // under the inbox's key: whatever reloads the inbox reloads the marked batch too
  markedBatch: ["inbox", "marked"],
} as const;

const enc = encodeURIComponent;

export const useInbox = () =>
  useQuery({ queryKey: keys.inbox, queryFn: () => get<InboxEntry[]>("/api/inbox") });

export const useFolders = () =>
  useQuery({ queryKey: keys.folders, queryFn: () => get<string[]>("/api/folders") });

const knowArchive = <T extends { archive?: { id: string } | null }>(status: T): T => {
  if (status.archive) setActiveArchive(status.archive.id);
  return status;
};

export const useStatus = () =>
  useQuery({
    queryKey: keys.status,
    queryFn: async () => knowArchive(await get<Status>("/api/status")),
    refetchInterval: 5000,
  });

/** Whether an archive folder is set up. Only ``configured: false`` (the setup-mode
 * server) means the first-run screen; any other answer, even an error, shows the app. */
export const useConfigured = () =>
  useQuery({
    queryKey: keys.configured,
    queryFn: async () =>
      knowArchive(await get<{ configured?: boolean; archive?: Status["archive"]; profiles_count?: number }>("/api/status")),
    staleTime: Infinity,
  });

// -- archives (profiles) ---------------------------------------------------------

const archivesKey = ["archives"] as const;

/** The archives dam knows, and which one this window shows. */
export const useArchives = (enabled = true) =>
  useQuery({
    queryKey: archivesKey,
    queryFn: async () => {
      const list = await get<Archives>("/api/archives");
      setActiveArchive(list.current);
      return list;
    },
    enabled,
  });

/** Add an archive (it is not opened). ``demo_folder``: build the demo archive there. */
export const addArchive = (name: string, color: string | null, demo_folder?: string) =>
  post<Archive>("/api/archives", { name, color, ...(demo_folder ? { demo_folder } : {}) });

/** Open another archive in this server (409 when another window has it). */
export const switchArchive = (id: string) => post<ArchiveSwitched>(`/api/archives/${enc(id)}/switch`);

export const updateArchive = (id: string, change: { name?: string; color?: string }) =>
  patch<Archive>(`/api/archives/${enc(id)}`, change);

/** Remove an archive from the list; no folder is deleted. */
export const forgetArchive = (id: string, switch_to?: string) =>
  post<ArchiveForgotten>(`/api/archives/${enc(id)}/forget`, switch_to ? { switch_to } : {});

/** Show the archive's data folder or archive folder in Finder / Explorer. */
export const revealArchive = (id: string, what: "data" | "archive") =>
  post<void>(`/api/archives/${enc(id)}/reveal`, { what });

export const useSetupCandidates = () =>
  useQuery({
    queryKey: keys.setupCandidates,
    queryFn: () => get<SetupCandidates>("/api/setup/candidates"),
    staleTime: Infinity,
  });

/** Check a folder path (nothing changes on disk). */
export const checkSetupPath = (path: string) => post<SetupCheck>("/api/setup/validate", { path });

/** Save the archive folder; ``create`` makes that one missing folder first. With a
 * ``layout`` (start a new archive): also writes the special folder names to the settings
 * and makes the layout's folders, as one batch you can undo. */
export const saveSetup = (archive_root: string, create: boolean, layout?: LayoutBody) =>
  post<SetupResult>("/api/setup", layout ? { archive_root, create, layout } : { archive_root, create });

/** The folders a new archive at ``path`` would get (nothing changes on disk). */
export const previewSetupLayout = (path: string, layout: LayoutBody) =>
  post<LayoutPreview>("/api/setup/layout-preview", { path, layout });

/** The starter layouts and the special folders (inside the running app). */
export const useLayoutTemplates = (enabled = true) =>
  useQuery({
    queryKey: ["layout-templates"],
    queryFn: () => get<LayoutTemplates>("/api/layout/templates"),
    staleTime: Infinity,
    enabled,
  });

/** Every folder of the layout and which would be made (nothing changes on disk). */
export const previewLayout = (layout: LayoutBody) => post<LayoutPreview>("/api/layout/preview", layout);

/** What a new folder would do (nothing changes on disk); refused names are a 400. */
export const previewNewFolder = (parent: string, name: string) =>
  post<ResolvedOp[]>("/api/folders/new/preview", { parent, name });

/** Show an archive folder in Finder / Explorer / the file manager. */
export const revealFolder = (path: string) => post<void>("/api/folders/reveal", { path });

/** Copy one file into the inbox (the original stays). A taken name gets ``_2``; a file over
 * the size limit is a 413. Not JSON: the file itself is the body. */
export async function uploadToInbox(file: File): Promise<BatchResult> {
  const response = await fetch(`/api/inbox/upload?name=${encodeURIComponent(file.name)}`, {
    method: "POST",
    headers: { "Content-Type": "application/octet-stream", Accept: "application/json" },
    credentials: "same-origin",
    body: file,
  });
  if (!response.ok) throw await failure(response);
  return (await response.json()) as BatchResult;
}

/** What filing these requests would do (nothing changes on disk). */
export const usePreview = () =>
  useMutation({
    mutationFn: (requests: FileRequest[]) => post<ResolvedOp[]>("/api/inbox/preview", requests),
  });

function useRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.inbox });
    void client.invalidateQueries({ queryKey: keys.folders });
    void client.invalidateQueries({ queryKey: keys.status });
    void client.invalidateQueries({ queryKey: keys.browse });
    void client.invalidateQueries({ queryKey: keys.activity });
    void client.invalidateQueries({ queryKey: keys.recovery });
    // filing and undo create or remove tray items, collection entries and notes
    void client.invalidateQueries({ queryKey: keys.today });
    void client.invalidateQueries({ queryKey: keys.items });
    void client.invalidateQueries({ queryKey: keys.collections });
    void client.invalidateQueries({ queryKey: keys.fileLinks });
    void client.invalidateQueries({ queryKey: keys.notes });
    void client.invalidateQueries({ queryKey: keys.ongoing }); // undo of a conversion
    void client.invalidateQueries({ queryKey: keys.important });
    void client.invalidateQueries({ queryKey: keys.locks });
    void client.invalidateQueries({ queryKey: keys.file }); // the viewer's record (its marks)
  };
}

export const useFileIt = () => {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ requests, via }: { requests: FileRequest[]; via: Via }) =>
      post<FileItResult>("/api/inbox/file", { requests, dry_run: false, via } satisfies FileBody),
    onSettled: refresh,
  });
};

/** Make the layout's folders (one batch, undoable from Activity). */
export const useCreateLayout = () => {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (layout: LayoutBody) => post<LayoutResult>("/api/layout", layout),
    onSettled: refresh,
  });
};

/** Make one folder (``parent`` "" is the top of the archive). */
export const useCreateFolder = () => {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: ({ parent, name }: { parent: string; name: string }) =>
      post<BatchResult>("/api/folders/new", { parent, name }),
    onSettled: refresh,
  });
};

/** Copy files into the inbox, one batch each; refreshes the inbox afterwards. */
export const useUploadToInbox = () => {
  const refresh = useRefresh();
  return useMutation({ mutationFn: (file: File) => uploadToInbox(file), onSettled: refresh });
};

export const useUndo = () => {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (batchId: string) =>
      post<UndoResult>(`/api/activity/${encodeURIComponent(batchId)}/undo`),
    onSettled: refresh,
  });
};

/** The exact ops undoing ``batchId`` would run, or its refusal (nothing changes).
 * Fetched fresh each time the confirm opens: never cached, never retried. */
export const useUndoPreview = (batchId: string) =>
  useQuery({
    queryKey: ["undo-preview", batchId],
    queryFn: () => post<ResolvedOp[]>(`/api/activity/${encodeURIComponent(batchId)}/undo/preview`),
    retry: false,
    gcTime: 0,
    staleTime: 0,
    refetchOnWindowFocus: false,
  });

/** Direct children of the archive-relative folder ``path`` ("" is the root). */
/** A folder's direct children; with ``collection``, only those on the way to one of
 * its members (everything inside a member folder). */
export const useBrowse = (path: string, enabled = true, collection: number | null = null) =>
  useQuery({
    queryKey: collection === null ? [...keys.browse, path] : [...keys.browse, path, { collection }],
    queryFn: () =>
      get<DirEntry[]>(
        `/api/browse?path=${encodeURIComponent(path)}${collection === null ? "" : `&collection=${collection}`}`,
      ),
    enabled,
  });

export type FlatSort = "name" | "date" | "size" | "folder";
export type FlatFiles = Schemas["FlatFilesOut"];
/** The Files view's page size (the API's ``limit`` maximum). */
export const FLAT_LIMIT = 500;

/** The Files view: every file below ``path`` (of ``collection``, if set), flat, at most
 * ``FLAT_LIMIT`` rows plus the total. */
export const useBrowseFiles = (
  path: string,
  collection: number | null,
  sort: FlatSort,
  dir: "asc" | "desc",
  enabled = true,
) =>
  useQuery({
    queryKey: [...keys.browse, "files", path, { collection, sort, dir }],
    queryFn: () => {
      const p = new URLSearchParams({ path, sort, dir, limit: String(FLAT_LIMIT) });
      if (collection !== null) p.set("collection", String(collection));
      return get<FlatFiles>(`/api/browse/files?${p}`);
    },
    enabled,
  });

/** Full-text search; ``folder`` limits it to that subtree. Up to the API's 500 hits, so
 * sorting the results by a column sorts (nearly) every match, not just the best 50. */
export const searchFiles = (q: string, folder?: string) => {
  const folderParam = folder ? `&folder=${encodeURIComponent(folder)}` : "";
  return get<SearchHit[]>(`/api/search?q=${encodeURIComponent(q)}${folderParam}&limit=500`);
};

/** Moves into ``##. To Delete`` (mirrored path); a dry run only resolves the plan. */
export const useQuarantine = () => {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: QuarantineBody) => post<BatchResult>("/api/quarantine", body),
    onSettled: (_data, _error, body) => {
      if (!body.dry_run) refresh();
    },
  });
};

/** What moving these files into ``folder`` would do (nothing changes on disk). */
export const useMovePreview = () =>
  useMutation({
    mutationFn: (body: MoveBody) => post<ResolvedOp[]>("/api/browse/move/preview", body),
  });

/** Move files (names kept) into ``folder``: journaled, so the batch can be undone. */
export const useMoveFiles = () => {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: MoveBody) => post<MoveResult>("/api/browse/move", body),
    onSettled: refresh,
  });
};

/** One file's new name in a folder (its own: a rename; another: a move with that name). */
export const useRenamePreview = () =>
  useMutation({
    mutationFn: (body: RenameBody) => post<ResolvedOp[]>("/api/browse/rename/preview", body),
  });

/** Rename (and maybe move) one file: journaled, so the batch can be undone. */
export const useRenameFile = () => {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: RenameBody) => post<MoveResult>("/api/browse/rename", body),
    onSettled: refresh,
  });
};

/** What Activity is narrowed to (all optional; ``since``/``until`` are epoch seconds). */
export type ActivityFilter = {
  q?: string;
  kind?: string;
  origin?: string;
  status?: string;
  since?: number;
  until?: number;
};

/** Batches per page of Activity. */
export const ACTIVITY_PAGE = 50;

/** Journaled batches matching the filter, newest first, a page at a time. One more than
 * a page is asked for: getting it back is how we know there are more (its cursor is the
 * last batch shown). */
export const useActivity = (filter: ActivityFilter = {}) =>
  useInfiniteQuery({
    queryKey: [...keys.activity, filter],
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => {
      const params = new URLSearchParams({ limit: String(ACTIVITY_PAGE + 1) });
      for (const [k, v] of Object.entries(filter)) if (v !== undefined && v !== "") params.set(k, String(v));
      if (pageParam) params.set("before", pageParam);
      return get<BatchSummary[]>(`/api/activity?${params}`);
    },
    getNextPageParam: (last) => (last.length > ACTIVITY_PAGE ? last[ACTIVITY_PAGE - 1].batch_id : undefined),
    select: (data) => data.pages.flatMap((page) => page.slice(0, ACTIVITY_PAGE)),
  });

/** Journal rows of interrupted operations (settled by POST /api/recovery). */
export const usePendingRecovery = () =>
  useQuery({ queryKey: keys.recovery, queryFn: () => get<JournalEntry[]>("/api/recovery") });

export const useRecovery = () => {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: () => post<RecoveryResult>("/api/recovery"),
    onSettled: refresh,
  });
};

// -- Phase 2: Today, trays and items -------------------------------------------

/** Today, fetched again every few seconds while the barcode pass still reads inbox
 * files for QR stickers (``reading_codes``): its progress moves no status count. */
export const useToday = () =>
  useQuery({
    queryKey: keys.today,
    queryFn: () => get<Today>("/api/today"),
    refetchInterval: (query) => ((query.state.data?.reading_codes ?? 0) > 0 ? 3000 : false),
  });

/** Today counts the inbox and what indexing found in it: fetch it again whenever the
 * polled status's inbox count or indexing progress changes (a scan found or lost a
 * file, or read one), so the sidebar and Today always agree and "Found in the inbox"
 * appears without a reload. The inbox comes along: its tray guesses (Today's "Not
 * recognised", the Inbox rows) fill in as indexing reads the files. */
export function useTodayFollowsInbox(status: Status | undefined) {
  const client = useQueryClient();
  const now = status ? `${status.inbox_count}/${status.indexed}/${status.pending}/${status.files}` : undefined;
  const last = useRef(now);
  useEffect(() => {
    const before = last.current;
    last.current = now;
    if (before !== undefined && now !== undefined && before !== now) {
      void client.invalidateQueries({ queryKey: keys.today });
      void client.invalidateQueries({ queryKey: keys.inbox });
    }
  }, [client, now]);
}

/** Tray definitions in order, plus the tray files that were skipped. */
export const useTrays = () =>
  useQuery({ queryKey: keys.trays, queryFn: () => get<Trays>("/api/trays") });

export const useItems = (trayId: string, state: ItemState = "open") =>
  useQuery({
    queryKey: [...keys.items, "tray", trayId, state],
    queryFn: () => get<TrayItem[]>(`/api/trays/${enc(trayId)}/items?state=${state}`),
    enabled: trayId !== "", // no tray yet (the definitions are loading)
  });

export const useItem = (id: number) =>
  useQuery({ queryKey: [...keys.items, id], queryFn: () => get<Item>(`/api/items/${id}`) });

/** The item's files with their path and state (missing, in the quarantine folder). */
export const useItemFiles = (id: number) => useQuery(itemFilesQuery(id));

/** The item's files query (also fetched fresh by "Mark paid & file it…"). */
export const itemFilesQuery = (id: number) => ({
  queryKey: [...keys.items, id, "files"],
  queryFn: () => get<ItemFile[]>(`/api/items/${id}/files`),
});

/** The item's bank barcode, built from its current fields (under the item's key, so
 * every item change reloads it). */
export const useItemBarcode = (id: number) =>
  useQuery({
    queryKey: [...keys.items, id, "barcode"],
    queryFn: () => get<ItemBarcode>(`/api/items/${id}/barcode`),
  });

/** The item's events, oldest first. */
export const useItemHistory = (id: number) =>
  useQuery({
    queryKey: [...keys.items, id, "history"],
    queryFn: () => get<ItemEvent[]>(`/api/items/${id}/history`),
  });

/** The open items, collections and note of one file. */
/** One file's index record and tags (the viewer window). */
export const useFileDetail = (driveId: string, enabled = true) =>
  useQuery({
    queryKey: [...keys.file, driveId],
    queryFn: () => get<FileDetail>(`/api/files/${enc(driveId)}`),
    enabled: enabled && driveId !== "",
  });

/** What the rules and the scan suggest for a file anywhere in the archive. */
export const useFileSuggestions = (driveId: string, enabled = true) =>
  useQuery({
    queryKey: [...keys.file, driveId, "suggestions"],
    queryFn: () => get<FileSuggestions>(`/api/files/${enc(driveId)}/suggestions`),
    enabled,
  });

// -- page 1: boxes, people, From and For ---------------------------------------

/** How often page 1 is asked for again while it is being read, and for how long. */
export const PAGE1_POLL_MS = 2000;
const PAGE1_POLLS = 15;

/** Page 1's lines of a file. Asked again every 2 s (up to 30 s) while a read is queued
 * (``read`` false and no ``unavailable``). */
export const usePage1 = (driveId: string, enabled = true) =>
  useQuery({
    queryKey: [...keys.file, driveId, "page1"],
    queryFn: () => get<Page1>(`/api/files/${enc(driveId)}/page1`),
    enabled: enabled && driveId !== "",
    refetchInterval: (query) => {
      const page = query.state.data;
      return page && !page.read && !page.unavailable && query.state.dataUpdateCount < PAGE1_POLLS ? PAGE1_POLL_MS : false;
    },
  });

/** A suggestion that waits for page 1 (``waiting_for_page1``) asks for it until it is read,
 * then reloads what the inbox and the file show (and keeps reloading for a while if it
 * still waits, for the picture of the page). */
export function useWaitForPage1(driveId: string, waiting: boolean) {
  const client = useQueryClient();
  const page = usePage1(driveId, waiting);
  const read = page.data?.read === true;
  useEffect(() => {
    if (!waiting || !read) return;
    void client.invalidateQueries({ queryKey: keys.inbox });
    void client.invalidateQueries({ queryKey: [...keys.file, driveId, "suggestions"] });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting, read]);
  // page 1 is read but the suggestion still waits: a picture area has no picture of the
  // page yet (made in the background), so ask again for a while
  useEffect(() => {
    if (!waiting || !read) return;
    let tries = 0;
    const timer = setInterval(() => {
      tries += 1;
      void client.invalidateQueries({ queryKey: keys.inbox });
      void client.invalidateQueries({ queryKey: [...keys.file, driveId, "suggestions"] });
      if (tries >= PAGE1_POLLS) clearInterval(timer);
    }, PAGE1_POLL_MS);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [waiting, read]);
}

/** The lines of page 1 inside a box. */
export const usePage1Lines = () =>
  useMutation({
    mutationFn: ({ driveId, box }: { driveId: string; box: PageBox }) =>
      post<Page1>(`/api/files/${enc(driveId)}/page1/lines`, { box }),
  });

/** The rule the boxes drawn on page 1 start from, one area per box (a 400 says why not). */
export const useDraftZone = () =>
  useMutation({
    mutationFn: (body: { drive_id: string; boxes: PageBox[]; picture_boxes?: PageBox[]; sender?: string | null }) =>
      post<ZoneDraft>("/api/rules/draft-zone", body),
  });

/** The picture of a box on page 1, cut from the document's page-1 picture (nothing is
 * written). With ``save`` and the rule's id it is also kept with the rules and ``image``
 * names the file. A 400 says why not (the picture is not made yet, ...). */
export const useAreaPicture = () =>
  useMutation({
    mutationFn: ({ driveId, box, save = false, ruleId }: { driveId: string; box: PageBox; save?: boolean; ruleId?: string }) =>
      post<AreaPicture>("/api/rules/area-picture", { drive_id: driveId, box, save, rule_id: ruleId ?? null }),
  });

/** The senders in use, with the number of documents each has. */
export const useSenders = (enabled = true) =>
  useQuery({ queryKey: keys.senders, queryFn: () => get<Sender[]>("/api/senders"), enabled });

/** Set From and/or For on documents: a field left out stays, ``null`` clears it. */
export const usePutAssignments = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { drive_ids: string[]; sender?: string | null; person?: string | null }) =>
      put<Assignment[]>("/api/assignments", body),
    onSettled: () => {
      // the suggestion's {person} and the chips change with it
      void client.invalidateQueries({ queryKey: keys.inbox });
      void client.invalidateQueries({ queryKey: keys.file });
      void client.invalidateQueries({ queryKey: keys.senders });
    },
  });
};

/** The people list and the address area. */
export const usePeople = () => useQuery({ queryKey: keys.people, queryFn: () => get<People>("/api/settings/people") });

/** Save the people list (and the address area when given); a 400 says why not. */
export const useSavePeople = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { people: Person[]; address_zone?: PageBox }) => put<People>("/api/settings/people", body),
    onSuccess: (saved) => client.setQueryData(keys.people, saved),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.people });
      void client.invalidateQueries({ queryKey: keys.inbox }); // who a letter is for follows the list
      void client.invalidateQueries({ queryKey: keys.file });
    },
  });
};

/** Switch the background reading of page 1 of older documents. */
export const usePage1Backfill = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => put<{ enabled: boolean }>("/api/settings/page1-backfill", { enabled }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.status });
      void client.invalidateQueries({ queryKey: keys.indexErrors });
    },
  });
};

/** How many PDFs with a text layer have page 1 read per minute (scans and slow downloads keep
 * the indexer's pace). */
export const usePage1Speed = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (readsPerMinute: number) =>
      put<{ reads_per_minute: number }>("/api/settings/page1-speed", { reads_per_minute: readsPerMinute }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.status });
      void client.invalidateQueries({ queryKey: keys.indexErrors });
    },
  });
};

/** The tags in use that start with ``prefix`` (most used first), for the tag field's
 * suggestions; the previous list stays while the next one loads. */
export const useTagSuggestions = (prefix: string, limit: number, enabled = true) =>
  useQuery({
    queryKey: ["tag-suggestions", prefix, limit],
    queryFn: () => get<{ name: string; files: number }[]>(`/api/tags?${new URLSearchParams({ prefix, limit: String(limit) })}`),
    enabled,
    placeholderData: keepPreviousData,
    staleTime: 10_000,
  });

/** Set a file's tags exactly (written directly: no preview, nothing journaled). */
export const usePutFileTags = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ driveId, tags }: { driveId: string; tags: string[] }) =>
      put<{ tags: string[] }>(`/api/files/${enc(driveId)}/tags`, { tags }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.file });
      void client.invalidateQueries({ queryKey: keys.browse });
      void client.invalidateQueries({ queryKey: ["tag-suggestions"] });
    },
  });
};

export const useFileLinks = (driveId: string) =>
  useQuery({
    queryKey: [...keys.fileLinks, driveId],
    queryFn: () => get<FileLinks>(`/api/files/${enc(driveId)}/links`),
  });

/** Every tray/collection/note change can show up on Today and in the lists. */
function useRefreshTrays() {
  const client = useQueryClient();
  return () => {
    for (const key of [keys.today, keys.items, keys.collections, keys.fileLinks, keys.notes, keys.checklist]) {
      void client.invalidateQueries({ queryKey: key });
    }
  };
}

/** Mark an item done with the tray's done fields (DB only: no files move). */
export const useItemDone = () => {
  const refresh = useRefreshTrays();
  return useMutation({
    mutationFn: ({ id, fields }: { id: number; fields: Record<string, unknown> }) =>
      post<Item>(`/api/items/${id}/done`, { fields }),
    onSettled: refresh,
  });
};

export const useItemReopen = () => {
  const refresh = useRefreshTrays();
  return useMutation({
    mutationFn: (id: number) => post<Item>(`/api/items/${id}/reopen`),
    onSettled: refresh,
  });
};

/** Only what is given changes; a blank field value clears that field. */
export const useItemUpdate = () => {
  const refresh = useRefreshTrays();
  return useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Schemas["ItemPatchBody"]) =>
      patch<Item>(`/api/items/${id}`, body),
    onSettled: refresh,
  });
};

/** Add a file to an item or remove one (DB only: the file stays where it is). */
export const useItemFileChange = () => {
  const refresh = useRefreshTrays();
  return useMutation({
    mutationFn: ({
      id,
      driveId,
      remove,
      position,
    }: {
      id: number;
      driveId: string;
      remove?: boolean;
      /** Adding: where in the item's files (an Undo's old place); default the end. */
      position?: number;
    }) =>
      post<Item>(
        `/api/items/${id}/files${remove ? "/remove" : ""}`,
        position === undefined || remove ? { drive_id: driveId } : { drive_id: driveId, position },
      ),
    onSettled: refresh,
  });
};

/** Merge the open item ``source`` into the open item ``id``: its files, note and checklist
 * are added and it is removed (DB only). ``useUndoMergeItem`` brings both back. */
export const useMergeItem = () => {
  const refresh = useRefreshQuick();
  return useMutation({
    mutationFn: ({ id, source }: { id: number; source: number }) =>
      post<Item>(`/api/items/${id}/merge`, { item_id: source }),
    onSettled: refresh,
  });
};

export const useUndoMergeItem = () => {
  const refresh = useRefreshQuick();
  return useMutation({
    mutationFn: (id: number) => post<Item>(`/api/items/${id}/undo-merge`),
    onSettled: refresh,
  });
};

/** "Put in <tray>" and its take-back change the tray lists, Today, the sidebar counts
 * and the inbox's "already in" state. */
function useRefreshQuick() {
  const client = useQueryClient();
  const refreshTrays = useRefreshTrays();
  return () => {
    refreshTrays();
    void client.invalidateQueries({ queryKey: keys.trays });
    void client.invalidateQueries({ queryKey: keys.inbox });
  };
}

/** "Put in <tray>": an item per file with its scan prefill (DB only: the files stay in
 * the inbox). Files that already have an open item in the tray come back in ``skipped``. */
export const useQuickPutInTray = () => {
  const refresh = useRefreshQuick();
  return useMutation({
    /** With ``fields`` (one file; an AI suggestion's, exactly as shown): those values
     * instead of the scan prefill, with the same "already in" and folder checks. */
    mutationFn: (body: Schemas["QuickBody"]) => post<QuickResult>("/api/items/quick", body),
    onSettled: refresh,
  });
};

/** Take back an item nobody changed yet (DB only); 409 once it was changed. */
export const useDiscardItem = () => {
  const refresh = useRefreshQuick();
  return useMutation({
    mutationFn: (id: number) => post<void>(`/api/items/${id}/discard`),
    onSettled: refresh,
  });
};

/** Move an open item to another tray (the same item; DB only). */
export const useMoveItem = () => {
  const refresh = useRefreshQuick();
  return useMutation({
    mutationFn: ({ id, tray }: { id: number; tray: string }) => post<Item>(`/api/items/${id}/move`, { tray }),
    onSettled: refresh,
  });
};

/** Put a just-moved item back in its old tray; 409 once it was changed since. */
export const useUndoMoveItem = () => {
  const refresh = useRefreshQuick();
  return useMutation({
    mutationFn: (id: number) => post<Item>(`/api/items/${id}/undo-move`),
    onSettled: refresh,
  });
};

/** Remove an item (open or done) from its tray: the item, note, checklist and history
 * are deleted, the files are not touched. */
export const useRemoveItem = () => {
  const refresh = useRefreshQuick();
  return useMutation({
    mutationFn: (id: number) => post<void>(`/api/items/${id}/remove`),
    onSettled: refresh,
  });
};

export const useCreateItem = () => {
  const refresh = useRefreshTrays();
  return useMutation({
    mutationFn: (body: Omit<Schemas["ItemCreateBody"], "fields"> & { fields?: Record<string, unknown> }) =>
      post<Item>("/api/items", body),
    onSettled: refresh,
  });
};

// -- collections ----------------------------------------------------------------

export const useCollections = (state: CollectionState = "open") =>
  useQuery({
    queryKey: [...keys.collections, "list", state],
    queryFn: () => get<CollectionRow[]>(`/api/collections?state=${state}`),
  });

/** Every collection, open and closed, with the built-in ★ Ongoing and ! Important (the
 * Browse collection filter lists those under "Marked"; no other picker does). */
export const useCollectionsWithMarked = (enabled = true) =>
  useQuery({
    queryKey: [...keys.collections, "list", "all", "builtin"],
    queryFn: () => get<CollectionRow[]>("/api/collections?state=all&builtin=true"),
    enabled,
  });

/** The built-in ★ Ongoing (``starred``) or ! Important collection, with its members.
 * Under the collections key: every member change (a mark too) reloads it. */
export const useBuiltin = (kind: Mark) =>
  useQuery({
    queryKey: [...keys.collections, "builtin", kind],
    queryFn: () => get<Collection>(`/api/marks/collection/${kind}`),
  });

/** Sent on ``window`` after a mark changes, for lists outside the query cache (search). */
export const MARKS_CHANGED = "dam:marks-changed";

/** What a mark change reloads: everything that renders marks or the links the mark
 * publishes (``##. Ongoing`` / ``##. Important`` folders show in Browse, the folder
 * tree, Activity and the status counts). Not the recovery list, the notes or a file's
 * links (the built-ins are not listed as collections there). */
function useRefreshMarks() {
  const client = useQueryClient();
  return () => {
    for (const key of [
      keys.inbox,
      keys.folders,
      keys.status,
      keys.browse,
      keys.activity,
      keys.today,
      keys.items,
      keys.collections,
      keys.ongoing,
      keys.important,
      keys.locks,
      keys.file,
    ]) {
      void client.invalidateQueries({ queryKey: key });
    }
  };
}

/** The marks after ``action`` on marks ``from``, in the order the API gives them. */
export const marksAfter = (from: readonly Mark[] | undefined, action: MarkAction): Mark[] => {
  const kind: Mark = action === "star" || action === "unstar" ? "starred" : "important";
  const on = action === "star" || action === "important";
  return (["starred", "important"] as Mark[]).filter((m) => (m === kind ? on : (from ?? []).includes(m)));
};

/** Star or unstar, mark or unmark as Important (``group``: "Houses/Hillside", for
 * ``important`` only). A member change of a built-in: no preview, journaled, and the
 * opposite action reverses it. Everything that shows marks reloads; the Ask screen's
 * answers (kept in the cache for the session, never refetched) get their citations'
 * marks updated in place. */
export const useMark = () => {
  const client = useQueryClient();
  const refresh = useRefreshMarks();
  return useMutation({
    mutationFn: ({ action, ids, group }: { action: MarkAction; ids: string[]; group?: string }) =>
      post<CollectionChange>(`/api/marks/${action}`, group === undefined ? { drive_ids: ids } : { drive_ids: ids, group }),
    onSuccess: (_change, { action, ids }) => {
      client.setQueryData<AskEntry[]>(askKey, (old) =>
        old?.map((entry) => ({
          ...entry,
          answer: {
            ...entry.answer,
            citations: entry.answer.citations.map((c) =>
              ids.includes(c.drive_id) ? { ...c, marks: marksAfter(c.marks, action) } : c,
            ),
          },
        })),
      );
      window.dispatchEvent(new Event(MARKS_CHANGED));
    },
    onSettled: refresh,
  });
};

export const useCollection = (id: number) =>
  useQuery({
    queryKey: [...keys.collections, id],
    queryFn: () => get<Collection>(`/api/collections/${id}`),
  });

/** A new collection: a name (at the top), or a name inside an open ``parent_id``. */
export const useCreateCollection = () => {
  const refresh = useRefreshTrays();
  const sync = useRefresh(); // a child of a published parent gets a folder in ##. Ongoing
  return useMutation({
    mutationFn: (body: string | { name: string; parent_id: number }) =>
      post<Collection>("/api/collections", typeof body === "string" ? { name: body } : body),
    onSettled: (_data, _error, body) => {
      refresh();
      if (typeof body !== "string") sync();
    },
  });
};

/** Move a collection (and everything under it) inside another, or to the top (null).
 * No preview, as for member and group changes: the Ongoing sync only moves app-owned
 * entries (journaled) and moving it back reverses it; the batch that ran comes back.
 * A cycle is refused (400), and so is a closed parent (409). */
export const useSetCollectionParent = () => {
  const refresh = useRefresh(); // moves folders in ##. Ongoing: Activity and Browse too
  return useMutation({
    mutationFn: ({ id, parent_id }: { id: number; parent_id: number | null }) =>
      patch<CollectionChange>(`/api/collections/${id}/parent`, { parent_id }),
    onSettled: refresh,
  });
};

/** Put a collection before or after a sibling (its place among those with the same
 * parent). Only the order changes: no file moves, no batch. Built-in collections and
 * other parents are refused (400). */
export const useMoveCollectionOrder = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...place }: { id: number } & ({ before_id: number } | { after_id: number })) =>
      post<CollectionChange>(`/api/collections/${id}/move`, place),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.collections }),
  });
};

/** Add files/folders to a collection, or remove one (DB only: files stay put). The
 * Ongoing sync runs after it: the answer carries its batch and problems. */
export const useCollectionMembers = () => {
  const refresh = useRefresh(); // adds or removes links in ##. Ongoing
  return useMutation({
    mutationFn: (
      change: { id: number; add: string[] } | { id: number; remove: string },
    ): Promise<CollectionChange> =>
      "add" in change
        ? post<CollectionChange>(`/api/collections/${change.id}/members`, { drive_ids: change.add })
        : post<CollectionChange>(`/api/collections/${change.id}/members/remove`, { drive_id: change.remove }),
    onSettled: refresh,
  });
};

/** The members that need attention (open tray items, still in the inbox), in one
 * request. Under the collection's key: every collection or item change reloads it. */
export const useCollectionAttention = (id: number) =>
  useQuery({
    queryKey: [...keys.collections, id, "attention"],
    queryFn: () => get<MemberAttention[]>(`/api/collections/${id}/attention`),
  });

/** Groups and summaries. Each runs the Ongoing sync (groups are subfolders there, so
 * a group change moves app-owned links: journaled, no preview) and answers like the
 * member routes. */
export type GroupChange =
  | { op: "create"; id: number; name: string; parent_id: number | null }
  | ({ op: "update"; gid: number } & Schemas["GroupPatchBody"])
  | { op: "remove"; gid: number }
  | { op: "members"; id: number; drive_ids: string[]; group_id: number | null }
  | { op: "summary"; id: number; summary: string };

export const useGroupChange = () => {
  const refresh = useRefresh(); // moves links in ##. Ongoing: Activity and Browse too
  const client = useQueryClient();
  return useMutation({
    // Show the answer at once (a new group can go straight into rename); the refresh
    // below reloads it anyway.
    onSuccess: (r: CollectionChange) => client.setQueryData([...keys.collections, r.collection.id], r.collection),
    mutationFn: (change: GroupChange): Promise<CollectionChange> => {
      switch (change.op) {
        case "create":
          return post(`/api/collections/${change.id}/groups`, { name: change.name, parent_id: change.parent_id });
        case "update": {
          const { op: _op, gid, ...body } = change;
          return patch(`/api/collection-groups/${gid}`, body);
        }
        case "remove":
          return post(`/api/collection-groups/${change.gid}/remove`);
        case "members":
          return post(`/api/collections/${change.id}/members/group`, {
            drive_ids: change.drive_ids,
            group_id: change.group_id,
          });
        case "summary":
          return patch(`/api/collections/${change.id}/summary`, { summary: change.summary });
      }
    },
    onSettled: refresh,
  });
};

/** A collection change that syncs ``##. Ongoing``: preview with ``useCollectionPreview``,
 * then apply here; show the returned batch (the apply re-plans), not the preview. */
export type CollectionAction =
  | { id: number; action: "rename"; name: string }
  | { id: number; action: "close" | "reopen" }
  | { id: number; action: "publish"; on: boolean };

function collectionRoute(change: CollectionAction, preview: boolean): [string, unknown] {
  const base = `/api/collections/${change.id}`;
  const suffix = preview ? "/preview" : "";
  if (change.action === "rename") return [`${base}/rename${suffix}`, { name: change.name }];
  if (change.action === "publish") return [`${base}/publish${suffix}`, { publisher: "ongoing", on: change.on }];
  return [`${base}/${change.action}${suffix}`, undefined];
}

export const useCollectionPreview = () =>
  useMutation({
    mutationFn: (change: CollectionAction) => {
      const [path, body] = collectionRoute(change, true);
      return post<ResolvedOp[]>(path, body);
    },
  });

export const useCollectionChange = () => {
  const refresh = useRefresh(); // moves links in ##. Ongoing: Activity and Browse too
  return useMutation({
    mutationFn: (change: CollectionAction) => {
      if (change.action === "rename") {
        return patch<CollectionChange>(`/api/collections/${change.id}`, { name: change.name });
      }
      const [path, body] = collectionRoute(change, false);
      return post<CollectionChange>(path, body);
    },
    onSettled: refresh,
  });
};

/** Build a zip or one PDF of the collection (can take a while: no client timeout).
 * Over the size limit without ``confirm_large`` nothing is built: ``needs_confirm``. */
export const useExport = () =>
  useMutation({
    mutationFn: ({ id, ...body }: { id: number } & Schemas["ExportBody"]) =>
      post<ExportResult>(`/api/collections/${id}/export`, body),
  });

/** Where the built export downloads from (a same-origin link with ``download``). */
export const exportUrl = (token: string) => `/api/exports/${enc(token)}`;

// -- notes and checklists ---------------------------------------------------------------

export const useNote = (kind: NoteKind, target: string) =>
  useQuery({
    queryKey: [...keys.notes, kind, target],
    queryFn: () => get<{ text: string }>(`/api/notes/${kind}/${enc(target)}`),
  });

/** Store a note (trimmed); blank text removes it. */
export const useSetNote = () => {
  const refresh = useRefreshTrays();
  return useMutation({
    mutationFn: ({ kind, target, text }: { kind: NoteKind; target: string; text: string }) =>
      put<{ text: string }>(`/api/notes/${kind}/${enc(target)}`, { text }),
    onSettled: refresh,
  });
};

/** Add text below a note's existing text (one request: the server does the read and the
 * write together, so nothing typed meanwhile is lost). */
export const useAppendNote = () => {
  const client = useQueryClient();
  const refresh = useRefreshTrays();
  return useMutation({
    mutationFn: ({ kind, target, text }: { kind: NoteKind; target: string; text: string }) =>
      post<{ text: string }>(`/api/notes/${kind}/${enc(target)}/append`, { text }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.notes });
      return refresh();
    },
  });
};

export const useChecklist = (kind: NoteKind, target: string) =>
  useQuery({
    queryKey: [...keys.checklist, kind, target],
    queryFn: () => get<ChecklistItem[]>(`/api/checklist/${kind}/${enc(target)}`),
  });

export type ChecklistChange =
  | { op: "add"; kind: NoteKind; target: string; text: string }
  | { op: "set"; id: number; done?: boolean; text?: string }
  | { op: "remove"; id: number }
  | { op: "move"; id: number; position: number };

export const useChecklistChange = () => {
  const refresh = useRefreshTrays();
  return useMutation({
    mutationFn: (change: ChecklistChange): Promise<unknown> => {
      switch (change.op) {
        case "add":
          return post(`/api/checklist/${change.kind}/${enc(change.target)}`, { text: change.text });
        case "set":
          return patch(`/api/checklist/${change.id}`, { done: change.done, text: change.text });
        case "remove":
          return post(`/api/checklist/${change.id}/remove`);
        case "move":
          return post(`/api/checklist/${change.id}/move`, { position: change.position });
      }
    },
    onSettled: refresh,
  });
};

// -- converting ##. Ongoing -------------------------------------------------------

export const useOngoingEntries = () =>
  useQuery({ queryKey: keys.ongoing, queryFn: () => get<OngoingEntry[]>("/api/ongoing/entries") });

export const useConvertPreview = () =>
  useMutation({ mutationFn: (body: ConvertBody) => post<ConvertPlan>("/api/ongoing/preview", body) });

/** Apply exactly the previewed ``body`` plus its ``fingerprint``. */
export const useConvert = () => {
  const refresh = useRefresh(); // moves files and changes ##. Ongoing
  return useMutation({
    mutationFn: (body: ConvertBody & { fingerprint: string }) =>
      post<ConvertResult>("/api/ongoing/convert", body),
    onSettled: refresh,
  });
};

// -- converting ##. Important (stars) ----------------------------------------------

export type ImportantConvertBody = Schemas["ImportantConvertBody"];

export const useImportantEntries = () =>
  useQuery({ queryKey: keys.important, queryFn: () => get<OngoingEntry[]>("/api/important/entries") });

export const useImportantPreview = () =>
  useMutation({ mutationFn: (body: ImportantConvertBody) => post<ConvertPlan>("/api/important/preview", body) });

/** Apply exactly the previewed ``body`` plus its ``fingerprint``. */
export const useImportantConvert = () => {
  const refresh = useRefresh(); // moves files and changes ##. Important
  return useMutation({
    mutationFn: (body: ImportantConvertBody & { fingerprint: string }) =>
      post<ConvertResult>("/api/important/convert", body),
    onSettled: refresh,
  });
};

// -- polish round: index errors, tray defaults ------------------------------------

/** Files whose text could not be read (``all``: also the unsupported types). */
/** The rows the errors sheet shows at most; ``total`` says how many there are. */
export const INDEX_ERRORS_LIMIT = 200;

export const useIndexErrors = (all: boolean, enabled = true) =>
  useQuery({
    queryKey: [...keys.indexErrors, all],
    queryFn: () => get<IndexProblems>(`/api/index/errors?${all ? "all=1&" : ""}limit=${INDEX_ERRORS_LIMIT}`),
    enabled,
  });

/** Counts per index state and the not readable files per type (the list itself comes
 * from ``useIndexErrors``). */
export const useIndexSummary = () =>
  useQuery({
    queryKey: [...keys.indexErrors, "summary"],
    queryFn: () => get<IndexSummary>("/api/index/summary?limit=1"),
    refetchInterval: 15_000, // the page-1 pass moves on while the sheet is open
  });

/** Queue files for indexing again; the list and the status follow. */
export const useRetryIndex = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (driveIds: string[]) => post<{ queued: number }>("/api/index/retry", { drive_ids: driveIds }),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.indexErrors });
      void client.invalidateQueries({ queryKey: keys.status });
    },
  });
};

/** What the shipped default tray file adds (``paths``: the chosen subset; null: the
 * server's default choice). Always with the dismissed list. */
export const useTrayDefaults = (trayId: string, paths: string[] | null, enabled = true) =>
  useQuery({
    queryKey: [...keys.trayDefaults, trayId, paths],
    queryFn: () => {
      const q = new URLSearchParams({ dismissed: "1" });
      for (const p of paths ?? []) q.append("paths", p);
      return get<TrayDefaultsDiff>(`/api/trays/${enc(trayId)}/defaults-diff?${q}`);
    },
    enabled: enabled && trayId !== "" && (paths === null || paths.length > 0),
    placeholderData: (previous) => previous, // keep the sheet steady while a new subset loads
  });

function useRefreshTrayDefaults() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: keys.trayDefaults });
    void client.invalidateQueries({ queryKey: keys.trays });
    void client.invalidateQueries({ queryKey: keys.status });
  };
}

export type TrayDefaultsChange =
  | { op: "apply"; trayId: string; paths: string[]; expect_current_text: string; expect_new_text: string }
  | { op: "dismiss" | "undismiss"; trayId: string; paths: string[] };

/** Add the chosen default keys (exactly the previewed texts), or (un)dismiss keys. After
 * an apply the tray's subset diffs are dropped from the cache: those keys are no longer
 * missing, so fetching one again would only answer 400 (the full diff is refetched). */
export const useTrayDefaultsChange = () => {
  const refresh = useRefreshTrayDefaults();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (change: TrayDefaultsChange): Promise<{ file: string; backup: string } | { dismissed: string[] }> => {
      const base = `/api/trays/${enc(change.trayId)}`;
      if (change.op === "apply") {
        const { paths, expect_current_text, expect_new_text } = change;
        return post(`${base}/apply-defaults`, { paths, expect_current_text, expect_new_text });
      }
      return post(`${base}/defaults-${change.op}`, { paths: change.paths });
    },
    onSuccess: (_, change) => {
      if (change.op !== "apply") return;
      client.removeQueries({
        queryKey: [...keys.trayDefaults, change.trayId],
        predicate: (q) => q.queryKey[keys.trayDefaults.length + 1] !== null,
      });
    },
    onSettled: refresh,
  });
};

// -- AI (spec §2: nothing is sent without the sheet) -----------------------------

/** On/off, whether a key is present (never the key), the month's spend and cap. Reused
 * for a minute (the server asks the Keychain at most once a minute anyway); a run or
 * the on/off switch refreshes it. */
export const useAIStatus = () =>
  useQuery({
    queryKey: [...keys.ai, "status"],
    queryFn: () => get<AIStatus>("/api/ai/status"),
    staleTime: 60_000,
  });

/** What ``task`` would send and cost; nothing is sent. */
export const useAIPrepare = () =>
  useMutation({
    mutationFn: ({ task, params }: { task: AITask; params: Record<string, unknown> }) =>
      post<AIPrepared>(`/api/ai/${enc(task)}/prepare`, { params }),
  });

/** Send exactly the prepared payload (by its token); the month's spend changes. */
export const useAIRun = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ task, token }: { task: AITask; token: string }) =>
      post<AIRunResult>(`/api/ai/${enc(task)}/run`, { token }),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.ai }),
  });
};

/** The AI call log, newest first (Activity → AI). */
export const useAILog = (limit = 200) =>
  useQuery({
    queryKey: [...keys.ai, "log", limit],
    queryFn: () => get<{ rows: AILogRow[] }>(`/api/ai/log?limit=${limit}`).then((r) => r.rows),
  });

/** The on/off switch (``<data dir>/ai-state.json``, as ``dam ai --on/--off``). */
export const useAISwitch = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (enabled: boolean) => post<AIStatus>("/api/ai/state", { enabled }),
    onSuccess: (status) => client.setQueryData([...keys.ai, "status"], status),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.ai }),
  });
};

/** Save the AI excluded folders (the whole list: it replaces the defaults in
 * settings.yaml); they apply at once. Answers the new status. */
export const useAIExcludeFolders = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (folders: string[]) => put<AIStatus>("/api/ai/exclude-folders", { folders }),
    onSuccess: (status) => client.setQueryData([...keys.ai, "status"], status),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.ai }),
  });
};

/** The File N marked rows (dry runs on the server, nothing changes). */
export const useMarkedBatch = () =>
  useQuery({ queryKey: keys.markedBatch, queryFn: () => get<BatchRow[]>("/api/filing-codes/batch") });

/** The filing codes table, the entries of the file that were skipped (``problems``) and
 * codes that look like each other (``warnings``). */
export const useFilingCodes = () =>
  useQuery({ queryKey: keys.filingCodes, queryFn: () => get<FilingCodes>("/api/filing-codes") });

/** Replace the whole table (the old file is kept as a backup); a 400 says why not. */
export const useSaveFilingCodes = () => {
  const client = useQueryClient();
  const refresh = useRefresh(); // the inbox rows and Today read the codes
  return useMutation({
    mutationFn: (codes: FilingCode[]) => put<FilingCodes>("/api/filing-codes", codes),
    onSuccess: (saved) => client.setQueryData(keys.filingCodes, saved),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.filingCodes }); // also the folders below it
      refresh();
    },
  });
};

// -- learned filing rules -----------------------------------------------------

/** The rules in order, the files that were skipped (``errors``) and the offer state. */
export const useRules = (enabled = true) =>
  useQuery({ queryKey: keys.rules, queryFn: () => get<RulesData>("/api/rules"), enabled });

/** Test a rule in the background (one test per ``sheet``: an earlier one for it is ended). */
export const startReplayJob = (body: {
  rule: RuleIn;
  sheet: string;
  replaces?: string | null;
  placeAbove?: string | null;
  nearDriveId?: string | null;
  sourceDriveId?: string | null;
}) =>
  post<ReplayJob>("/api/rules/replay/jobs", {
    rule: body.rule,
    sheet: body.sheet,
    replaces: body.replaces ?? null,
    place_above: body.placeAbove ?? null,
    near_drive_id: body.nearDriveId ?? null,
    source_drive_id: body.sourceDriveId ?? null,
  });

/** The state of a background test and its result so far; with ``since`` (the version
 * already held) the result is null while nothing is new. */
export const getReplayJob = (id: string, since?: number) =>
  get<ReplayJob>(`/api/rules/replay/jobs/${enc(id)}${since !== undefined ? `?since=${since}` : ""}`);

/** End a background test where it is; what it found so far stays. */
export const stopReplayJob = (id: string) => post<ReplayJob>(`/api/rules/replay/jobs/${enc(id)}/stop`);

/** Queue page 1 of the documents a background test waits for to be read now (one at a
 * time, ahead of everything else); the test picks them up as they arrive. */
export const readReplayJobNow = (id: string) => post<{ queued: number }>(`/api/rules/replay/jobs/${enc(id)}/read-now`);

/** End a background test and forget it (the sheet that asked for it closed). */
export const dropReplayJob = (id: string) => del<ReplayJob>(`/api/rules/replay/jobs/${enc(id)}`);

/** The areas of the rule being tested on one document (matched lines, the best place and
 * score of a picture area, why one did not match), to draw them on its page 1. */
export const useAreasFor = (rule: RuleIn | undefined, driveId: string, enabled = true) =>
  useQuery({
    queryKey: ["areas-for", driveId, JSON.stringify(rule)],
    queryFn: () => post<{ areas: Area[] }>("/api/rules/areas-for", { rule, drive_id: driveId }),
    enabled: enabled && rule !== undefined,
  });

/** Which rules match a document and why not (their areas, with the score of a picture
 * area), as a query: for diagnosing a picture rule on a document. */
export const useRuleExplain = (driveId: string, enabled = true) =>
  useQuery({
    queryKey: [...keys.file, driveId, "explain"],
    queryFn: () => post<RuleExplain[]>("/api/rules/explain", { drive_id: driveId }),
    enabled,
  });

/** Save a rule (``replaces``: the id of the rule this one takes the place of;
 * ``placeAbove``: for a new rule, the learned rule it goes directly above); a 400 says why not. */
export const useSaveRule = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ rule, replaces, placeAbove }: { rule: RuleIn; replaces?: string | null; placeAbove?: string | null }) => {
      const query = replaces ? `?replaces=${enc(replaces)}` : placeAbove ? `?place_above=${enc(placeAbove)}` : "";
      return put<RulesData>(`/api/rules/${enc(rule.id)}${query}`, rule);
    },
    onSuccess: (saved) => client.setQueryData(keys.rules, saved),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.rules });
      // the areas behind a suggestion follow the rule
      void client.invalidateQueries({ queryKey: keys.inbox });
      void client.invalidateQueries({ queryKey: keys.file, predicate: (q) => q.queryKey.at(-1) === "suggestions" });
    },
  });
};

/** Move the rule pictures no rule uses (names in ``config/rules/areas``) into ``##. To Delete``
 * as ``dam rule picture <name>``; a dry run only resolves the plan. A real move is journaled
 * (so Activity and the toast can undo it) and drops the pictures from the unused list. */
export const useQuarantineUnusedPictures = () => {
  const client = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: (body: UnusedPicturesBody) => post<BatchResult>("/api/rules/unused-pictures/quarantine", body),
    onSettled: (_data, _error, body) => {
      if (body.dry_run) return;
      refresh();
      void client.invalidateQueries({ queryKey: keys.rules });
    },
  });
};

export const useDeleteRule = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => del<RulesData>(`/api/rules/${enc(id)}`),
    onSuccess: (saved) => client.setQueryData(keys.rules, saved),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.rules }),
  });
};

/** Move a rule up (``delta`` -1) or down (1) in the order. */
export const useMoveRule = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ id, delta }: { id: string; delta: number }) =>
      post<RulesData>(`/api/rules/${enc(id)}/move`, { delta }),
    onSuccess: (saved) => client.setQueryData(keys.rules, saved),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.rules }),
  });
};

/** Which rules match a document and which of them wins. */
export const useExplain = () =>
  useMutation({ mutationFn: (driveId: string) => post<RuleExplain[]>("/api/rules/explain", { drive_id: driveId }) });

/** Turn the offers on or off, or forget the declined word sets. */
export const useRulesState = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { offer?: boolean | null; clear_declined?: boolean }) => put<RulesState>("/api/rules/state", body),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.rules }),
  });
};

/** "Not for these": never offer a rule for this set of words again. */
export const useDeclineRule = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (words: string[]) => post<RulesState>("/api/rules/state/decline", { words }),
    onSettled: () => void client.invalidateQueries({ queryKey: keys.rules }),
  });
};

/** The codes' inbox folders that are missing, and inbox subfolders that are no code's. */
export const useCodeFolders = () =>
  useQuery({
    queryKey: [...keys.filingCodes, "folders"],
    queryFn: () => get<CodeFolders>("/api/filing-codes/folders"),
  });

/** What "Create inbox folders" would do (nothing changes on disk). */
export const previewCodeFolders = () => post<ResolvedOp[]>("/api/filing-codes/folders/preview");

/** Make the missing code folders in the inbox (one batch, undoable from Activity). */
export const useCreateCodeFolders = () => {
  const client = useQueryClient();
  const refresh = useRefresh();
  return useMutation({
    mutationFn: () => post<BatchResult>("/api/filing-codes/folders"),
    onSettled: () => {
      void client.invalidateQueries({ queryKey: keys.filingCodes });
      refresh();
    },
  });
};

const sheetsKey = [...keys.filingCodes, "sheets"];

/** The sticker sheet layouts: the built-ins, then the saved custom one (id ``custom``). */
export const useSheetLayouts = () => useQuery({ queryKey: sheetsKey, queryFn: () => get<SheetLayout[]>("/api/filing-codes/sheets") });

/** Save the custom sheet layout (the old file is kept as a backup); a 400 says why not
 * (too small for a sticker, beyond an A4 page). */
export const useSaveCustomSheet = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (layout: SheetLayoutIn) => put<SheetLayout>("/api/filing-codes/sheets/custom", layout),
    onSettled: () => void client.invalidateQueries({ queryKey: sheetsKey }),
  });
};

/** The sticker sheet page (``GET``, opened in its own tab; it carries a
 * Content-Security-Policy of its own). ``codes`` go as ``P:12,A:3``. */
export function stickerSheetUrl(sheet: StickerSheet): string {
  const query = new URLSearchParams({
    codes: Object.entries(sheet.codes)
      .map(([code, n]) => `${code}:${n}`)
      .join(","),
    layout: sheet.layout,
    start_at: String(sheet.start_at),
    boxes: String(sheet.boxes),
    blank_labels: String(sheet.blank_labels),
    outlines_only: String(sheet.outlines_only),
  });
  return `/api/filing-codes/sheet?${query}`;
}

/** One sticker as SVG, drawn from a code and label as typed (the Settings preview). */
export function stickerPreviewUrl(code: string, label: string): string {
  return `/api/filing-codes/sticker?${new URLSearchParams({ code, label })}`;
}

const summaryKey = (driveId: string) => [...keys.ai, "summary", driveId];

/** A file's saved summaries (``{ai, user}``, each with ``outdated``). */
export const useFileSummary = (driveId: string) =>
  useQuery({
    queryKey: summaryKey(driveId),
    queryFn: () => get<FileSummaries>(`/api/files/${enc(driveId)}/summary`),
  });

/** Save a summary: ``source: "ai"`` is "Use this summary", ``"user"`` the user's own
 * text. 409 when it would replace a current summary the user wrote, unless ``replace``
 * (asked first). */
export const usePutFileSummary = () => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({
      driveId,
      ...body
    }: {
      driveId: string;
      source: "ai" | "user";
      summary: string;
      key_facts?: string[];
      replace?: boolean;
    }) => put<FileSummaries>(`/api/files/${enc(driveId)}/summary`, body),
    onSuccess: (saved, { driveId }) => client.setQueryData(summaryKey(driveId), saved),
  });
};

const fileFieldsKey = (driveId: string) => [...keys.fileFields, driveId];

/** A file's scan fields: the saved list, else the detected one (``edited`` tells which). */
export const useFileFields = (driveId: string) =>
  useQuery({
    queryKey: fileFieldsKey(driveId),
    queryFn: () => get<ScanFields>(`/api/files/${enc(driveId)}/fields`),
  });

/** What changing a file's scan fields refreshes: the inbox entry (its fields and the
 * prefill that comes from them) and the file's own list. */
function useFieldsChange() {
  const client = useQueryClient();
  return (saved: ScanFields, driveId: string) => {
    client.setQueryData(fileFieldsKey(driveId), saved);
    void client.invalidateQueries({ queryKey: keys.inbox });
  };
}

/** Save a file's whole list of scan fields (it replaces the detected one). */
export const usePutFileFields = () => {
  const changed = useFieldsChange();
  return useMutation({
    mutationFn: ({ driveId, fields }: { driveId: string; fields: ScanField[] }) =>
      put<ScanFields>(`/api/files/${enc(driveId)}/fields`, { fields }),
    onSuccess: (saved, { driveId }) => changed(saved, driveId),
  });
};

/** "Reset to detected": forget the saved list. */
export const useResetFileFields = () => {
  const changed = useFieldsChange();
  return useMutation({
    mutationFn: (driveId: string) => del<ScanFields>(`/api/files/${enc(driveId)}/fields`),
    onSuccess: (saved, driveId) => changed(saved, driveId),
  });
};

/** The Ask screen's answers: kept in the query cache for this session only (never
 * saved, never refetched), newest first. */
export type AskEntry = { id: number; question: string; answer: AskAnswer; costEur: number; cached: boolean };
const askKey = ["ask-session"] as const;

export function useAskSession() {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: askKey,
    queryFn: () => client.getQueryData<AskEntry[]>(askKey) ?? [],
    initialData: [] as AskEntry[],
    staleTime: Infinity,
    gcTime: Infinity,
  });
  const add = (entry: Omit<AskEntry, "id">) =>
    client.setQueryData<AskEntry[]>(askKey, (old = []) => [{ ...entry, id: (old[0]?.id ?? 0) + 1 }, ...old]);
  return { answers: query.data, add };
}

// -- Locks ----------------------------------------------------------------------
// A locked file (Important, or locked by the owner) can be viewed and described but not
// renamed, moved or sent to To Delete. "Unlock" gets a token from the server that the page
// sends with every call until the file is left; the server does the refusing.

export const LOCKED_REASON = "This file is locked. Unlock it to change it.";

/** Every locked file and the locked folders (Important ones and the owner's). */
export const useLocks = () =>
  useQuery({
    queryKey: keys.locks,
    queryFn: () => get<Locks>("/api/locks"),
    staleTime: 30_000,
  });

const lockedIn = (locks: Locks | undefined, driveId: string, path?: string | null) => {
  if (locks === undefined) return false;
  if (locks.files.some((f) => f.drive_id === driveId)) return true;
  const here = path?.normalize("NFC");
  return here != null && locks.folders.some((f) => here === f || here.startsWith(`${f}/`));
};

/** Re-render when a file is unlocked or locked again here. */
function useUnlockVersion() {
  return useSyncExternalStore(
    (listener) => {
      unlockListeners.add(listener);
      return () => unlockListeners.delete(listener);
    },
    () => unlockVersion,
  );
}

/** Whether the page may offer to change a file on disk: `(driveId, marks, path) => blocked`.
 * Blocked means locked and not unlocked for now. Only the server enforces the lock; this
 * keeps the controls honest. */
export function useIsBlocked() {
  const locks = useLocks();
  useUnlockVersion();
  return useCallback(
    (driveId: string, marks?: readonly Mark[] | null, path?: string | null) =>
      !isUnlockedNow(driveId) && ((marks?.includes("important") ?? false) || lockedIn(locks.data, driveId, path)),
    [locks.data],
  );
}

export type FileLock = {
  /** Locked (Important, or by the owner), whether or not unlocked for now. */
  locked: boolean;
  important: boolean;
  /** Unlocked for now: until the page lets this file go. */
  unlockedNow: boolean;
  /** Locked and not unlocked: its rename, move and To Delete are off. */
  blocked: boolean;
  busy: boolean;
  error: string | null;
  lock: () => Promise<void>;
  /** "now": until you leave this file; "for_good": remove the owner's lock (not for an Important file). */
  unlock: (mode: "now" | "for_good") => Promise<void>;
  /** End a temporary unlock at once. */
  relock: () => void;
};

const releaseUnlock = (driveId: string) => {
  if (!unlockTokens.delete(driveId)) return;
  unlocksChanged();
};

/** A file's lock. ``marks``/``path`` are the caller's, when it has them (else the file's
 * record is read). Leaving the file (this component going away) locks it again; hold the
 * hook in one component per open file (``LockControl``). */
export function useFileLock(driveId: string, marks?: readonly Mark[], path?: string | null, holder = false): FileLock {
  const client = useQueryClient();
  const locks = useLocks();
  const detail = useFileDetail(driveId, marks === undefined && driveId !== "");
  useUnlockVersion();
  const known = marks ?? detail.data?.record.marks;
  const filePath = path ?? detail.data?.record.path ?? null;
  const important = known?.includes("important") ?? false;
  const locked = important || lockedIn(locks.data, driveId, filePath);
  const unlockedNow = isUnlockedNow(driveId);
  const pending = useRef(0);
  const [state, setState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });

  const call = async (run: () => Promise<void>) => {
    pending.current += 1;
    setState({ busy: true, error: null });
    try {
      await run();
      setState({ busy: pending.current > 1, error: null });
    } catch (e) {
      setState({ busy: pending.current > 1, error: errorText(e) });
    } finally {
      pending.current -= 1;
    }
  };
  const refresh = () => client.invalidateQueries({ queryKey: keys.locks });

  // leaving the file locks it again, here and on the server
  useEffect(() => {
    if (!holder) return;
    return () => {
      if (unlockTokens.has(driveId)) {
        releaseUnlock(driveId);
        void del(`/api/files/${enc(driveId)}/unlock`).catch(() => {});
      }
    };
  }, [driveId, holder]);

  return {
    locked,
    important,
    unlockedNow,
    blocked: locked && !unlockedNow,
    busy: state.busy,
    error: state.error,
    lock: () =>
      call(async () => {
        await post<LockState>(`/api/files/${enc(driveId)}/lock`);
        await refresh();
      }),
    unlock: (mode) =>
      call(async () => {
        const answer = await post<LockState>(`/api/files/${enc(driveId)}/unlock`, { mode });
        if (mode === "now" && answer.token) {
          unlockTokens.set(driveId, answer.token);
          unlocksChanged();
        }
        await refresh();
      }),
    relock: () => {
      if (!unlockTokens.has(driveId)) return;
      releaseUnlock(driveId);
      void del(`/api/files/${enc(driveId)}/unlock`).catch(() => {});
    },
  };
}

// the page being closed or reloaded: tell the server to lock everything again (it would
// anyway after a while, and a reload forgets the tokens)
if (typeof window !== "undefined") {
  window.addEventListener("pagehide", () => {
    for (const driveId of unlockTokens.keys()) {
      void fetch(`/api/files/${encodeURIComponent(driveId)}/unlock`, {
        method: "DELETE",
        keepalive: true,
        credentials: "same-origin",
        headers: activeArchive ? { "X-Dam-Archive": activeArchive } : {},
      }).catch(() => {});
    }
  });
}
