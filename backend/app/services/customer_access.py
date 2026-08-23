from __future__ import annotations

from typing import Literal, cast


CustomerAccessRole = Literal["admin", "manager", "team", "agent"]

# Generic fallback used only when no customer account exists to seed the
# administrator-managed scope. Real deployments seed these values per customer.
DEFAULT_CUSTOMER_CLIENT_NAME = "Customer"
DEFAULT_CUSTOMER_PRODUCT_PRIVILEGE = ""
DEFAULT_CUSTOMER_PART_CUSTOMER_ID = ""
DEFAULT_CUSTOMER_SHIPMENT_COMPANY_ID = ""

# Backward-compatible names retained for older DMS integrations and recovery
# tests. New multi-company code must use the configurable DEFAULT_* values or
# the portal configuration stored by CustomerAccountAdminStore.
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
    is_admin: bool = False,
) -> CustomerAccessRole:
    normalized = str(value or "").strip().casefold()
    if normalized in CUSTOMER_ACCESS_ROLES:
        return cast(CustomerAccessRole, normalized)
    if is_admin:
        return "admin"
    return "team"


def customer_access_permissions(role: object) -> dict[str, bool]:
    normalized = normalize_customer_access_role(role)
    return {
        "canViewOrders": normalized in {"admin", "manager", "team"},
        "canViewDetails": normalized in {"admin", "manager", "team"},
        "isAdmin": normalized == "admin",
    }
