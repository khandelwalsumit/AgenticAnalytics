"""Generate realistic dummy call data for AgenticAnalytics POC.

Columns align exactly with config.py:
  - LLM_ANALYSIS_COLUMNS: digital_friction (2-line analysis), key_solution (2-line solution)
  - GROUP_BY_COLUMNS: call_reason, broad_theme_l3, granular_theme_l5
  - Products: ATT, Costco, AAdvantage, Cash, Rewards

call_reason values map 1:1 to the 6 domain skills:
  payment_transfer, transaction_statement, authentication,
  profile_settings, fraud_dispute, rewards

Run: python generate_dummy_csv.py
"""

import csv
import random

random.seed(42)

PRODUCTS = ["ATT", "Costco", "AAdvantage", "Cash", "Rewards"]

# ---- call_reason hierarchy: matches domain skill names exactly ----
# Each call_reason maps to its L2, L3, L4, L5 hierarchy + friction patterns

CALL_REASON_DATA = {
    "Payments & Transfers": {
        "l2": [
            "Payment Failed", "Auto Pay Issue", "Balance Transfer",
            "Bill Pay Problem", "Refund Delay",
        ],
        "l3": ["Payment Processing", "Fund Transfer", "Billing"],
        "l4": [
            "ACH Processing", "Wire Transfer", "P2P Payment",
            "Scheduled Payment", "Payment Reversal",
        ],
        "l5": [
            "Payment Gateway Timeout", "Duplicate Payment Deduction",
            "Auto Pay Enrollment Failure", "Balance Transfer Promo Mismatch",
            "Bill Pay Scheduling Error", "Refund Not Reflected",
        ],
        "problems": [
            "Customer's payment was declined even though they have sufficient balance. The app shows 'Transaction Failed' with no error code.",
            "Auto Pay was set up but the payment didn't go through this month. Customer was charged a late fee as a result.",
            "Balance transfer promotional APR is showing 15.99% instead of the 0% advertised in the mailer customer received.",
            "Customer made a P2P transfer 3 days ago but the recipient hasn't received the funds yet. Status shows 'Processing'.",
            "Bill pay scheduled for the 15th was processed on the 13th causing an overdraft in the linked checking account.",
            "Customer's refund from a disputed transaction was approved 2 weeks ago but still not reflected in the account balance.",
            "Payment to credit card failed with 'unable to verify account' error when using the mobile app to pay from external bank.",
            "Wire transfer initiated from the app was stuck in pending for 5 business days. Branch says it was never submitted.",
        ],
        "digital_friction": [
            "App payment flow requires 7 taps to complete a simple payment. Error messages are generic ('Something went wrong') with no actionable guidance.\nNo retry mechanism exists -- customer must restart the entire payment flow after a failure.",
            "Auto Pay enrollment screen doesn't confirm the payment date clearly. The toggle switch for auto pay on/off is buried under 'More Options'.\nCustomer cannot see scheduled auto pay details without navigating to a separate 'Scheduled Payments' section.",
            "Balance transfer flow on mobile doesn't display the promotional APR until after the transfer is submitted. No ability to cancel a pending transfer.\nThe promo rate terms link opens a PDF that doesn't render properly on mobile devices.",
            "P2P transfer status page only shows 'Processing' with no estimated completion time or tracking details.\nNo push notification when transfer completes or fails -- customer has to manually check status repeatedly.",
            "Bill pay date picker doesn't clearly indicate processing time (1-3 business days). Calendar UI cuts off on smaller screens.\nNo confirmation screen showing the exact date funds will be withdrawn from the linked account.",
            "Refund tracking is hidden under Statement > Transactions > Pending. No dedicated refund status page.\nThe app doesn't distinguish between merchant refunds and dispute credits making it confusing for customers.",
            "External bank linking flow fails silently on certain bank integrations. The 'Verify Account' step times out after 30 seconds.\nNo option to manually enter routing/account numbers as fallback when instant verification fails.",
            "Wire transfer form on app doesn't save beneficiary details. Customer must re-enter all fields for repeat transfers.\nThe intermediary bank field is required but no guidance is provided on when it's needed or how to find it.",
        ],
        "key_solution": [
            "Simplify payment flow to 3 taps maximum. Replace generic errors with specific codes and retry button.\nAdd payment status push notifications and in-app payment history with clear success/fail indicators.",
            "Redesign Auto Pay setup with clear date confirmation and summary screen. Surface auto pay status on account dashboard.\nSend payment confirmation notifications 2 days before and immediately after auto pay execution.",
            "Show promotional APR upfront in the transfer flow before submission. Allow transfer cancellation within 24 hours.\nRender promo terms as native HTML instead of PDF for mobile readability.",
            "Add estimated completion time and step-by-step tracking to P2P transfers. Enable push notifications for status changes.\nProvide recipient confirmation when funds are deposited with transaction reference number.",
            "Show fund withdrawal date clearly during bill pay setup. Add processing time tooltip. Fix calendar UI for small screens.\nImplement confirmation screen with exact debit date and option to edit before final submission.",
            "Create dedicated refund tracking dashboard. Separate merchant refunds from dispute credits with clear labels.\nAdd push notification when refund posts and estimated timeline during pending status.",
            "Implement fallback manual account entry when instant verification fails. Extend timeout to 60 seconds.\nCache linked bank details securely so customers don't need to re-verify for subsequent payments.",
            "Save beneficiary details for wire transfers. Add smart form that shows/hides intermediary bank field based on destination.\nPre-populate fields from previous transfers with one-tap repeat transfer option.",
        ],
    },
    "Transactions & Statements": {
        "l2": [
            "Missing Transaction", "Statement Error", "Duplicate Charge",
            "Unrecognized Charge", "Statement Download",
        ],
        "l3": ["Transaction History", "Statement Access", "Charge Inquiry"],
        "l4": [
            "Real-time Posting", "PDF Statement", "Transaction Search",
            "Pending Transaction", "Statement Delivery",
        ],
        "l5": [
            "Transaction Not Showing", "Statement PDF Download Failure",
            "Duplicate Charge Display", "Merchant Name Mismatch",
            "Statement Cycle Confusion", "Transaction Search Not Working",
        ],
        "problems": [
            "Customer made a purchase yesterday but it's not showing in the transaction history on the app. The merchant confirmed the charge went through.",
            "Statement PDF won't download on the mobile app. Shows loading spinner for 30 seconds then displays 'Unable to generate statement'.",
            "Same restaurant charge appears twice in the transaction list but the customer says they only visited once. Amounts are identical.",
            "Customer doesn't recognize a charge labeled 'DBI*MGMT FEE' on their statement. Wants to know what it is before disputing.",
            "Customer thinks they were double-billed because their closing date changed and charges appear on two consecutive statements.",
            "Transaction search only works with exact merchant names. Searching 'amazon' doesn't find 'AMZN MKTP US' or 'Amazon.com'.",
            "Pending transactions show different amounts than final posted amounts. Customer was charged $45.67 but pending showed $40.00.",
            "Customer cannot view transactions older than 90 days on the app. Needs records from 6 months ago for tax purposes.",
        ],
        "digital_friction": [
            "Transaction history has a 24-48 hour delay for new purchases to appear. No 'pending' indicator for recently authorized transactions.\nReal-time balance doesn't match transaction total due to holds and pending charges not being displayed.",
            "Statement PDF generation times out on mobile. The download button doesn't provide progress feedback or file size indication.\nPast statements beyond 12 months are not accessible digitally -- customer must call to request archived statements.",
            "Transaction list doesn't merge duplicate authorization/settlement entries. Same charge appears as both 'pending' and 'posted'.\nNo visual indicator to distinguish between pending authorizations and final posted charges.",
            "Merchant names in transaction list use payment processor codes instead of recognizable business names (e.g., 'SQ *COFFEE' instead of 'Blue Bottle Coffee').\nNo merchant category or location info displayed to help customers identify charges.",
            "Statement cycle dates are not prominently displayed. The app doesn't explain that changing due date shifts the billing cycle.\nNo way to view which transactions fall into which statement period without downloading individual PDFs.",
            "Transaction search uses exact string matching only. No fuzzy search, no merchant category filters, no amount range filters.\nSearch results don't highlight matching terms or sort by relevance -- just reverse chronological order.",
            "Pending transaction amounts are the authorization hold amount not the final charge. No explanation that final amount may differ.\nApp doesn't update pending amounts when merchant sends a different settlement amount.",
            "App only displays 90 days of transactions by default. 'View More' link is hard to find and loads slowly with no pagination.\nExporting transactions to CSV/PDF for older periods requires multiple separate downloads by month.",
        ],
        "key_solution": [
            "Implement real-time transaction feed with pending indicators and authorization timestamps.\nShow 'pending' charges immediately and auto-merge with posted charges when settled.",
            "Optimize PDF generation for mobile with progress bar. Cache recently generated statements for instant re-download.\nProvide 7-year digital statement archive accessible from the app without calling.",
            "Auto-merge duplicate pending/posted entries for the same authorization. Add clear 'Pending' vs 'Posted' badges.\nOnly show final posted amount once settlement completes and remove the pending entry.",
            "Implement merchant name enrichment using merchant category codes and location data. Show business names instead of processor codes.\nAdd merchant logo, category icon, and map location for in-store transactions.",
            "Display statement period dates on the transaction list header. Add visual dividers between billing cycles.\nShow a 'This Statement' vs 'Next Statement' toggle for easy period navigation.",
            "Add fuzzy search with merchant category filters and amount range sliders. Support partial name matching.\nHighlight search matches in results and add relevance-based sorting alongside chronological.",
            "Show both authorization and expected final amounts for pending transactions. Add tooltip explaining holds.\nPush notification when pending amount differs from final posted amount by more than 10%.",
            "Display full transaction history with infinite scroll and fast pagination. Enable one-click CSV export for any date range.\nAdd tax-year quick filter for easy end-of-year transaction export.",
        ],
    },
    "Authentication & Access": {
        "l2": [
            "Password Reset", "OTP Not Received", "Account Locked",
            "Biometric Login Failure", "Device Registration",
        ],
        "l3": ["Sign On", "Account Security", "Device Management"],
        "l4": [
            "MFA/OTP", "Password Management", "Session Handling",
            "Biometric Auth", "Trusted Device",
        ],
        "l5": [
            "SMS OTP Delay", "Password Complexity Rejection",
            "Biometric Fallback Missing", "Session Timeout Too Short",
            "Device Registration Loop", "Account Lockout After 3 Attempts",
        ],
        "problems": [
            "Customer cannot log in because OTP is not being delivered to their phone. They've waited 15 minutes and tried 3 times.",
            "Password reset link in email expired before customer could use it. The link is only valid for 15 minutes.",
            "Customer's account got locked after entering wrong password 3 times. Now the unlock process requires calling the number on the back of the card.",
            "Face ID stopped working on the app after the latest iOS update. No option to fall back to fingerprint or PIN in the app.",
            "Customer got a new phone and now has to re-register the device. The registration process asks for a code sent to old phone number.",
            "Customer keeps getting logged out every 5 minutes while trying to complete an application. Has to re-authenticate each time.",
            "Customer set up a new password meeting all requirements but gets 'Password not accepted' error with no explanation of what's wrong.",
            "MFA setup wizard crashes on Android when trying to set up the authenticator app. Falls back to SMS which customer doesn't want.",
        ],
        "digital_friction": [
            "OTP delivery via SMS has 30-60 second delays during peak hours. No fallback to email or authenticator app OTP.\nThe 'Resend OTP' button has a 60-second cooldown with no visible timer showing remaining wait time.",
            "Password reset email link expires in 15 minutes which is too short. The reset page doesn't indicate time remaining.\nPassword requirements are only shown after a failed attempt, not proactively during creation.",
            "Account lockout after 3 failed attempts with no progressive delay option. Unlock requires a phone call during business hours only.\nNo self-service unlock via email verification or security questions as alternative.",
            "Biometric authentication has no graceful fallback chain. If Face ID fails there's no option for fingerprint then PIN.\nApp requires full password re-entry when biometric fails instead of offering simpler alternatives.",
            "Device registration sends verification code to the phone number on file which may be outdated. No email verification option.\nNew device registration invalidates all other trusted devices forcing re-authentication everywhere.",
            "Session timeout is set to 5 minutes with no activity detection. Background app refresh counts as inactivity.\nNo 'Keep me logged in' or 'Remember this device' option for trusted personal devices.",
            "Password requirements are complex (12+ chars, upper, lower, number, special) but error messages don't specify which rule failed.\nPrevious 12 passwords are blocked but the system doesn't tell you it's a reuse -- just says 'not accepted'.",
            "MFA authenticator app setup generates a QR code that's too small to scan on some Android devices. Manual key entry is hidden.\nNo ability to set preferred MFA method -- defaults to SMS even after setting up authenticator app.",
        ],
        "key_solution": [
            "Add email and authenticator app as OTP fallback channels. Show countdown timer on resend button.\nImplement push notification OTP that doesn't depend on SMS delivery.",
            "Extend password reset link validity to 60 minutes. Show expiry countdown on the reset page.\nDisplay password requirements upfront with real-time validation checkmarks during creation.",
            "Implement progressive lockout (increasing delays) instead of hard lock after 3 attempts.\nAdd self-service unlock via email verification link or security question answers.",
            "Build biometric fallback chain: Face ID -> Fingerprint -> Device PIN -> Password. Implement graceful degradation.\nAllow customers to configure preferred biometric method in app settings.",
            "Allow email-based device verification as alternative to SMS. Don't invalidate other devices on new registration.\nProvide 'Transfer Trust' flow that migrates device trust from old phone via QR code scan.",
            "Extend session timeout to 15 minutes with active idle detection. Exclude background refresh from inactivity.\nAdd 'Remember Device' option for 30/60/90 days on personal devices.",
            "Show real-time password rule validation with green checkmarks. Explicitly name which rule failed on rejection.\nClearly state 'This password was used previously' instead of generic 'not accepted' message.",
            "Generate larger QR codes with zoom option. Show manual setup key prominently alongside QR.\nLet users set preferred MFA method in security settings and remember the preference.",
        ],
    },
    "Profile & Settings": {
        "l2": [
            "Address Change", "Phone Number Update", "Email Update",
            "Notification Preferences", "Account Closure",
        ],
        "l3": ["Personal Info Update", "Account Preferences", "Account Lifecycle"],
        "l4": [
            "Contact Information", "Document Verification", "Privacy Settings",
            "Communication Preferences", "Account Closure Process",
        ],
        "l5": [
            "Address Validation Failure", "Phone Update Requires Branch Visit",
            "Email Change Delayed Verification", "Notification Toggle Missing",
            "Account Closure Multi-Step Burden", "Name Change Document Upload Error",
        ],
        "problems": [
            "Customer moved to a new state but the address update on the app keeps saying 'Address could not be verified' for their new apartment.",
            "Customer got a new phone number but can't update it on the app. The app says 'Contact us to update phone number'.",
            "Customer changed their email address but verification email was sent to the OLD email address which they no longer have access to.",
            "Customer wants to turn off promotional email notifications but the app only has an on/off toggle for ALL notifications including alerts.",
            "Customer wants to close their account but the app says 'Visit a branch or call us'. There's no online closure option.",
            "Customer had a legal name change and uploaded their court order document but the upload keeps failing with 'File too large' error.",
            "Customer's mailing address shows their old address on statements even though they updated it in the app 2 months ago.",
            "Customer wants to add their spouse as an authorized user but the form requires a SSN and the spouse is reluctant to enter it online.",
        ],
        "digital_friction": [
            "Address validation uses a strict USPS database that doesn't recognize new constructions or apartment complexes less than 6 months old.\nApp doesn't offer manual address override or 'use this address anyway' option when validation fails.",
            "Phone number change is blocked on digital channels for security. No self-service flow exists even with identity verification.\nThe app directs to a call center that has 45+ minute average hold times for phone updates.",
            "Email change verification is sent to the OLD email as a 'security measure' but customers changing email often lost access to the old one.\nNo alternative verification path using SMS or identity documents for email changes.",
            "Notification settings are binary all-or-nothing. No granular control over transaction alerts vs marketing vs security notifications.\nPush notification preferences don't sync with email notification preferences -- managed separately.",
            "Account closure requires calling or visiting a branch. No digital self-service option even for zero-balance accounts.\nThe closure process takes 30+ days with no status tracking and requires 3 separate confirmation steps.",
            "Document upload has a 2MB file size limit which rejects most phone camera photos. No image compression built in.\nSupported format list (PDF, JPG) is only shown after upload failure. HEIC from iPhone is not supported.",
            "Address update in profile doesn't propagate to statement delivery address automatically. These are managed as separate fields.\nNo confirmation that address change was successful -- customer only discovers it wasn't updated at next statement.",
            "Authorized user form requires SSN entry on a single page with all other info. No explanation of why SSN is needed or how it's protected.\nNo option for the authorized user to enter their own SSN via a secure separate link.",
        ],
        "key_solution": [
            "Add 'Use this address anyway' override with attestation checkbox when USPS validation fails.\nUpdate address database more frequently and support new construction addresses with unit number variations.",
            "Build secure self-service phone update flow with multi-factor identity verification (ID upload + security questions).\nReduce call center hold times for phone updates by adding callback scheduling option.",
            "Send email change verification to the NEW email with additional SMS verification to the phone on file.\nOffer identity document upload as alternative verification when customer can't access old email.",
            "Implement granular notification preferences: Security Alerts, Transaction Alerts, Account Updates, Marketing.\nSync notification preferences across push, email, and SMS channels from a single settings page.",
            "Enable digital account closure for zero-balance accounts with no outstanding obligations.\nProvide closure status tracking and reduce processing time to 5 business days with clear timeline.",
            "Increase upload limit to 10MB with built-in image compression. Support HEIC, PNG, PDF, JPG formats.\nShow supported formats and size limits before upload attempt with built-in camera capture option.",
            "Auto-propagate address changes to all linked services (statements, cards, correspondence).\nShow confirmation banner after address update with list of all affected services and estimated update timeline.",
            "Allow authorized user to complete their sensitive info via a separate secure tokenized link.\nExplain SSN requirement with privacy policy link and show security badge on the form.",
        ],
    },
    "Fraud & Disputes": {
        "l2": [
            "Unauthorized Transaction", "Dispute Status", "Card Replacement",
            "Fraud Alert", "Provisional Credit",
        ],
        "l3": ["Dispute Resolution", "Fraud Prevention", "Card Security"],
        "l4": [
            "Chargeback Process", "Fraud Investigation", "Card Controls",
            "Suspicious Activity", "Credit Provisioning",
        ],
        "l5": [
            "Dispute Form Too Complex", "Fraud Alert False Positive",
            "Provisional Credit Delay", "Card Lock Self-Service Missing",
            "Investigation Status Opaque", "Chargeback Timeline Unclear",
        ],
        "problems": [
            "Customer sees a $500 charge they didn't make. They want to dispute it but the dispute form asks for merchant contact info they don't have.",
            "Customer got a fraud alert text about a $12 coffee purchase they actually made. Now their card is blocked and they can't unblock it from the app.",
            "Customer filed a dispute 3 weeks ago and has no idea where it stands. The app just says 'Under Review' with no timeline.",
            "Customer wants to lock their card temporarily while they look for it at home. The app only offers 'Report Lost/Stolen' which permanently cancels the card.",
            "Customer's provisional credit from a dispute was reversed without explanation. They received a letter but it referenced a case number they can't find online.",
            "Customer filed a chargeback for a canceled subscription but the merchant provided proof of a renewal. Customer can't upload their cancellation evidence.",
            "Customer's card was compromised and they need a replacement but expedited shipping costs $25. Standard shipping takes 7-10 business days.",
            "Customer got a fraud alert for an online purchase and clicked 'Not Me' but the transaction still went through on their account.",
        ],
        "digital_friction": [
            "Dispute initiation form is 3 pages long requiring merchant details the customer doesn't have. No 'I don't know' option for optional fields.\nCan't dispute directly from the transaction in the app -- must navigate to a separate 'Disputes' section and re-enter transaction details.",
            "Fraud alerts via SMS have a 'Yes/No' response but responding 'Yes it's me' doesn't auto-unblock the card. Must call to remove the hold.\nFalse positive rate on fraud detection is high for small recurring charges and online subscriptions.",
            "Dispute status page shows only 'Under Review' with no timeline, no case manager contact, and no progress indicators.\nCustomer can't see what documents have been submitted or what's still needed without calling the dispute team.",
            "App only offers permanent card cancellation -- no temporary lock/unlock toggle. Customer must call to place a temporary hold.\nThe 'Report Lost/Stolen' flow immediately orders a new card and deactivates the current one with no confirmation step.",
            "Provisional credit reversal notification is sent via postal mail only. No in-app notification or email explaining why credit was reversed.\nCase reference numbers in letters don't match the format shown in the app, creating confusion.",
            "Customer cannot upload additional evidence for an open dispute through the app. Must fax or mail supporting documents.\nThe dispute portal doesn't show what evidence the merchant submitted, only the dispute outcome.",
            "Replacement card ordering doesn't show estimated delivery date. Expedited shipping option is expensive and not clearly presented.\nDigital card number for immediate online use is not offered during the replacement process.",
            "Fraud alert response 'Not Me' doesn't automatically create a dispute case. Customer must separately call to initiate the dispute.\nReal-time fraud blocking has a 30-second processing delay during which the fraudulent transaction can complete.",
        ],
        "key_solution": [
            "Enable one-tap dispute from the transaction detail screen. Pre-fill all transaction details and make merchant info optional.\nSimplify form to single page with smart defaults and 'I don't know' option for merchant fields.",
            "Auto-unblock card immediately when customer confirms 'Yes it's me' on fraud alert. Tune fraud models to reduce false positives.\nAllow customers to whitelist recurring merchants and subscription services to prevent false positives.",
            "Show dispute timeline with stages (Filed > Under Review > Merchant Response > Resolution) and estimated days per stage.\nProvide case manager name and secure messaging for dispute communication within the app.",
            "Add temporary card lock/unlock toggle on the card management screen. Separate from 'Report Lost/Stolen' flow.\nAdd confirmation step before permanent card cancellation with explanation of the difference.",
            "Send provisional credit reversal notifications via push notification and email with clear explanation and next steps.\nUse consistent case reference format across all channels (app, email, mail).",
            "Enable document upload directly within the dispute detail screen. Show merchant evidence and allow customer rebuttal.\nAccept photos, PDFs, and screenshots as dispute evidence with in-app camera capture.",
            "Show estimated delivery date for replacement cards. Offer instant digital card number for immediate online use.\nProvide free expedited shipping for fraud-related replacements.",
            "Auto-create dispute case when customer responds 'Not Me' to fraud alert. Block transaction in real-time before completion.\nReduce fraud alert processing to under 5 seconds to prevent fraudulent transactions from completing.",
        ],
    },
    "Rewards & Loyalty": {
        "l2": [
            "Points Balance", "Redemption Issue", "Earn Rate Question",
            "Promotional Offer", "Points Expiry",
        ],
        "l3": ["Rewards Redemption", "Points Earning", "Loyalty Tier"],
        "l4": [
            "Cashback Posting", "Travel Redemption", "Category Bonus",
            "Anniversary Bonus", "Points Transfer",
        ],
        "l5": [
            "Points Not Credited", "Redemption Minimum Too High",
            "Category Bonus Not Applied", "Promotional Points Missing",
            "Partner Transfer Delay", "Tier Downgrade Surprise",
        ],
        "problems": [
            "Customer made $300 in grocery purchases last month but points for the 3x category bonus weren't credited. Regular 1x points were applied.",
            "Customer wants to redeem points for a flight but the minimum redemption is 25,000 points and they have 24,500. No option for partial points + cash.",
            "Customer signed up for a 60,000 point welcome bonus offer but only received 40,000 after meeting the spend requirement.",
            "Customer's cashback was posted as points instead of statement credit. They can't find where to change their redemption preference.",
            "Customer transferred points to airline partner 5 days ago but they still don't appear in the airline frequent flyer account.",
            "Customer was downgraded from Platinum to Gold tier without any warning or notification. Lost access to airport lounge benefit.",
            "Customer's anniversary bonus points from last year haven't been credited. Account anniversary was 3 months ago.",
            "Customer used their card at a gas station but didn't get the 5x gas category bonus. The merchant coded as 'convenience store'.",
        ],
        "digital_friction": [
            "Category bonus tracking in the app doesn't show which merchants qualify for enhanced earning rates. No real-time earn rate preview.\nBonus category spend progress is only visible in the rewards section, not on the transaction detail screen.",
            "Redemption flow requires minimum 25,000 points with no points+cash option. Available redemption options are buried in a sub-menu.\nTravel redemption search is a separate portal that doesn't integrate with the main app experience.",
            "Welcome bonus tracker doesn't show qualifying spend progress in real-time. Updated only once per statement cycle.\nBonus terms and qualifying purchase exclusions are in fine print that's hard to read on mobile.",
            "Cashback redemption preference setting is hidden under Rewards > Settings > Preferences > Redemption Method (4 levels deep).\nNo way to set default redemption for all future cashback -- must choose each time.",
            "Points transfer status shows 'Processing' with no estimated completion time. No confirmation from the partner program.\nTransfer is irreversible but the confirmation screen doesn't clearly warn about this.",
            "Tier status and benefits are displayed on a page that hasn't been updated for mobile. Tier progress bar doesn't show spend needed for next tier.\nNo proactive notification before tier downgrade -- customer only discovers it when trying to use a benefit.",
            "Anniversary bonus posting timeline is not documented anywhere in the app. No tracker showing when bonus will be credited.\nAccount anniversary date is not displayed in the app -- customer can't verify when it is.",
            "Merchant category code (MCC) used for bonus determination is not visible to the customer. No way to report incorrect merchant coding.\nCategory bonus exclusions (gas stations inside grocery stores, warehouse clubs) are not clearly explained.",
        ],
        "key_solution": [
            "Show merchant earning rate preview on each transaction. Display bonus category progress on the main rewards dashboard.\nAdd real-time earn rate indicator on transaction detail screens with qualifying merchant badge.",
            "Implement points+cash hybrid redemption for any amount. Surface all redemption options on one clean screen.\nIntegrate travel search directly into the main app with points value calculator for each option.",
            "Add real-time welcome bonus spend tracker on the rewards dashboard with progress bar and days remaining.\nList qualifying and non-qualifying purchase categories clearly with specific merchant examples.",
            "Move redemption preference to top-level rewards settings (1 tap from dashboard). Add 'Set as default' option.\nAllow customers to set auto-redemption rules (e.g., auto statement credit every 5,000 points).",
            "Show estimated partner transfer completion time and partner program confirmation. Add transfer tracker.\nDisplay clear irreversibility warning with partner program terms before confirming transfer.",
            "Show tier progress bar with exact spend needed for retention/upgrade. Send 90-day and 30-day tier expiry warnings.\nList all tier benefits clearly with real-time access status (active/at risk).",
            "Display anniversary bonus posting timeline and account anniversary date prominently in rewards section.\nSend push notification when anniversary bonus is credited or if there's a delay.",
            "Show the MCC code and category assigned to each transaction. Allow customers to flag incorrect merchant categorization.\nClearly list category bonus exclusions with examples on the rewards earning rules page.",
        ],
    },
}

