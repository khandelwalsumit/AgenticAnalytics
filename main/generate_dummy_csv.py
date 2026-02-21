import csv
import random

columns = [
    "exact_problem_statement",
    "digital_friction",
    "policy_friction",
    "solution_by_ui",
    "solution_by_ops",
    "solution_by_education",
    "solution_by_technology",
    "call_reason",
    "call_reason_l2",
    "broad_theme_l3",
    "intermediate_theme_l4",
    "granular_theme_l5",
    "friction_driver_category"
]

dummy_phrases = {
    "exact_problem_statement": [
        "Customer is unable to reset their password via the mobile app.",
        "User mentions the website is too slow when loading reports.",
        "Customer confused about the new billing policy on their last invoice.",
        "App crashes immediately upon opening on Android 13.",
        "User cannot find the 'Export Data' option in the new interface.",
        "Payment got deducted twice for the same transaction.",
        "Customer didn't receive the OTP for login authentication.",
        "User wants to cancel subscription but cannot find the button."
    ],
    "digital_friction": ["High", "Medium", "Low", "None"],
    "policy_friction": ["Yes", "No", "N/A"],
    "solution_by_ui": ["Make buttons more prominent", "Simplify navigation menu", "Add tooltips", "Fix responsive layout", "None"],
    "solution_by_ops": ["Escalate to L2 faster", "Provide better script for agents", "Waive fee", "None", "Manual refund processing"],
    "solution_by_education": ["Send interactive guide", "Update FAQ section", "Publish video tutorial", "Email newsletter tip", "None"],
    "solution_by_technology": ["Fix timezone bug", "Optimize database query", "Resolve API timeout", "Fix null pointer exception", "None"],
    "call_reason": ["Login/Access", "Billing/Payments", "Technical Issue", "Feature Inquiry", "Account Management"],
    "call_reason_l2": ["Password Reset", "Double Charge", "App Crash", "Export Data", "Subscription Cancellation"],
    "broad_theme_l3": ["Authentication", "Transaction Processing", "Application Stability", "Workflow/Usability", "Account Lifecycle"],
    "intermediate_theme_l4": ["MFA/OTP", "Invoice Generation", "Mobile App Issues", "Reporting/Analytics", "Subscription Management"],
    "granular_theme_l5": ["SMS Gateway Delay", "Payment Gateway Timeout", "Android Webview Crash", "CSV Export Broken", "Hidden Cancellation Flow"],
    "friction_driver_category": ["UI/UX Flaw", "System Bug/Outage", "User Error/Knowledge Gap", "Restrictive Policy", "Third-party Failure"]
}

data = []
for _ in range(100):
    row = [
        random.choice(dummy_phrases["exact_problem_statement"]),
        random.choice(dummy_phrases["digital_friction"]),
        random.choice(dummy_phrases["policy_friction"]),
        random.choice(dummy_phrases["solution_by_ui"]),
        random.choice(dummy_phrases["solution_by_ops"]),
        random.choice(dummy_phrases["solution_by_education"]),
        random.choice(dummy_phrases["solution_by_technology"]),
        random.choice(dummy_phrases["call_reason"]),
        random.choice(dummy_phrases["call_reason_l2"]),
        random.choice(dummy_phrases["broad_theme_l3"]),
        random.choice(dummy_phrases["intermediate_theme_l4"]),
        random.choice(dummy_phrases["granular_theme_l5"]),
        random.choice(dummy_phrases["friction_driver_category"])
    ]
    data.append(row)

with open('dummy_data.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(columns)
    writer.writerows(data)

print("dummy_data.csv generated successfully.")
