from __future__ import annotations

from typing import Literal, cast


CustomerAccessRole = Literal["admin", "manager", "team", "agent"]

MAYAKO_CLIENT_NAME = "Mayako"
MAYAKO_PRODUCT_PRIVILEGE = "0780"
MAYAKO_PART_CUSTOMER_ID = "CU638"
MAYAKO_SHIPMENT_COMPANY_ID = "0E254109-8698-4F5D-BE70-ABFD2B929CE9"

CUSTOMER_ACCESS_ROLES: tuple[CustomerAccessRole, ...] = (
    "admin",
    "manager",
    "team",
    "agent",
)


def normalize_customer_access_role(
    value: object,
    *,
    can_view_price: bool = False,
    is_admin: bool = False,
) -> CustomerAccessRole:
    normalized = str(value or "").strip().casefold()
    if normalized in CUSTOMER_ACCESS_ROLES:
        return cast(CustomerAccessRole, normalized)
    if is_admin:
        return "admin"
    if can_view_price:
        return "manager"
    return "team"


def customer_access_permissions(role: object) -> dict[str, bool]:
    normalized = normalize_customer_access_role(role)
    return {
        "canViewPrice": normalized in {"admin", "manager"},
        "canViewOrders": normalized in {"admin", "manager", "team"},
        "canViewDetails": normalized in {"admin", "manager", "team"},
        "isAdmin": normalized == "admin",
    }
