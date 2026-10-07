"use client";

/**
 * Login background: a living network of AI agents. The company hub sits in
 * the middle, specialist agents around it; lines connect them and small
 * orange data pulses travel along the lines, so the page shows the product's
 * idea (a team of agents working together) at a glance. Purely decorative
 * (aria-hidden); still for people who prefer reduced motion.
 */

import { useEffect, useState } from "react";
import { iconShapes } from "./Icon";

type Node = { id: string; x: number; y: number; icon: string; label: string; r: number };

// viewBox 1600 x 1000, pinned to the viewport; nodes sit around the edges and
// below the sign-in card (which covers roughly x 900-1540, y 150-740), so
// they stay visible and the text stays readable
const NODES: Node[] = [
  { id: "hub", x: 1200, y: 845, icon: "hub", label: "", r: 30 },
  { id: "planner", x: 860, y: 90, icon: "compass", label: "Planner", r: 18 },
  { id: "developer", x: 1450, y: 75, icon: "code", label: "Developer", r: 18 },
  { id: "tester", x: 1570, y: 640, icon: "flask", label: "Tester", r: 17 },
  { id: "reviewer", x: 1480, y: 900, icon: "search", label: "Reviewer", r: 17 },
  { id: "security", x: 950, y: 950, icon: "shield", label: "Security", r: 17 },
  { id: "devops", x: 600, y: 900, icon: "rocket", label: "DevOps", r: 16 },
  { id: "docs", x: 90, y: 780, icon: "book", label: "Docs", r: 16 },
  { id: "memory", x: 70, y: 180, icon: "lightbulb", label: "Memory", r: 16 },
];

// only the spokes: every agent talks to the hub, nothing else, so the
// background stays calm
const LINKS: [string, string][] = NODES.filter((n) => n.id !== "hub").map((n) => ["hub", n.id]);

const byId: Record<string, Node> = Object.fromEntries(NODES.map((n) => [n.id, n]));
const node = (id: string): Node => byId[id] as Node;
const HUB = node("hub");

function usePrefersReducedMotion(): boolean {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduce(mq.matches);
    const on = () => setReduce(mq.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduce;
}

export function AgentNetwork() {
  const reduce = usePrefersReducedMotion();
  return (
    <svg
      aria-hidden="true"
      className="pointer-events-none fixed inset-0 h-full w-full opacity-35 sm:opacity-100"
      viewBox="0 0 1600 1000"
      preserveAspectRatio="xMidYMid slice"
    >
      <defs>
        <radialGradient id="an-glow">
          <stop offset="0" stopColor="#fb923c" stopOpacity="0.22" />
          <stop offset="1" stopColor="#fb923c" stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* soft glow behind the hub */}
      <circle cx={HUB.x} cy={HUB.y} r="220" fill="url(#an-glow)" />

      {/* links + travelling data pulses */}
      {LINKS.map(([a, b], i) => {
        const p = node(a);
        const q = node(b);
        const d = `M${p.x},${p.y} L${q.x},${q.y}`;
        const dur = 3.2 + (i % 5) * 0.9;
        return (
          <g key={`${a}-${b}`}>
            <path
              d={d}
              stroke="#fdba74"
              strokeWidth="1"
              strokeDasharray="3 8"
              opacity="0.55"
              fill="none"
            >
              {!reduce && (
                <animate
                  attributeName="stroke-dashoffset"
                  from="0"
                  to="-24"
                  dur="1.6s"
                  repeatCount="indefinite"
                />
              )}
            </path>
            {!reduce && i % 2 === 0 && (
              <circle r="3" fill="#f26b1d">
                <animateMotion
                  dur={`${dur}s`}
                  repeatCount="indefinite"
                  path={i % 2 ? `M${q.x},${q.y} L${p.x},${p.y}` : d}
                  begin={`${(i * 0.37) % 3}s`}
                />
                <animate
                  attributeName="opacity"
                  values="0;1;1;0"
                  dur={`${dur}s`}
                  repeatCount="indefinite"
                  begin={`${(i * 0.37) % 3}s`}
                />
              </circle>
            )}
          </g>
        );
      })}

      {/* agent nodes */}
      {NODES.map((n, i) => (
        <g key={n.id} transform={`translate(${n.x},${n.y})`}>
          {!reduce && (
            <circle r={n.r} fill="none" stroke="#fb923c" strokeWidth="1.5" opacity="0.5">
              <animate
                attributeName="r"
                values={`${n.r};${n.r + 10};${n.r}`}
                dur={`${3 + (i % 3)}s`}
                repeatCount="indefinite"
                begin={`${i * 0.4}s`}
              />
              <animate
                attributeName="opacity"
                values="0.5;0;0.5"
                dur={`${3 + (i % 3)}s`}
                repeatCount="indefinite"
                begin={`${i * 0.4}s`}
              />
            </circle>
          )}
          <circle
            r={n.r}
            fill={n.id === "hub" ? "#f26b1d" : "#ffffff"}
            stroke="#fdba74"
            strokeWidth="2"
          />
          {n.id === "hub" ? (
            // the company mark: three connected agents
            <g stroke="#fff" strokeWidth="2.5" fill="#fff">
              <path d="M-10 8 L0 -8 L10 8 Z" fill="none" strokeLinejoin="round" />
              <circle cx="0" cy="-8" r="4" />
              <circle cx="-10" cy="8" r="4" />
              <circle cx="10" cy="8" r="4" />
            </g>
          ) : (
            <svg
              x={-n.r * 0.5}
              y={-n.r * 0.5}
              width={n.r}
              height={n.r}
              viewBox="0 0 24 24"
              fill="none"
              stroke="#ea580c"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              {iconShapes(n.icon)}
            </svg>
          )}
          {n.label && (
            <text
              y={n.r + 16}
              textAnchor="middle"
              fontSize="12"
              fontWeight="600"
              fill="#9a3412"
              opacity="0.75"
              style={{ fontFamily: "var(--font-sans), sans-serif" }}
            >
              {n.label}
            </text>
          )}
        </g>
      ))}
    </svg>
  );
}
