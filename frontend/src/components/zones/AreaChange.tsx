/** What happens when an area drawn on page 1 is moved or resized: a rule's area opens the
 * rule sheet with the changed area (and the replay, with how the rule did before, so the
 * owner sees the effect on past documents before saving). The address area moves on this
 * document only, at once and with Undo (the area for all letters is set in Settings). */
import { useEffect, useRef, useState } from "react";
import {
  type Area,
  errorText,
  type PageBox,
  type Rule,
  useAreaPicture,
  useRules,
  useSetAddressArea,
} from "../../api/client";
import { RuleSheet } from "../rules/RuleSheet";
import { undoAction, useToast } from "../Toasts";

/** ``rule`` with the box of the area changed. A picture area also gets ``image``, the crop
 * cut again for the new box. */
export function withChangedArea(rule: Rule, area: Area, box: PageBox, image?: string): Rule {
  if (area.kind === "address") return { ...rule, person_zone: box };
  return {
    ...rule,
    when: { ...rule.when, zones: rule.when.zones.map((z, i) => (i === area.index ? { ...z, box, ...(image ? { image } : {}) } : z)) },
  };
}

/** ``driveId``: the document the area was changed on (a picture area is cut again from it). */
export function AreaChange({ driveId, area, box, onClose }: { driveId: string; area: Area; box: PageBox; onClose: () => void }) {
  if (area.kind === "address" && area.rule_id === "")
    return <MoveDocumentArea driveId={driveId} area={area} box={box} onClose={onClose} />;
  return <RuleAreaSheet driveId={driveId} area={area} box={box} onClose={onClose} />;
}

function RuleAreaSheet({ driveId, area, box, onClose }: { driveId: string; area: Area; box: PageBox; onClose: () => void }) {
  const rules = useRules();
  const toast = useToast();
  const recut = useAreaPicture();
  // a picture area's crop is cut again from the current document before the sheet opens.
  // The cut belongs to one area and one box: when either changes, or the sheet goes, a reply
  // that comes back later is dropped (it would give the newer box another box's crop).
  const [image, setImage] = useState<string | null>(null);
  const picture = area.kind === "image";
  const boxKey = box.join(",");
  useEffect(() => {
    if (!picture) return;
    let current = true;
    setImage(null);
    recut
      .mutateAsync({ driveId, box, save: true, ruleId: area.rule_id })
      .then((cut) => {
        if (current) setImage(cut.image ?? null);
      })
      .catch((e) => {
        if (!current) return;
        toast({ kind: "error", text: errorText(e) });
        onClose();
      });
    return () => {
      current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [picture, driveId, area.rule_id, area.index, boxKey]);
  const rule = rules.data?.rules.find((r) => r.id === area.rule_id);
  const gone = rules.data !== undefined && rule === undefined;
  useEffect(() => {
    if (!gone) return;
    toast({ kind: "error", text: `Rule ${area.rule_id} is not there any more.` });
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gone]);
  if (!rule || (picture && image === null)) return null;
  return (
    <RuleSheet initial={withChangedArea(rule, area, box, image ?? undefined)} replaces={rule.id} before={rule} nearDriveId={driveId} sourceDriveId={driveId} onClose={onClose} />
  );
}

/** The address area was moved on ``driveId``: the new place is this document's
 * own area, saved at once. Undo gives back what it had: its own earlier box, or the usual
 * area. */
function MoveDocumentArea({ driveId, area, box, onClose }: { driveId: string; area: Area; box: PageBox; onClose: () => void }) {
  const setArea = useSetAddressArea();
  const toast = useToast();
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const before: PageBox | "general" = area.document ? area.box : "general";
    setArea
      .mutateAsync({ driveId, box })
      .then(() =>
        toast({
          kind: "info",
          text: "Address area moved on this document.",
          action: undoAction(() => setArea.mutate({ driveId, box: before })),
        }),
      )
      .catch((e) => toast({ kind: "error", text: errorText(e) }))
      .finally(onClose);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return null;
}
