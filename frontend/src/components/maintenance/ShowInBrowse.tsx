/** A check row's icon buttons: Quick Look (the file in the overlay, without leaving the
 * check) and Show in Browse (the sidebar's Browse icon). */
import { Eye, FolderTree } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { IconButton } from "../ui/IconButton";

const ICON = { size: 16, strokeWidth: 1.75 } as const;

export function ShowInBrowse({ to, label = "Show in Browse" }: { to: string; label?: string }) {
  const navigate = useNavigate();
  return <IconButton icon={<FolderTree {...ICON} />} label={label} className="tip-end" onClick={() => navigate(to)} />;
}

export function QuickLookButton({ onClick }: { onClick: () => void }) {
  return <IconButton icon={<Eye {...ICON} />} label="Quick Look" onClick={onClick} />;
}
