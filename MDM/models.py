from dataclasses import dataclass
from typing import Optional

@dataclass
class CustomerRecord:
    record_id: str
    source_system: str
    first_name: str
    last_name: str
    email: str
    phone: str
    date_of_birth: Optional[str]
    gender: Optional[str]
    address_line1: str
    city: str
    state: str
    postal_code: str
    country: str
    loyalty_tier: Optional[str]
    customer_since: Optional[str]
    last_purchase_date: str
    total_lifetime_value: Optional[float]
    is_active: bool
    created_at: str
    updated_at: str
    cluster_id: str
