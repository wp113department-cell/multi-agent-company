import { redirect } from "next/navigation";

// Approvals now live in Fleet & Approvals.
export default function ApprovalsPage() {
  redirect("/fleet?tab=approvals");
}
