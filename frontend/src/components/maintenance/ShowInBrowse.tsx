/** A check row's icon buttons: Quick Look (the file in the overlay, without leaving the
 * check) and Show in Browse (the sidebar's Browse icon). */
import { Eye, FolderTree } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { IconButton } from "../ui/IconButton";

const ICON = { size: 16, strokeWidth: 1.75 } as const;

const folderOf = (path: string) => (path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "");
/** Browse at the file's folder with the file selected (shown in the right-hand panel). */
export const browseTo = (path: string, driveId: string) =>
  `/browse?${new URLSearchParams({ path: folderOf(path), select: driveId })}`;
/** Browse inside a folder (folders are opened, not selected). */
export const browseInto = (path: string) => `/browse?${new URLSearchParams({ path })}`;

export function ShowInBrowse({ to, label = "Show in Browse" }: { to: string; label?: string }) {
  const navigate = useNavigate();
  return <IconButton icon={<FolderTree {...ICON} />} label={label} className="tip-end" onClick={() => navigate(to)} />;
}

export function QuickLookButton({ onClick }: { onClick: () => void }) {
  return <IconButton icon={<Eye {...ICON} />} label="Quick Look" onClick={onClick} />;
}
