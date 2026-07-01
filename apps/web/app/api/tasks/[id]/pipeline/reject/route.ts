import { NextRequest, NextResponse } from "next/server";

// POST /api/tasks/:id/pipeline/reject — human rejects the planning pipeline output
export async function POST(_req: NextRequest, { params }: { params: { id: string } }) {
  const { getPipelineState, updatePipelineState } = await import("@gridiron/planning-pipeline");

  const pipelineState = await getPipelineState(params.id);
  if (!pipelineState || pipelineState.stage !== "awaiting_approval") {
    return NextResponse.json(
      {
        error: {
          code: "conflict",
          message: `Pipeline not awaiting approval (stage: ${pipelineState?.stage ?? "none"})`,
        },
      },
      { status: 409 },
    );
  }

  await updatePipelineState(params.id, { stage: "rejected" });

  return NextResponse.json({ message: "Pipeline plan rejected. Re-trigger to run pipeline again.", taskId: params.id });
}
