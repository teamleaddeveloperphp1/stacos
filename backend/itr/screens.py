SCREENS = [
    {"id": "personal_info", "number": 1, "label": "Personal Information"},
    {"id": "gross_total_income", "number": 2, "label": "Gross Total Income"},
    {"id": "total_deductions", "number": 3, "label": "Total Deductions"},
    {"id": "tax_paid", "number": 4, "label": "Tax Paid"},
    {"id": "tax_liability", "number": 5, "label": "Tax Liability"},
    {"id": "tax_summary", "number": 6, "label": "Tax Summary"},
    {"id": "validation", "number": 7, "label": "Validation & JSON"},
]

STATUS_LABELS = {
    "not_started": "Not started",
    "in_progress": "In progress",
    "confirmed": "Confirmed",
    "has_errors": "Has errors",
}


def build_menu_items(return_id, screen_status=None):
    from django.urls import reverse

    screen_status = screen_status or {}
    items = []
    for screen in SCREENS:
        status = screen_status.get(screen["id"].upper(), "NOT_STARTED").lower()
        items.append({
            "number": screen["number"],
            "label": screen["label"],
            "url": reverse(f"itr:{screen['id']}", args=[return_id]),
            "status": status,
            "status_label": STATUS_LABELS.get(status, STATUS_LABELS["not_started"]),
        })
    return items
