/**
 * One place for the facts the legal pages depend on.
 *
 * LEGAL_VERSION must match `legal_policy_version` in backend/app/config.py:
 * it is what a new account's consent record says they agreed to. Bump both
 * whenever the Terms or the Privacy Policy change in substance.
 */
export const LEGAL_VERSION = "2026-10-08";
export const LEGAL_UPDATED = "8 October 2026";

/**
 * Where people send privacy requests and legal notices. If it is ever left
 * empty, the pages point to the feedback form instead, which also reaches
 * the team.
 */
export const LEGAL_CONTACT_EMAIL = "alabichy@gmail.com";
