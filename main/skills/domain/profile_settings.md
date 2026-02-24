# Profile & Settings — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: Profile, Settings, Account Update, Personal Information, Address Change, Phone Number, Email Update, Name Change, KYC, Document Verification, Notification Preferences, Account Closure, PIN Change.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim profile/settings issue
- `solution_by_ui` — UI improvements for self-service updates
- `solution_by_ops` — Operational process improvements
- `digital_friction` — Digital barriers during profile changes
- `policy_friction` — Policy barriers requiring agent involvement
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: Phone Number / Email Update Requires Calling
**Signal**: "can't change my number", "update phone", "change email address", "contact info update"
**Root Cause Tree**:
- Contact info change locked behind agent-only process (security justification)
- Verification for contact change requires the OLD contact method (circular: can't verify via old phone if old phone is lost)
- Self-service path exists but is hidden or partially broken
- Update doesn't propagate to all systems (card, banking, alerts still use old number)
**Self-Service Gap**: Can customer update phone/email entirely online? Is there an alternate verification path when old contact is unavailable? Does the change propagate to ALL channels and products?
**Typical Volume**: 25–35% of profile calls — usually the single largest driver
**Call Reduction Lever**: Self-service contact update with alternate verification (security questions + document upload), same-session propagation to all products, "Old number lost?" alternate verification path

### Pattern 2: Address Change Complexity
**Signal**: "change address", "moved", "mailing address", "need proof of address"
**Root Cause Tree**:
- Address change requires documentation (utility bill, lease) — but why, for a mailing address?
- Different requirements for mailing vs legal address
- Multi-step verification slows down a simple change
- P.O. box handling varies by product
**Self-Service Gap**: Can customer change mailing address without documentation? Is the legal vs mailing distinction explained? Is the change reflected immediately for all correspondence?
**Typical Volume**: 10–15% of profile calls
**Call Reduction Lever**: Self-service mailing address change with no documentation (keep legal address change as agent-assisted), USPS address validation in-app, immediate confirmation with next-statement delivery address shown

### Pattern 3: Name Change After Life Event
**Signal**: "changed my name", "married name", "legal name change", "name doesn't match"
**Root Cause Tree**:
- Name change always requires calling + physical documentation
- Process unclear: what documents are accepted? Marriage certificate, court order, etc.
- Timeline for name change to propagate across all products is unknown
- Interim period where old name appears on some products creates confusion
**Self-Service Gap**: Can customer initiate name change online with document upload? Is the document requirement list available before calling? Is the propagation timeline communicated?
**Typical Volume**: 3–5% of profile calls (low volume but HIGH handle time per call)
**Call Reduction Lever**: Online name change initiation with secure document upload, clear document requirements list published in help center, propagation timeline shown at submission ("Cards with new name will be mailed within 7-10 days")

### Pattern 4: Notification Preferences Not Granular Enough
**Signal**: "too many alerts", "can't turn off", "not getting alerts I want", "notification settings"
**Root Cause Tree**:
- Notification settings are all-or-nothing (can't choose: yes to fraud alerts, no to marketing)
- Settings in app don't control all channels (email preferences separate from push preferences)
- Changes to preferences don't take effect immediately
- Some notifications are mandatory but customer doesn't understand why
**Self-Service Gap**: Are notification preferences granular by category AND channel? Are mandatory notifications clearly labeled? Do changes take effect immediately?
**Typical Volume**: 5–10% of profile calls
**Call Reduction Lever**: Granular notification matrix (category × channel), "required" badge on mandatory alerts with explanation, immediate effect on preference changes, notification preview ("This is what you'll receive")

### Pattern 5: PIN Change / Reset
**Signal**: "forgot PIN", "change PIN", "PIN not working", "ATM PIN"
**Root Cause Tree**:
- PIN reset requires calling (no self-service path in app)
- PIN change flow in app exists but fails silently
- Old PIN required to set new PIN (can't change if forgotten)
- Different PINs for different functions (ATM vs phone banking) is confusing
**Self-Service Gap**: Can customer set a new PIN entirely in app with biometric verification? Is there a "forgot PIN" flow that doesn't require calling? Can customer set PIN via card-linked ATM?
**Typical Volume**: 5–8% of profile calls
**Call Reduction Lever**: In-app PIN reset with biometric verification, instant PIN set for new cards via app before first use, "Forgot PIN? Reset via Face ID" flow

### Pattern 6: Account Closure Process
**Signal**: "close account", "cancel card", "how to close", "want to cancel"
**Root Cause Tree**:
- Account closure process intentionally hidden (retention design, not user-friendly design)
- Must call to close (no self-service path)
- Outstanding balance, rewards, or pending transactions block closure without explanation
- No confirmation of closure outcome
**Self-Service Gap**: Can customer initiate closure online? Are pre-closure requirements shown upfront (zero balance, no pending transactions)? Is there a "what you'll lose" summary before confirming?
**Typical Volume**: 3–5% of profile calls
**Call Reduction Lever**: Self-service closure initiation with pre-closure checklist, "You have 5,000 points — redeem before closing" warning, post-closure confirmation with timeline for final statement

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `exact_problem_statement` and `digital_friction` within the profile bucket
2. **Self-Service Mapping**: For each pattern, check if the current process is self-service or agent-required
3. **Volume Impact**: Size each pattern as % of total profile calls
4. **Policy vs Technology Split**: Distinguish updates blocked by policy (security, regulatory) vs blocked by technology (feature not built)
5. **Cross-Reference**: Apply `apply_skill("profile_settings", bucket)` for enriched context

## Per-Lens Guidance

| Lens | What to look for in profile data |
|------|----------------------------------|
| **Digital** | Which updates can be done self-service? Where does the self-service flow break? Is the settings page findable? |
| **Operations** | How long do profile updates take to process? Are document reviews backlogged? Does the change propagate across systems? |
| **Communication** | Is update confirmation sent? Are requirements listed before starting? Is processing timeline communicated? |
| **Policy** | Which updates genuinely require agent verification? Are documentation requirements proportional to risk? Can any agent-only updates be shifted to self-service? |

## Anti-Patterns (What NOT to Conclude)
- Don't assume all agent-required updates are unnecessary security — some genuinely protect against account takeover
- Don't recommend making ALL profile changes self-service without security analysis — name changes and primary contact changes have fraud implications
- Don't conflate the customer wanting a simple change with the change BEING simple — some changes have regulatory requirements
- Don't blame "lazy customers" for not finding settings — if the self-service path requires 6 taps to reach, findability is the bank's problem
