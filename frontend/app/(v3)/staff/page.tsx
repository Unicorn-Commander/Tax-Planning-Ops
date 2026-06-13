import { SurfaceStub } from "../shell";

export default function StaffPage() {
  return (
    <SurfaceStub
      no="10"
      title="The Staff"
      intent="Agents as staff: avatar + presence, model line, standing orders (§, editable), the autonomy dial, stats, and recent decisions including declines/escalations ('agents with judgment, on the record'). Doors: Console / MCP / API + live traffic with verdicts. House rules HR-01…05."
      mockup="10-staff.html"
      live="GET /lifecycle/audit/verify (audit chain)."
      additive="agent registry/status + the real MCP server (a stub today — pair this surface with the MCP build) + journal tail."
    />
  );
}
