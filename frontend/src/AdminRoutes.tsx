import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { RequireAuth } from "./lib/auth";
import { Board } from "./pages/Board";
import { Calendar } from "./pages/Calendar";
import { CustomerDetailPage, CustomerList, NewCustomer } from "./pages/Customers";
import { Dashboard } from "./pages/Dashboard";
import { EstimateList, EstimatePage, NewEstimate } from "./pages/Estimates";
import { ExpensesPage } from "./pages/Expenses";
import { InspectionPage } from "./pages/Inspection";
import { PartsPage } from "./pages/Parts";
import { RemindersPage } from "./pages/Reminders";
import { ReportsPage } from "./pages/Reports";
import { InvoiceList, InvoicePage, NewInvoice } from "./pages/Invoices";
import { Login } from "./pages/Login";
import { SettingsPage } from "./pages/Settings";
import { VehiclePage } from "./pages/Vehicle";
import { NewWorkOrder, WorkOrderPage } from "./pages/WorkOrders";

/** Everything under /admin. Loaded as its own bundle so the public site stays light. */
export default function AdminRoutes() {
  return (
    <Routes>
      <Route path="login" element={<Login />} />
      <Route
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
        <Route path="inspections/:id" element={<InspectionPage />} />
        <Route path="estimates" element={<EstimateList />} />
        <Route path="estimates/new" element={<NewEstimate />} />
        <Route path="estimates/:id" element={<EstimatePage />} />
        <Route path="invoices" element={<InvoiceList />} />
        <Route path="invoices/new" element={<NewInvoice />} />
        <Route path="invoices/:id" element={<InvoicePage />} />
        <Route path="reminders" element={<RemindersPage />} />
        <Route path="parts" element={<PartsPage />} />
        <Route path="expenses" element={<ExpensesPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<p className="py-10 text-center">That page doesn't exist.</p>} />
      </Route>
    </Routes>
  );
}
