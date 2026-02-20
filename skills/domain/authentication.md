# Authentication Analysis Skill

## Focus Areas
- Login failures and account access issues
- OTP (One-Time Password) delivery and verification
- Biometric authentication (fingerprint, face recognition)
- Session management and timeouts
- Password reset and recovery flows
- Multi-factor authentication issues

## Key Fields to Analyze
- `exact_problem_statement` — Customer's specific authentication issue
- `digital_friction` — Digital barriers during authentication
- `solution_by_technology` — Technology fixes for auth problems
- `call_reason` → `granular_theme_l5` — Full call reason hierarchy

## Analysis Framework

### Step 1: Categorize by Authentication Method
- **Password-based** — forgot password, incorrect password, locked account
- **OTP-based** — OTP not received, OTP expired, wrong OTP entered
- **Biometric** — fingerprint not recognized, face ID failure, sensor issues
- **Device-based** — device change, trusted device removal, new device registration
- **Session** — unexpected logouts, session expiry, concurrent session limits

### Step 2: Identify Failure Points
- At which step does authentication fail? (initiation, verification, completion)
- Is the failure device-specific (iOS vs Android, browser vs app)?
- Is there a carrier/network dependency (OTP delivery)?
- How many retry attempts before the customer calls?

### Step 3: Assess User Impact
- Account lockout rate and duration
- Time to resolution (self-service vs agent-assisted)
- Abandon rate at authentication step
- Security vs usability trade-off analysis

### Step 4: Map Solutions
- **Technology** — OTP retry mechanisms, biometric fallbacks, session management improvements
- **UI** — clearer error messages, progress indicators, alternative auth prompts
- **Ops** — faster account unlock processes, identity verification procedures
- **Education** — guiding customers on device setup, password best practices

## Investigation Questions
1. What is the breakdown of authentication issues by method (password/OTP/biometric)?
2. What percentage of OTP issues are delivery failures vs user errors?
3. How often do biometric failures lead to fallback to password?
4. What is the account lockout rate and average lockout duration?
5. Are authentication error messages actionable?
6. What is the self-service resolution rate for authentication issues?
7. How do authentication issues vary by platform (mobile app/web/desktop)?
