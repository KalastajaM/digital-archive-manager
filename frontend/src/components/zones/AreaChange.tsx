/** What happens when an area drawn on page 1 is moved or resized: a rule's area opens the
 * rule sheet with the changed area (and the replay, with how the rule did before, so the
 * owner sees the effect on past documents before saving); the archive-wide address area asks
 * once and is saved to the settings. */
import { useEffect, useState } from "react";
import {
  type Area,
  errorText,
  type PageBox,
  type Rule,
  useAreaPicture,
  usePeople,
  useRules,
  useSavePeople,
  useSetAddressArea,
} from "../../api/client";
import { useStyle } from "../../appearance";
import { visible } from "../../text";
import { RuleSheet } from "../rules/RuleSheet";
import { useToast } from "../Toasts";
import { Sheet } from "../ui/Sheet";

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
    return <AddressAreaSheet driveId={driveId} document={area.document ?? false} box={box} onClose={onClose} />;
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

/** The address area was moved on ``driveId``. The New look asks whether the new place is
 * for this document only or for all letters (``document``: it was this document's own
 * area, which "All letters" then takes away so the document follows them again). */
function AddressAreaSheet({ driveId, document, box, onClose }: { driveId: string; document: boolean; box: PageBox; onClose: () => void }) {
  const [look] = useStyle();
  const isNew = look === "new";
  const people = usePeople();
  const save = useSavePeople();
  const setArea = useSetAddressArea();
  const toast = useToast();
  const [problem, setProblem] = useState<string | null>(null);
  const busy = save.isPending || setArea.isPending;
  const act = async (action: () => Promise<unknown>, done: string) => {
    setProblem(null);
    try {
      await action();
      toast({ kind: "info", text: done });
      onClose();
    } catch (e) {
      setProblem(errorText(e));
    }
  };
  const saveAll = () =>
    act(async () => {
      await save.mutateAsync({ people: people.data?.people ?? [], address_zone: box });
      if (document) await setArea.mutateAsync({ driveId, box: "general" });
    }, "Address area saved for all letters.");
  const saveThis = () => act(() => setArea.mutateAsync({ driveId, box }), "Address area saved for this document.");
  return (
    <Sheet
      open
      title="Change the address area"
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose}>Cancel</button>
          {isNew && (
            <button type="button" className={document ? "primary" : undefined} disabled={busy} onClick={() => void saveThis()}>
              This document only
            </button>
          )}
          <button
            type="button"
            className={isNew && document ? undefined : "primary"}
            disabled={!people.data || busy}
            onClick={() => void saveAll()}
          >
            {isNew ? "All letters" : "Save"}
          </button>
        </>
      }
    >
      {isNew ? (
        <>
          <p>Look for the person a letter is for in this area on this document only, or on all letters?</p>
          <p className="hint">
            All letters changes who is found on letters that are read from now on and on the ones in the Inbox. Documents
            with an address area of their own keep it.
          </p>
        </>
      ) : (
        <>
          <p>Look for the person a letter is for in this area on every letter?</p>
          <p className="hint">It changes who is found on letters that are read from now on and on the ones in the Inbox.</p>
        </>
      )}
      {problem && (
        <p className="error" role="alert">
          {visible(problem)}
        </p>
      )}
    </Sheet>
  );
}
