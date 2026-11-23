# Hallmark redesign review

Scope: home, pricing, login/registration and the existing role-based workspace.
Original commit: 58d0ab2. Independent subagent review: no; review performed in-thread.

## Source audit

Original recorded sources: 822 Floor findings, 314 Reflex findings.
Final changed-source audit: 0 Floor findings, 0 Reflex findings, 33 warnings and 4 copy notes.
The audit covers index.html, public home/pricing, tokens/base, shared design styles,
workspace-ui.css and platform-console.css. Unchanged library CSS is not presented as newly audited output.
Recorded contracts kept: links 33/33; fields 131/131; inline handlers 1/1; script hooks 43/43.
No routes, fields, scripts or business actions were dropped. Only decorative arrows and account icons were removed.

## Renderer and review limits

Hallmark's Puppeteer renderer is unavailable. The command reports that limit.
Playwright/installed Edge supplies the before/after screenshots and actual interaction checks.
A static pass is not represented as a Hallmark render pass or a WCAG conformance certification.
The original public illustrations and claims are retained as owner-supplied material, not new evidence.

## Warning decisions

- Gate 3: existing comparable plan columns and integration badges are retained; feature icon tiles have no filled tile and panels are flattened.
- Gate 23: former hero-context marker has no element and is disabled; green stays on actions and selected navigation.
- Gate 49: switcher labels deliberately wrap with their descriptions; five viewport-width checks verify fit.
- F1: original apostrophes and legal copy stay unchanged.
- F3: shared base rules apply balanced heading wrapping; source-local warnings miss those declarations.
- F4: one primary action style; selected navigation, billing intervals and account choices are states, not extra purchase actions. Existing role switches retain their behavior.
- F6: shared public style applies tabular numerals to pricing.
- F24: the new shared theme removes hero, account-menu and recovery shadows.
- Gates 40/41: actual browser-computed contrast was measured, and discovered pricing/sidebar issues were fixed. Old declarations remain visible to the static scanner; the final cascade overrides them. Original dark logo panel explicitly sets light text.
- F7: consistent container recipes intentionally identify repeated application surfaces; nested goods disclosures and section examples have no second card boundary.
- Gate 74: existing Tailwind classes and hooks remain for compatibility; explicit shared theme styles own the redesigned appearance.
- Copy notes: existing titles/disclaimers are retained as material. Hero wording changes and decorative removals are listed in docs/hallmark_redesign.md.

## Hero review, in-thread

Fix: the action needs to remain above the desktop fold, and smaller phones need readable controls.
Resolved: tested 1280x800, 1440x900 and 1920x1080 primary tracking action bounds;
320px and 375px home layouts have no page overflow. Original tracking form remains the action.

## Finish review, in-thread

Fix: pricing-table contrast, mobile menu clipping, registration brand-panel alignment.
Resolved: actual pricing contrast probe has no visible-text findings; all nine mobile destinations
fit a two-column menu with no horizontal scroll; selecting one dismisses that disclosure;
registration brand panel aligns at its first row. Keyboard focus and reduced-motion checks pass.
The original mobile bar exposed some actions without a tap; the new menu adds one tap in return
for readable access to every role-allowed destination. That is a deliberate navigation tradeoff.

## Validation receipt

- Existing account/public/manifest backend regression: 51 tests and 3 subtests passed.
- Existing WhatsApp quote-to-sign-in browser regression: passed; edited draft, login and restored-session prefill verified.
- New offline browser acceptance: home/pricing/account plus nine customer tabs; widths 320,390,768,1440,1920; no JS errors; all APIs mocked.
- New assets included by the existing Vercel build: 30 public assets, 158 worker source files.
- Existing manifest browser fixture: five account roles completed 18-state action checks, then its SUPER_ADMIN visibility assertion failed. Identical failure reproduced on 58d0ab2; not claimed as a passing suite.
- No external provider calls, live WhatsApp sends, database migrations, bookings, payments or deployments.

The existing pricing, illustrative feedback and integration statements still require owner verification before launch.
No new imagery is required for this review; future first-party product photography could replace only the existing clearly labelled examples after approval.
