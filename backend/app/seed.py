"""Placeholder shop details and demo data for development.

Everything here is fictional: the shop name, address, and 555-01xx phone numbers are
placeholders to replace in Settings. Run with `uv run python -m app.tasks seed-demo`.
The demo walks one repair through the whole workflow so every screen has something on it.
"""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db import get_engine
from app.models import Appointment, Customer, Service, User, Vehicle
from app.schemas.common import digits_only
from app.schemas.documents import (
    DecisionIn,
    EstimateCreate,
    InvoiceFromWorkOrder,
    LineItemIn,
    PaymentIn,
    WorkOrderCreate,
)
from app.services import history, inspections, workflow
from app.services.business import get_business

DEMO_EMAIL = "demo@example.com"
DEMO_PASSWORD = "demo-password-123"  # noqa: S105 - development only; seed-demo refuses to run in production

PLACEHOLDER_SHOP = {
    "name": "Ridgeline Auto Repair",
    "phone": "(555) 010-0142",
    "email": "service@example.com",
    "website": None,
    "address_line1": "100 Sample Road",
    "city": "Anytown",
    "state": "NY",
    "postal_code": "12345",
    "service_area": "Anytown and surrounding communities within about 20 miles.",
    "hours": {
        "mon": {"open": "08:00", "close": "17:30"},
        "tue": {"open": "08:00", "close": "17:30"},
        "wed": {"open": "08:00", "close": "17:30"},
        "thu": {"open": "08:00", "close": "17:30"},
        "fri": {"open": "08:00", "close": "17:30"},
        "sat": {"open": "09:00", "close": "13:00"},
        "sun": None,
    },
    "about_text": (
        "PLACEHOLDER: A one-bay independent shop run by a single experienced mechanic. "
        "You talk directly to the person working on your car, get a written estimate before "
        "any work starts, and see photos of what was found. Replace this with the real story."
    ),
    "certifications": "PLACEHOLDER: list ASE certifications and years of experience here.",
    "offers_towing": False,
    "financing_info": None,
    "tax_rate": Decimal("8.0000"),
    "tax_labor": False,
    "tax_parts": True,
    "tax_fees": False,
    "default_labor_rate_cents": 12000,
    "default_parts_markup_pct": Decimal("40.00"),
    "invoice_due_days": 0,
    "estimate_valid_days": 30,
    "invoice_footer": "Thank you for your business. PLACEHOLDER warranty terms go here.",
}

SERVICES = [
    (
        "Oil Changes",
        "Maintenance",
        "Conventional, blend, and full synthetic oil with filter.",
        4995,
    ),
    (
        "Brake Service",
        "Brakes",
        "Inspection, pad replacement, fluid flush, and caliper service.",
        None,
    ),
    ("Brake Replacement", "Brakes", "Pads, rotors, and hardware for one axle or both.", None),
    ("Tires", "Tires & Wheels", "Mounting, balancing, rotation, and flat repair.", None),
    ("Wheel Alignment", "Tires & Wheels", "Alignment check and adjustment to spec.", None),
    (
        "Battery Replacement",
        "Electrical",
        "Battery testing, replacement, and terminal service.",
        None,
    ),
    ("Diagnostics", "Diagnostics", "Check-engine light and drivability diagnosis.", None),
    ("Engine Repair", "Engine", "Gaskets, timing components, and engine performance repair.", None),
    ("Transmission Service", "Drivetrain", "Fluid service and transmission diagnosis.", None),
    ("Cooling System", "Engine", "Radiators, water pumps, thermostats, and hoses.", None),
    ("Suspension", "Steering & Suspension", "Shocks, struts, control arms, and bushings.", None),
    ("Steering", "Steering & Suspension", "Tie rods, racks, and power steering repair.", None),
    ("Electrical", "Electrical", "Starting, charging, lighting, and wiring repair.", None),
    ("AC / Heating", "Climate", "AC recharge, leak diagnosis, and heater repair.", None),
    (
        "Preventative Maintenance",
        "Maintenance",
        "Factory-schedule maintenance and fluid services.",
        None,
    ),
    ("Inspection", "Maintenance", "Pre-purchase and general vehicle inspections.", None),
    ("Other Repairs", "General", "Not listed? Call and ask.", None),
]


