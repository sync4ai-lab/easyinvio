# Form validation and saved-address selections

`form-feedback.js` and `form-feedback.css` provide shared feedback on the main
workspace, Help Centre and public tracking pages. Document-level event handlers
also cover forms created later, including dialogs. Existing backend validation,
permissions, payment guards and business rules remain authoritative.

Before submit, invalid required, email, numeric, pattern and length constraints
produce an error summary, field messages and an error outline. The workspace
also shows its existing toast. The first invalid control receives focus, and
collapsed details containing invalid controls open. Optional blank controls do
not become mandatory. Required text containing only whitespace is rejected.
Messages clear as values are corrected; resetting a form clears the feedback.
Dynamic forms and programmatic submit events use the same guard. Explicit
`novalidate`/`formnovalidate` retain their native meaning; code must not add them
to purchase or registration forms to bypass required inputs.

The API wrapper translates validation error locations into readable labels such
as Delivery street instead of showing `body.destination.line1`. It does not
display submitted values, change the request or disable server validation.
Product-specific conditional rules and actions outside forms retain their own
validation. A valid form is not proof of carrier eligibility or payment success.

The saved-address picker clears prior results as soon as it opens or a search
changes. Responses and selection callbacks bind to an immutable pickup/delivery
side, session, workspace, search and request version. Closing the picker or
switching context invalidates old results. Selecting a record populates one side
atomically before firing dependent input/change events. It never deliberately
copies a recipient record into Pickup or fabricates missing address values.

Run the browser regression with:

```powershell
.\.venv\Scripts\python.exe -m tests.form_validation_browser
```

The isolated fixture checks the delayed-response race, retained stale buttons,
both address sides, whitespace, valid quote submission, 28 existing forms,
dynamic dialogs, collapsed details, email/file requirements and business owner,
workspace admin, dispatcher, accountant and individual personas. All records and
API replies are synthetic; it makes no real provider, payment or database calls.
It can also be run against a deployed frontend with mocked API responses to
check the shipped assets; that is not an authenticated backend integration test.

After source changes, regenerate the deployment bundle with
`python scripts/build_vercel.py --bundle`. The two feedback assets are in the
public CDN allowlist and have local FastAPI routes. Their external script/style
loading preserves the public tracking page's existing CSP.
