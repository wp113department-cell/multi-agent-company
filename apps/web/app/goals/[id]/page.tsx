import { redirect } from "next/navigation";

// Goals are project labels now: create and use them in Tasks.
export default function GoalDetailPage() {
  redirect("/tasks");
}
