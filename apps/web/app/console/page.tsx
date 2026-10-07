import { redirect } from "next/navigation";

// The Console's git tools now live on each project: Start → a project → Tools.
export default function ConsolePage() {
  redirect("/start");
}
