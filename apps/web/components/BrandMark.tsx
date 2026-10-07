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
      
      <rect width="40" height="40" rx="11" fill="#f26b1d" />
      <path d="M12 26 L20 12 L28 26 Z" stroke="white" strokeWidth="2" strokeLinejoin="round" opacity="0.9" />
      <circle cx="20" cy="12" r="4" fill="white" />
      <circle cx="12" cy="26" r="4" fill="white" />
      <circle cx="28" cy="26" r="4" fill="white" />
    </svg>
  );
}

export const BRAND_NAME = "Multi Agentic Company";
