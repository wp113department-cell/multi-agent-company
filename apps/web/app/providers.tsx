"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, useEffect } from "react";
import { syncAuthCookie } from "../lib/auth";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient());

  // Sync localStorage token → cookie on every page load so the middleware
  // can read it for server-side navigation checks.
  useEffect(() => {
    syncAuthCookie();
  }, []);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
