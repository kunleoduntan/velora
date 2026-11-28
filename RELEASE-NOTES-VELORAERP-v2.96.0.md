# VeloraERP 2.96.0 (with framework additions)

## Engagement (relationship moments)
Birthdays, work anniversaries, festive greetings and win-back messages for customers, suppliers and staff, in branded email templates. Automatic sending is OFF by default; messages are *Held* until released. Apps add their own moments through the `engagement_moments_provider` hook (Farepoint does).

## Portals
Employee portal (payslips, leave, holidays, colleagues' celebrations), a Messages page and an email on/off switch for every portal user. React + TypeScript, typed API, loading skeletons.

## Passwords and users (framework)
- One password standard (`controlplane/passwords.py`) used by sign-in, change, reset and administrators.
- Administrator can **issue a temporary password** from *Users, Roles & Access*: shown once with a Copy button, hidden after 45 seconds, never emailed. The user must choose their own at first sign-in; until then the session can only change the password.
- New users can be created with a temporary password in one step.
- **Forgot password?** on the sign-in screen. With email set up: a one-time link valid 30 minutes. Without email: the request waits in the administrator's list (Password reset requests) and the administrator issues a temporary password. Answers never reveal whether an account exists; requests are throttled (3 per hour per account).
- Email for reset links: set under *Password-reset email* on the same page (SMTP host and sender; the SMTP password is read from an environment variable).

## Simple workflows (framework)
Workflow designer opens in two plain tables (States, Transitions: from, button, to, who). Workflows that use conditions, several approvers or parallel sign-off open in the Advanced designer and are never flattened.

## Business Insights: 14 decision reports (module Administration)
Access by Role, Users and Their Roles, Role Conflicts in Use, Activity Pulse, Data Quality Scorecard, Message Delivery Health, Pending Approvals Ageing, Customer Concentration, Supplier Dependency, Cash Outlook, Collections Priority, Sales and Purchases Trend, Customer Segments, Business Pulse. Shown in the new *Business Insights* hub.
