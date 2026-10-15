// Mirrors backend/app/schemas. Keep in sync when the API changes.

export type Page<T> = { items: T[]; total: number; page: number; page_size: number };

export type User = { id: number; email: string; name: string; role: string };
export type SessionInfo = { user: User; csrf_token: string };

export type Vehicle = {
  id: number;
  customer_id: number;
  year: number | null;
  make: string | null;
  model: string | null;
  trim: string | null;
  vin: string | null;
  license_plate: string | null;
  license_state: string | null;
  mileage: number | null;
  engine: string | null;
  transmission: string | null;
  color: string | null;
  internal_notes: string | null;
  display_name: string;
  archived_at: string | null;
};

export type Customer = {
  id: number;
  first_name: string;
  last_name: string;
  full_name: string;
  phone: string | null;
  email: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  preferred_contact: "phone" | "text" | "email" | null;
  internal_notes: string | null;
  customer_since: string;
  archived_at: string | null;
};

export type CustomerDetail = Customer & {
  vehicles: Vehicle[];
  balance_cents: number;
  lifetime_paid_cents: number;
};

export type CustomerListItem = {
  id: number;
  full_name: string;
  phone: string | null;
  email: string | null;
  vehicle_count: number;
  balance_cents: number;
  archived_at: string | null;
};

export type LineKind = "labor" | "part" | "fee" | "discount";

export type LineItem = {
  id: number;
  position: number;
  kind: LineKind;
  description: string;
  quantity: string;
  unit_price_cents: number;
  unit_cost_cents: number | null;
  markup_pct: string | null;
  taxable: boolean;
  line_total_cents: number;
  part_number: string | null;
  vendor_name: string | null;
  warranty_months: number | null;
  warranty_miles: number | null;
  warranty_notes: string | null;
};

export type LineItemIn = {
  kind: LineKind;
  description: string;
  quantity?: string;
  unit_price_cents?: number | null;
  unit_cost_cents?: number | null;
  markup_pct?: string | null;
  taxable?: boolean | null;
  part_number?: string | null;
  vendor_name?: string | null;
  warranty_months?: number | null;
  warranty_miles?: number | null;
  warranty_notes?: string | null;
};

export type Totals = {
  tax_rate: string;
  labor_cents: number;
  parts_cents: number;
  fees_cents: number;
  discount_cents: number;
  taxable_cents: number;
  tax_cents: number;
  total_cents: number;
};

export type Party = {
  customer_id: number;
  customer_name: string;
  customer_phone: string | null;
  customer_email: string | null;
  vehicle_id: number;
  vehicle_name: string;
  vin: string | null;
  license_plate: string | null;
};

export const WO_STATUSES = [
  "new",
  "checked_in",
  "diagnosing",
  "waiting_approval",
  "approved",
  "in_repair",
  "quality_check",
  "ready_for_pickup",
  "completed",
  "cancelled",
] as const;
export type WorkOrderStatus = (typeof WO_STATUSES)[number];

export type WorkOrder = Totals & {
  id: number;
  number: string;
  status: WorkOrderStatus;
  customer_id: number;
  vehicle_id: number;
  concern: string | null;
  customer_notes: string | null;
  internal_notes: string | null;
  mileage_in: number | null;
  mileage_out: number | null;
  promised_at: string | null;
  qc_checklist: Record<string, boolean>;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
  party: Party;
  items: LineItem[];
  invoice_ids: number[];
  estimate_ids: number[];
};

export type WorkOrderCard = {
  id: number;
  number: string;
  status: WorkOrderStatus;
  customer_name: string;
  vehicle_name: string;
  concern: string | null;
  total_cents: number;
  promised_at: string | null;
  updated_at: string;
};

export type Estimate = Totals & {
  id: number;
  number: string;
  version: number;
  status: string;
  customer_id: number;
  vehicle_id: number;
  work_order_id: number | null;
  concern: string | null;
  customer_notes: string | null;
  internal_notes: string | null;
  mileage: number | null;
  expires_on: string | null;
  sent_at: string | null;
  viewed_at: string | null;
  approved_at: string | null;
  declined_at: string | null;
  locked_at: string | null;
  decision_method: string | null;
  decision_note: string | null;
  converted_at: string | null;
  created_at: string;
  party: Party;
  items: LineItem[];
};

export type Payment = {
  id: number;
  invoice_id: number;
  amount_cents: number;
  method: "cash" | "check" | "card" | "online" | "other";
  status: string;
  paid_at: string;
  reference: string | null;
  provider_ref: string | null;
  notes: string | null;
  voided_at: string | null;
  void_reason: string | null;
  invoice_number?: string | null;
};

export type Invoice = Totals & {
  id: number;
  number: string;
  status: string;
  customer_id: number;
  vehicle_id: number;
  work_order_id: number | null;
  issue_date: string;
  due_date: string | null;
  mileage: number | null;
  customer_notes: string | null;
  internal_notes: string | null;
  amount_paid_cents: number;
  balance_cents: number;
  sent_at: string | null;
  paid_at: string | null;
  voided_at: string | null;
  void_reason: string | null;
  party: Party;
  items: LineItem[];
  payments: Payment[];
};

export type DocumentListItem = {
  id: number;
  number: string;
  status: string;
  customer_name: string;
  vehicle_name: string;
  total_cents: number;
  balance_cents: number | null;
  date: string;
};

export type Appointment = {
  id: number;
  status: string;
  customer_id: number | null;
  vehicle_id: number | null;
  work_order_id: number | null;
  starts_at: string | null;
  ends_at: string | null;
  requested_service: string | null;
  concern: string | null;
  customer_notes: string | null;
  internal_notes: string | null;
  source: string;
  preferred_date: string | null;
  preferred_time: string | null;
  contact_name: string | null;
  contact_phone: string | null;
  contact_email: string | null;
  vehicle_description: string | null;
  reported_mileage: number | null;
  customer_name: string | null;
  vehicle_name: string | null;
};

export type Business = {
  id: number;
  name: string;
  phone: string | null;
  email: string | null;
  website: string | null;
  address_line1: string | null;
  address_line2: string | null;
  city: string | null;
  state: string | null;
  postal_code: string | null;
  service_area: string | null;
  hours: Record<string, { open: string; close: string } | null>;
  about_text: string | null;
  certifications: string | null;
  offers_towing: boolean;
  towing_info: string | null;
  financing_info: string | null;
  timezone: string;
  tax_rate: string;
  tax_labor: boolean;
  tax_parts: boolean;
  tax_fees: boolean;
  default_labor_rate_cents: number;
  default_parts_markup_pct: string;
  invoice_prefix: string;
  estimate_prefix: string;
  work_order_prefix: string;
  invoice_due_days: number;
  estimate_valid_days: number;
  authorization_statement: string;
  allow_typed_signature: boolean;
  invoice_footer: string | null;
};

export type Service = {
  id: number;
  name: string;
  slug: string;
  category: string | null;
  description: string | null;
  starting_price_cents: number | null;
  sort_order: number;
  is_published: boolean;
};

export type History = {
  work_orders: DocumentListItem[];
  estimates: DocumentListItem[];
  invoices: DocumentListItem[];
  appointments: { id: number; status: string; starts_at: string | null; requested_service: string | null; vehicle_id: number | null }[];
  payments: { id: number; invoice_id: number; amount_cents: number; method: string; status: string; paid_at: string }[];
};

export type AuditEntry = {
  id: number;
  occurred_at: string;
  actor: string;
  user_name: string | null;
  action: string;
  details: Record<string, unknown>;
};
