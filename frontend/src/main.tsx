import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Link, Route, Routes } from "react-router-dom";
import "./index.css";
import { ApiError } from "./lib/api";
import { AuthProvider } from "./lib/auth";
import { BookPage } from "./public/Book";
import { DocumentLink } from "./public/DocumentLink";
import { Home } from "./public/Home";
import { AboutPage, ContactPage, ServicesPage } from "./public/Pages";
import { PublicLayout } from "./public/PublicLayout";

const AdminRoutes = lazy(() => import("./AdminRoutes"));

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
      refetchOnWindowFocus: true,
    },
  },
  // After any successful change, refresh what's on screen. One mechanic, small data:
  // simple invalidation is more reliable than hand-tuned cache updates.
  mutationCache: new MutationCache({
    onSuccess: () => {
      queryClient.invalidateQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  }),
});

function NotFound() {
  return (
    <div className="mx-auto max-w-lg px-4 py-20">
      <h1 className="font-display text-4xl font-bold">Page not found</h1>
      <Link to="/" className="mt-4 inline-block min-h-12 content-center underline underline-offset-4">Go to the home page</Link>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route
            path="/admin/*"
            element={
              <AuthProvider>
                <Suspense fallback={<p className="p-8 text-center text-steel-2">Loading…</p>}>
                  <AdminRoutes />
                </Suspense>
              </AuthProvider>
            }
          />
          <Route path="/d/:token" element={<DocumentLink />} />
          <Route element={<PublicLayout />}>
            <Route index element={<Home />} />
            <Route path="services" element={<ServicesPage />} />
            <Route path="about" element={<AboutPage />} />
            <Route path="contact" element={<ContactPage />} />
            <Route path="book" element={<BookPage />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