# Friction driver categories
FRICTION_CATEGORIES = [
    "UI/UX Flaw", "System Bug/Outage", "Process Gap",
    "Policy Restriction", "Third-party Dependency", "Information Gap",
]

# Policy friction -- weighted toward No for most, Yes for Profile & Fraud
POLICY_FRICTION_WEIGHTS = {
    "Payments & Transfers": [0.7, 0.3],          # No, Yes
    "Transactions & Statements": [0.8, 0.2],
    "Authentication & Access": [0.6, 0.4],
    "Profile & Settings": [0.4, 0.6],
    "Fraud & Disputes": [0.3, 0.7],
    "Rewards & Loyalty": [0.6, 0.4],
}


def generate_rows(n: int = 500) -> list[dict]:
    """Generate n rows of realistic call data."""
    rows = []
    call_reasons = list(CALL_REASON_DATA.keys())

    for _ in range(n):
        product = random.choice(PRODUCTS)
        reason = random.choice(call_reasons)
        data = CALL_REASON_DATA[reason]

        idx = random.randint(0, len(data["problems"]) - 1)

        policy_weights = POLICY_FRICTION_WEIGHTS[reason]
        policy = random.choices(["No", "Yes"], weights=policy_weights, k=1)[0]

        row = {
            "product": product,
            "call_reason": reason,
            "call_reason_l2": random.choice(data["l2"]),
            "broad_theme_l3": random.choice(data["l3"]),
            "intermediate_theme_l4": random.choice(data["l4"]),
            "granular_theme_l5": random.choice(data["l5"]),
            "exact_problem_statement": data["problems"][idx],
            "digital_friction": data["digital_friction"][idx],
            "key_solution": data["key_solution"][idx],
            "policy_friction": policy,
            "friction_driver_category": random.choice(FRICTION_CATEGORIES),
        }
        rows.append(row)

    return rows


if __name__ == "__main__":
    rows = generate_rows(500)

    columns = [
        "product", "call_reason", "call_reason_l2",
        "broad_theme_l3", "intermediate_theme_l4", "granular_theme_l5",
        "exact_problem_statement", "digital_friction", "key_solution",
        "policy_friction", "friction_driver_category",
    ]

    with open("dummy_data.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    # Print stats
    import pandas as pd
    df = pd.read_csv("dummy_data.csv")
    print(f"Generated dummy_data.csv: {len(df)} rows, {len(df.columns)} columns")
    print(f"\nColumns: {list(df.columns)}")
    print(f"\nProducts: {sorted(df['product'].unique())}")
    print(f"Call Reasons: {sorted(df['call_reason'].unique())}")
    print(f"\nProduct distribution:")
    print(df["product"].value_counts().to_string())
    print(f"\nCall Reason distribution:")
    print(df["call_reason"].value_counts().to_string())
    print(f"\ndigital_friction sample (first row):")
    print(df["digital_friction"].iloc[0][:200])
    print(f"\nkey_solution sample (first row):")
    print(df["key_solution"].iloc[0][:200])