def _customer(db, first, last, phone, email, **kw) -> Customer:
    c = Customer(
        first_name=first,
        last_name=last,
        phone=phone,
        phone_digits=digits_only(phone),
        email=email,
        **kw,
    )
    db.add(c)
    db.flush()
    return c


def _vehicle(db, customer, **kw) -> Vehicle:
    v = Vehicle(customer_id=customer.id, **kw)
    db.add(v)
    db.flush()
    return v


def _apply_shop_profile(db: Session) -> None:
    business = get_business(db)
    for k, v in PLACEHOLDER_SHOP.items():
        setattr(business, k, v)
    if db.scalar(select(func.count()).select_from(Service)):
        return
    for i, (name, cat, desc, price) in enumerate(SERVICES):
        slug = name.lower().replace(" / ", "-").replace(" ", "-")
        db.add(
            Service(
                name=name,
                slug=slug,
                category=cat,
                description=desc,
                starting_price_cents=price,
                sort_order=i,
            )
        )


def setup_shop() -> dict:
    """Load the placeholder shop profile and the standard services list into a fresh
    database, so the public site isn't empty on day one. Safe in production: it adds no
    customers and no logins, and refuses once the shop has been set up."""
    with Session(get_engine()) as db:
        business = get_business(db)
        if business.name != "My Auto Repair" or db.scalar(
            select(func.count()).select_from(Service)
        ):
            return {"ok": False, "error": "The shop is already set up; nothing changed."}
        _apply_shop_profile(db)
        db.commit()
        return {"ok": True, "task": "setup_shop", "services": len(SERVICES)}


