# Design: EasyInvio

Shared visual system for the public home, pricing, account and workspace screens.
All routes, fields, account checks, financial approvals and provider logic stay in their existing modules.

## System
- Genre: modern-minimal.
- Theme: retained EasyInvio brand, light working surfaces and dark green navigation.
- Home shape: shipping workbench; first action is the existing secure tracking form.
- App shape: existing role-based shell with a shipment comparison workbench.
- Signature: shipping, tracking and WhatsApp in one connected workflow.
- Original brand-mark.svg is preserved without modification.

## Tokens
`tokens.css` is the source of truth for palette, type, spacing and motion.
- Brand green: #34d399, read from brand.css. Darkened action green: #087a51 for contrast on light surfaces.
- Paper: #f5f8f7; panel: #ffffff; ink: #172c25; muted: #52685e.
- Navigation: #11251e, with #e6eee9 text.
- Display: Segoe UI Variable Display; body: Segoe UI Variable Text, both locally available fallbacks.
- No new font CDN or runtime dependency.
- App type scale: 1.125–1.2. Home display scales separately, capped at 80px.
- Spacing: 4px grid with 2px optical detail.
- Panel radius: 16px; input/button: 10px; navigation disclosure: pill.

## Controls
- Primary: green, white text; one visual style across all surfaces.
- Secondary: neutral outline; minimum 44px hit target.
- Focus: immediate 3px green outline with 3px offset.
- Existing disabled, loading, error and success logic is retained, with shared presentation.
- Inputs remain native and retain their original ids, names and validation attributes.

## Navigation and responsive rules
- Desktop: existing destinations on the dark sidebar.
- Under 1024px: all existing destinations in a native Workspace menu disclosure.
- Under 640px: account and shipment layouts stack; tables keep their accessible scroll wrappers.
- Containers stop growing at 1440px; gutters grow on larger monitors.

## Motion
- Only brief colour/opacity/transform feedback. No decorative reveal.
- Reduced motion removes animation and transition.

## Exports
`tokens.css`, `base.css`, `design-system.css`, `public-redesign.css`.
