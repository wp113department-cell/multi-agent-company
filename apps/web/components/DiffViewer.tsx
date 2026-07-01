"use client";

interface DiffViewerProps {
  diff: string;
}

export function DiffViewer({ diff }: DiffViewerProps) {
  if (!diff || diff.trim() === "") {
    return <p className="text-sm text-slate-500 italic">No diff available.</p>;
  }

  const lines = diff.split("\n");

  return (
    <div className="overflow-x-auto rounded border border-slate-200 bg-slate-950 text-xs font-mono">
      <table className="w-full border-collapse">
        <tbody>
          {lines.map((line, i) => {
            const isAdd = line.startsWith("+") && !line.startsWith("+++");
            const isDel = line.startsWith("-") && !line.startsWith("---");
            const isHunk = line.startsWith("@@");
            const isHeader = line.startsWith("diff ") || line.startsWith("index ") || line.startsWith("---") || line.startsWith("+++");

            let bg = "bg-transparent";
            let color = "text-slate-400";
            if (isAdd) { bg = "bg-green-950"; color = "text-green-300"; }
            else if (isDel) { bg = "bg-red-950"; color = "text-red-300"; }
            else if (isHunk) { bg = "bg-blue-950"; color = "text-blue-300"; }
            else if (isHeader) { color = "text-slate-300"; }

            return (
              <tr key={i} className={bg}>
                <td className="select-none w-10 px-2 py-0 text-right text-slate-600 border-r border-slate-800">
                  {i + 1}
                </td>
                <td className={`px-3 py-0 whitespace-pre ${color}`}>{line || " "}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
