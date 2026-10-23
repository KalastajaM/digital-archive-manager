import { FileText, Image } from "lucide-react";
import { useState } from "react";
import { type FileRecord, pageUrl, rawUrl } from "../api/client";

const IMAGE_EXTS = new Set(["png", "jpg", "jpeg", "gif", "webp", "avif", "heic", "heif"]);

/** A list row's thumbnail: the first page (or the image), else a file icon. */
export function Thumb({ record }: { record: FileRecord }) {
  const [failed, setFailed] = useState(false);
  const ext = record.ext?.toLowerCase() ?? "";
  const src = ext === "pdf" ? pageUrl(record.drive_id, 1, 400) : IMAGE_EXTS.has(ext) ? rawUrl(record.drive_id) : null;
  if (!src || failed) {
    const Icon = IMAGE_EXTS.has(ext) ? Image : FileText;
    return (
      <span className="thumb thumb-icon" aria-hidden="true">
        <Icon size={18} strokeWidth={1.5} />
      </span>
    );
  }
  return (
    <span className="thumb" aria-hidden="true">
      <img src={src} alt="" loading="lazy" draggable={false} onError={() => setFailed(true)} />
    </span>
  );
}
