/** "Edit rule" on the Inbox's filing panel: the rule that made the suggestion, opened in the
 * rule sheet to change. The document on screen is the test's source: it is judged on its own
 * line of the proof and left out of the counts (and a picture area says how it scores). */
import { useEffect } from "react";
import { errorText, useRules } from "../../api/client";
import { visible } from "../../text";
import { useToast } from "../Toasts";
import { RuleSheet } from "./RuleSheet";

export function EditRuleSheet({ ruleId, driveId, onClose }: { ruleId: string; driveId: string; onClose: () => void }) {
  const rules = useRules();
  const toast = useToast();
  const rule = rules.data?.rules.find((r) => r.id === ruleId);
  const gone = rules.data !== undefined && rule === undefined;
  const failed = rules.isError;
  useEffect(() => {
    if (!gone && !failed) return;
    toast({
      kind: "error",
      text: failed ? `Could not open rule ${visible(ruleId)}: ${errorText(rules.error)}` : `Rule ${visible(ruleId)} is gone: it was changed or deleted.`,
    });
    onClose();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gone, failed]);
  if (!rule) return null;
  return (
    <RuleSheet
      key={rule.id}
      initial={rule}
      replaces={rule.learned ? rule.id : undefined}
      samplePage
      nearDriveId={driveId}
      sourceDriveId={driveId}
      onClose={onClose}
    />
  );
}
