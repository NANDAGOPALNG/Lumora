import { QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { AuthProvider } from "@/components/providers/auth-provider";
import { createAppQueryClient } from "@/components/providers/query-provider";
import { setAccessToken } from "@/lib/auth/session";

/** Renders UI inside the real AuthProvider and a fresh query client (no retries, for speed). */
export function renderApp(ui: React.ReactNode, { token = "token-ada" as string | null } = {}) {
  if (token) setAccessToken(token);
  const client = createAppQueryClient();
  client.setDefaultOptions({ queries: { staleTime: 30_000, retry: false, retryDelay: 0 } });
  const view = render(
    <AuthProvider>
      <QueryClientProvider client={client}>{ui}</QueryClientProvider>
    </AuthProvider>,
  );
  return { ...view, client };
}
