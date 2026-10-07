# Security policy

## Supported versions

hxadmin is pre-1.0: only the latest release gets security fixes.

## Reporting a vulnerability

Please do not open a public issue. Report it privately through GitHub: on the repository's **Security** tab, choose **Report a vulnerability**.

Include the affected version, how to reproduce it, and the impact you see. You will get an acknowledgement within a week; once a fix is released, the advisory is published and credits you unless you prefer otherwise.

## Scope

hxadmin renders an admin interface over your database, so issues that let one user act beyond their `auth`, `is_accessible`, `is_action_allowed` or `get_query` restrictions, cross-site request forgery, cross-site scripting, and leaks of database contents or errors are all in scope. Vulnerabilities in your own `auth` dependency or deployment are not, though we welcome reports of documentation that leads to unsafe setups.
