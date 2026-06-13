// kit/queue.tsx — the sign-off queue item (§6.4). The desk's first panel and
// the solo home's "Needs you" queue. Agent-drafted work stops here for the
// human gate; every item carries Approve / Edit-in-place / Ask-back / Dismiss
// (reject-and-reprompt is never the only correction path).

import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

export interface QueueItemProps {
  /** leading slot — a client avatar or a type glyph */
  lead?: ReactNode;
  title: ReactNode;
  sub?: ReactNode;
  /** a stamp/chip on the right of the text (e.g. "drafted", confidence) */
  badge?: ReactNode;
  /** the action row — typically MiniButtons: Approve · Edit · Ask · Dismiss */
  actions?: ReactNode;
  className?: string;
}

export function QueueItem({ lead, title, sub, badge, actions, className }: QueueItemProps) {
  return (
    <div className={cn("queue-item", className)}>
      {lead ? <div className="flex-none">{lead}</div> : null}
      <div className="min-w-0 flex-1">
        <div className="ttl flex items-center gap-2">
          <span className="truncate">{title}</span>
          {badge}
        </div>
        {sub ? <div className="sub">{sub}</div> : null}
      </div>
      {actions ? <div className="acts">{actions}</div> : null}
    </div>
  );
}
