import { createContext, useContext, useEffect, useId } from "react";

export const DraftContext = createContext<{
  report: (id: string, label: string | null) => void;
  canProceed: () => boolean;
}>({ report: () => {}, canProceed: () => true });

/** Local edits remain local until saved; generation must use the saved version. */
export function useDraftGuard(label: string, dirty: boolean) {
  const id = useId();
  const context = useContext(DraftContext);
  useEffect(() => {
    context.report(id, dirty ? label : null);
    return () => context.report(id, null);
  }, [id, label, dirty, context.report]);
  return context.canProceed;
}
