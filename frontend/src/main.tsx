import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import "./index.css";
import { ApiError } from "./lib/api";
import { AuthProvider, RequireAuth } from "./lib/auth";
import { Board } from "./pages/Board";
import { Calendar } from "./pages/Calendar";
import { CustomerDetailPage, CustomerList, NewCustomer } from "./pages/Customers";
import { Dashboard } from "./pages/Dashboard";
import { EstimateList, EstimatePage, NewEstimate } from "./pages/Estimates";
import { InvoiceList, InvoicePage, NewInvoice } from "./pages/Invoices";
import { Login } from "./pages/Login";
import { SettingsPage } from "./pages/Settings";
import { VehiclePage } from "./pages/Vehicle";
import { NewWorkOrder, WorkOrderPage } from "./pages/WorkOrders";

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

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/admin/login" element={<Login />} />
            <Route
              path="/admin"
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="board" element={<Board />} />
              <Route path="calendar" element={<Calendar />} />
              <Route path="customers" element={<CustomerList />} />
              <Route path="customers/new" element={<NewCustomer />} />
              <Route path="customers/:id" element={<CustomerDetailPage />} />
              <Route path="vehicles/:id" element={<VehiclePage />} />
              <Route path="work-orders/new" element={<NewWorkOrder />} />
              <Route path="work-orders/:id" element={<WorkOrderPage />} />
              <Route path="estimates" element={<EstimateList />} />
              <Route path="estimates/new" element={<NewEstimate />} />
              <Route path="estimates/:id" element={<EstimatePage />} />
              <Route path="invoices" element={<InvoiceList />} />
              <Route path="invoices/new" element={<NewInvoice />} />
              <Route path="invoices/:id" element={<InvoicePage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<p className="py-10 text-center">That page doesn't exist.</p>} />
            </Route>
            {/* The public website arrives in Phase 2; until then the root opens the dashboard. */}
            <Route path="*" element={<Navigate to="/admin" replace />} />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
