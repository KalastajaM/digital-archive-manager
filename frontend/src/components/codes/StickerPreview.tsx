/** A filing code's sticker as it prints (QR, code, label, tick boxes), redrawn shortly
 * after the code or label changes, unsaved edits included. */
import { useEffect, useState } from "react";
import { stickerPreviewUrl } from "../../api/client";
import { visible } from "../../text";

const WAIT_MS = 300;
const CODE = /^[A-Za-z0-9]{1,4}$/;

export function StickerPreview({ code, label }: { code: string; label: string }) {
  const typed = { code: code.trim().toUpperCase(), label: label.trim() };
  const [shown, setShown] = useState(typed);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const timer = setTimeout(() => setShown({ code: typed.code, label: typed.label }), WAIT_MS);
    return () => clearTimeout(timer);
  }, [typed.code, typed.label]);
  useEffect(() => setFailed(false), [shown.code, shown.label]);

  const tip = "The sticker as it prints, with the star and important tick boxes";
  if (!CODE.test(shown.code) || failed) {
    return (
      <div className="sticker-preview empty" data-tip={tip}>
        {shown.code ? "Not a valid code" : "No code yet"}
      </div>
    );
  }
  return (
    <div className="sticker-preview" data-tip={tip}>
      <img
        src={stickerPreviewUrl(shown.code, shown.label)}
        alt={`Sticker ${visible(shown.code)}${shown.label ? `: ${visible(shown.label)}` : ""}`}
        onError={() => setFailed(true)}
      />
    </div>
  );
}
