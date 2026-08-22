# Revocations

Each revocation is one immutable, UUID-named JSON file validated against the
revocation schema. A matching revocation ends active coordination immediately;
removing the branch-local claim happens later in a Full deactivation transition.