def seed_demo() -> dict:
    with Session(get_engine()) as db:
        if db.scalar(select(func.count()).select_from(Customer)):
            return {"ok": False, "error": "Database already has customers; demo data not loaded."}

        _apply_shop_profile(db)

        user = db.scalar(select(User).where(User.email == DEMO_EMAIL))
        if user is None:
            user = User(
                email=DEMO_EMAIL,
                name="Demo Mechanic",
                password_hash=hash_password(DEMO_PASSWORD),
                role="owner",
            )
            db.add(user)
        db.flush()

        # --- The full workflow: John Smith's 2018 Accord, front brakes, $650.00
        john = _customer(
            db,
            "John",
            "Smith",
            "(555) 010-0101",
            "john.smith@example.com",
            preferred_contact="text",
            internal_notes="Prefers texts. Usually waits in the lobby.",
        )
        accord = _vehicle(
            db,
            john,
            year=2018,
            make="Honda",
            model="Accord",
            trim="LX",
            vin="1HGCV1F13JA000001",
            license_plate="DEM0101",
            license_state="NY",
            mileage=61200,
            engine="1.5L Turbo I4",
            transmission="CVT",
            color="Silver",
        )

        wo = workflow.create_work_order(
            db,
            user,
            WorkOrderCreate(
                customer_id=john.id,
                vehicle_id=accord.id,
                mileage_in=61240,
                concern="Customer states vehicle shakes when braking from highway speed.",
                items=[
                    LineItemIn(
                        kind="labor",
                        description="Replace front brake pads and rotors",
                        quantity=Decimal("2.0"),
                    ),
                    LineItemIn(
                        kind="part",
                        description="Front brake pad set (ceramic)",
                        part_number="DEMO-PAD-1001",
                        unit_price_cents=8911,
                        unit_cost_cents=5400,
                        vendor_name="Sample Parts Supply",
                        warranty_months=12,
                        warranty_miles=12000,
                    ),
                    LineItemIn(
                        kind="part",
                        description="Front brake rotor",
                        quantity=Decimal("2"),
                        part_number="DEMO-ROT-2002",
                        unit_price_cents=13600,
                        unit_cost_cents=8200,
                        vendor_name="Sample Parts Supply",
                        warranty_months=12,
                        warranty_miles=12000,
                    ),
                    LineItemIn(
                        kind="fee", description="Shop supplies and disposal", unit_price_cents=2000
                    ),
                ],
            ),
        )
        workflow.change_work_order_status(db, user, wo, "diagnosing", False)

        # Digital inspection with traffic-light findings (no demo photos: the camera adds
        # real ones).
        insp = inspections.start(db, user, wo)
        findings = {
            "Brakes": (
                "urgent",
                "Front pads at 2 mm. Front rotors below minimum thickness and warped, "
                "which causes the shake when braking.",
                "Replace front pads and rotors",
                63000,
            ),
            "Tires": (
                "monitor",
                "Rear tires at 4/32 in. Plan on replacing within 6 months.",
                None,
                None,
            ),
            "Fluids": ("monitor", "Brake fluid is dark.", "Brake fluid flush at next visit", 11000),
        }
        for it in insp.items:
            status, notes, rec, cost = findings.get(it.category, ("good", None, None, None))
            inspections.update_item(
                db,
                user,
                it,
                {
                    "status": status,
                    "notes": notes,
                    "recommendation": rec,
                    "estimated_cost_cents": cost,
                },
            )
        inspections.update(
            db,
            user,
            insp,
            {
                "summary": "Front brakes need replacing now. Everything else is in good shape; "
                "keep an eye on the rear tires.",
                "status": "completed",
            },
        )
        est = workflow.create_estimate(
            db,
            user,
            EstimateCreate(
                customer_id=john.id,
                vehicle_id=accord.id,
                work_order_id=wo.id,
                customer_notes="Front rotors are below minimum thickness and warped; "
                "pads at 2 mm. Rear brakes measured fine.",
            ),
        )
        assert est.total_cents == 65000, est.total_cents
        est.inspection_id = insp.id
        workflow.mark_estimate_sent(db, user, est)
        workflow.record_estimate_decision(
            db,
            user,
            est,
            DecisionIn(decision="approved", method="phone", note="Approved by phone."),
        )
        workflow.convert_estimate(db, user, est)
        for status in ("in_repair", "quality_check"):
            workflow.change_work_order_status(db, user, wo, status, False)
        wo.mileage_out = 61252
        inv = workflow.invoice_from_work_order(db, user, wo, InvoiceFromWorkOrder())
        workflow.mark_invoice_sent(db, user, inv)
        workflow.record_manual_payment(
            db,
            user,
            inv.id,
            PaymentIn(amount_cents=65000, method="card", reference="Terminal, Visa ending 0000"),
        )
        wo.qc_checklist = {
            k: True
            for k in (
                "repair_completed",
                "vehicle_inspected",
                "test_drive_completed",
                "tools_removed",
                "old_parts_handled",
                "customer_notified",
                "invoice_generated",
                "payment_confirmed",
            )
        }
        workflow.change_work_order_status(db, user, wo, "ready_for_pickup", False)
        workflow.change_work_order_status(db, user, wo, "completed", False)
        history.add_manual(
            db,
            user,
            accord,
            {
                "service_date": date(2026, 4, 18),
                "mileage": 55020,
                "summary": "Oil and filter change, tire rotation",
                "performed_by": "Previous shop",
                "notes": "From the customer's paper records.",
            },
        )

        # --- An open job waiting on approval
        maria = _customer(
            db,
            "Maria",
            "Garcia",
            "(555) 010-0102",
            "maria.garcia@example.com",
            preferred_contact="phone",
        )
        rav = _vehicle(
            db,
            maria,
            year=2015,
            make="Toyota",
            model="RAV4",
            mileage=118400,
            license_plate="DEM0102",
            license_state="NY",
            color="Blue",
        )
        wo2 = workflow.create_work_order(
            db,
            user,
            WorkOrderCreate(
                customer_id=maria.id,
                vehicle_id=rav.id,
                mileage_in=118410,
                concern="Check engine light on; rough idle when cold.",
                items=[
                    LineItemIn(
                        kind="labor",
                        description="Diagnose check engine light",
                        quantity=Decimal("1.0"),
                    )
                ],
            ),
        )
        workflow.change_work_order_status(db, user, wo2, "waiting_approval", False)
        est2 = workflow.create_estimate(
            db,
            user,
            EstimateCreate(
                customer_id=maria.id,
                vehicle_id=rav.id,
                work_order_id=wo2.id,
                items=[
                    LineItemIn(
                        kind="labor",
                        description="Diagnose check engine light (P0301)",
                        quantity=Decimal("1.0"),
                    ),
                    LineItemIn(
                        kind="labor",
                        description="Replace ignition coil, cylinder 1",
                        quantity=Decimal("0.5"),
                    ),
                    LineItemIn(
                        kind="part",
                        description="Ignition coil",
                        part_number="DEMO-COIL-3",
                        unit_cost_cents=6200,
                    ),
                ],
            ),
        )
        workflow.mark_estimate_sent(db, user, est2)

        # --- An unpaid invoice from last week
        dev = _customer(db, "Devon", "Brooks", "(555) 010-0103", None)
        f150 = _vehicle(
            db,
            dev,
            year=2012,
            make="Ford",
            model="F-150",
            mileage=152000,
            license_plate="DEM0103",
            license_state="NY",
        )
        wo3 = workflow.create_work_order(
            db,
            user,
            WorkOrderCreate(
                customer_id=dev.id,
                vehicle_id=f150.id,
                mileage_in=152010,
                concern="Oil change and tire rotation.",
                items=[
                    LineItemIn(
                        kind="part",
                        description="Full synthetic oil and filter",
                        unit_price_cents=5495,
                    ),
                    LineItemIn(kind="labor", description="Tire rotation", quantity=Decimal("0.5")),
                ],
            ),
        )
        workflow.change_work_order_status(db, user, wo3, "ready_for_pickup", False)
        inv3 = workflow.invoice_from_work_order(db, user, wo3, InvoiceFromWorkOrder())
        inv3.issue_date = inv3.issue_date - timedelta(days=8)
        inv3.due_date = inv3.issue_date + timedelta(days=7)
        workflow.mark_invoice_sent(db, user, inv3)

        # --- A new online appointment request
        db.add(
            Appointment(
                status="requested",
                source="online",
                requested_service="Brake Service",
                concern="Squealing noise from the rear when stopping.",
                preferred_date=(datetime.now(UTC) + timedelta(days=2)).date(),
                preferred_time="Morning",
                contact_name="Alex Kim",
                contact_phone="(555) 010-0104",
                contact_email="alex.kim@example.com",
                vehicle_description="2019 Subaru Outback",
                reported_mileage=54000,
            )
        )
        # --- A confirmed appointment tomorrow for an existing customer
        tomorrow_9 = (datetime.now(UTC) + timedelta(days=1)).replace(
            hour=13, minute=0, second=0, microsecond=0
        )
        db.add(
            Appointment(
                status="confirmed",
                customer_id=maria.id,
                vehicle_id=rav.id,
                starts_at=tomorrow_9,
                ends_at=tomorrow_9 + timedelta(hours=2),
                requested_service="Diagnostics",
                source="admin",
            )
        )
        db.commit()
        return {
            "ok": True,
            "login": DEMO_EMAIL,
            "password": DEMO_PASSWORD,
            "demo_invoice": inv.number,
            "demo_total_cents": inv.total_cents,
        }
