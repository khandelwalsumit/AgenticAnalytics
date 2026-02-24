# Authentication & Account Access — Domain Skill

## When to Apply
Use this skill when analyzing call data where `call_reason` or theme hierarchy contains: Sign On, Login, Password, OTP, Authentication, Account Locked, Verification, MFA, Biometric, Session, Device Registration.

## Key Data Fields
- `exact_problem_statement` — Customer's verbatim authentication issue
- `digital_friction` — Digital barrier during the auth flow
- `solution_by_technology` — Technology fix recommendations
- `solution_by_ui` — UI/UX improvements for auth flows
- `solution_by_education` — Customer guidance for self-service auth resolution
- `call_reason` → `granular_theme_l5` — Hierarchical call classification
- `friction_driver_category` — Root friction type label

## Friction Pattern Library

### Pattern 1: OTP Delivery Failures
**Signal**: Problem statements mentioning "didn't receive OTP", "no code", "OTP expired", "wrong number"
**Root Cause Tree**:
- Carrier-side SMS filtering or delay (not bank's fault but bank's problem)
- Customer's registered number is outdated
- OTP channel limited to SMS only (no email, authenticator, push fallback)
- OTP validity window too short for delivery + input
**Self-Service Gap**: Can the customer request OTP resend? Switch delivery channel? See delivery status? Update phone number without calling?
**Typical Volume**: 25–40% of all authentication calls
**Call Reduction Lever**: Add fallback OTP channels (email, push notification), extend validity window, show "OTP sent to XXX-XX-1234" with resend option

### Pattern 2: Account Lockout After Failed Attempts
**Signal**: "locked out", "too many attempts", "can't get in", "account blocked"
**Root Cause Tree**:
- Lockout threshold too aggressive (3 attempts is industry norm, some banks use 5)
- No incremental friction (goes from open → locked with no middle state)
- Lockout duration not communicated ("locked for 30 minutes" vs "call us")
- Self-service unlock unavailable or hidden
**Self-Service Gap**: Can customer unlock via email verification? Via security questions? Via in-app biometric fallback?
**Typical Volume**: 15–25% of authentication calls
**Call Reduction Lever**: Add timed auto-unlock (30 min), enable self-service unlock via alternate verification, show remaining attempts before lockout

### Pattern 3: Device Change / New Device Registration
**Signal**: "new phone", "changed device", "not recognized", "re-register", "trusted device"
**Root Cause Tree**:
- Device binding requires in-person or phone verification
- No pre-migration flow ("moving to new phone? Here's how")
- Old device deactivation process unclear
- Customer didn't know device was "trusted"
**Self-Service Gap**: Can customer register new device via web? Can they transfer trust from old device? Is there a one-time bypass for known customers?
**Typical Volume**: 10–15% of authentication calls
**Call Reduction Lever**: Device migration wizard, email-based device approval, grace period for new device first login

### Pattern 4: Password Reset Friction
**Signal**: "forgot password", "reset not working", "link expired", "password rules"
**Root Cause Tree**:
- Reset link expires too quickly (15 min is too short)
- Password complexity rules unclear until rejection
- Reset flow requires information customer doesn't have
- Verification method for reset is broken (see Pattern 1 OTP issues)
**Self-Service Gap**: Is the reset flow 100% self-service? Are complexity rules shown proactively? Is there a "forgot username" path?
**Typical Volume**: 10–20% of authentication calls
**Call Reduction Lever**: Extend reset link validity, show password rules before entry, biometric-based reset, in-app reset without email

### Pattern 5: Session Timeout During Multi-Step Flows
**Signal**: "logged me out", "session expired", "lost my progress", "had to start over"
**Root Cause Tree**:
- Session timeout too aggressive (5 min) for complex forms
- No session save/resume capability
- No warning before timeout
- Timeout applies to background app (user switched to check SMS for OTP)
**Self-Service Gap**: Can the session be extended? Can progress be saved? Does the app warn before timeout?
**Typical Volume**: 5–10% of authentication calls (but high frustration multiplier)
**Call Reduction Lever**: Extend timeout for active forms, add "session expiring" warning, save form state, don't count OTP tab-out as idle

### Pattern 6: Biometric Authentication Failures
**Signal**: "fingerprint not working", "face ID failed", "biometric not recognized"
**Root Cause Tree**:
- Biometric enrollment was incomplete or corrupted
- Device OS update changed biometric API
- No clear fallback path shown when biometric fails
- Re-enrollment requires full re-authentication (chicken-and-egg)
**Self-Service Gap**: Is there a clear "biometric not working? Tap here for PIN" fallback? Can user re-enroll without calling?
**Typical Volume**: 5–10% of authentication calls (growing with mobile adoption)
**Call Reduction Lever**: Always show PIN fallback, detect biometric failure and proactively offer alternatives, in-app re-enrollment flow

## Analysis Workflow

1. **Distribution Analysis**: Use `analyze_bucket` to get distribution of `digital_friction` and `exact_problem_statement` values within the auth bucket
2. **Pattern Matching**: Map top problem statements to the 6 patterns above
3. **Volume Sizing**: Note the percentage of the auth bucket each pattern represents
4. **Self-Service Assessment**: For each pattern, check `solution_by_technology` and `solution_by_ui` to see what fixes are already suggested in the data
5. **Cross-Reference**: Apply `apply_skill("authentication", bucket)` to get enriched context

## Per-Lens Guidance

| Lens | What to look for in auth data |
|------|------------------------------|
| **Digital** | Is the auth flow completable end-to-end in app? Where does it break? Is error messaging actionable? |
| **Operations** | Is account unlock manual? Are verification teams bottlenecked? Is there batch processing delay? |
| **Communication** | Is lockout duration communicated? Is OTP delivery status visible? Are security alerts timely? |
| **Policy** | Is MFA mandatory by regulation or internal choice? Are lockout thresholds regulatory? Can biometric satisfy KYC? |

## Anti-Patterns (What NOT to Conclude)
- Don't attribute OTP carrier failures to the bank's app quality
- Don't assume all lockouts are security events — most are genuine forgot-password scenarios
- Don't recommend removing security controls — recommend making them smoother
- Don't conflate authentication friction with authorization friction (auth = who you are, authz = what you're allowed to do)
