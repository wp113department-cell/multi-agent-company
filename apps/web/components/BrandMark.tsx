/** Multi Agentic Company logo: three connected agent nodes in brand orange. */
export function BrandMark({ size = 32 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id="mac-g" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="#fdba74" />
          <stop offset="0.45" stopColor="#f97316" />
          <stop offset="1" stopColor="#c2410c" />
        </linearGradient>
      </defs>
      <rect width="40" height="40" rx="11" fill="url(#mac-g)" />
      <rect x="1" y="1" width="38" height="19" rx="10" fill="white" opacity="0.14" />
      <path d="M12 26 L20 12 L28 26 Z" stroke="white" strokeWidth="2" strokeLinejoin="round" opacity="0.9" />
      <circle cx="20" cy="12" r="4" fill="white" />
      <circle cx="12" cy="26" r="4" fill="white" />
      <circle cx="28" cy="26" r="4" fill="white" />
    </svg>
  );
}

export const BRAND_NAME = "Multi Agentic Company";
