# Landing brand assets and onboarding boundaries

SVG marks in `frontend/landing/index.html` are embedded locally in an allowlisted SVG sprite. Geometry comes from the sources below; fills are adapted for the slate/indigo palette. No endorsement or universal service availability is implied. Brand names and trademarks belong to their respective owners.

Downloaded XML is parsed during implementation. Only geometry elements and allowlisted presentation attributes are retained; scripts, styles, event handlers, foreign objects, external links and network references are excluded. No downloaded XML is parsed or injected at runtime.

## Sources

- dpd: https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/dpd.svg
- dhl: https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/dhl.svg
- ups: https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/ups.svg
- shopify: https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/shopify.svg
- woocommerce: https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/woocommerce.svg
- whatsapp: https://raw.githubusercontent.com/simple-icons/simple-icons/develop/icons/whatsapp.svg
- royalmail: https://raw.githubusercontent.com/gil--/shipping_carrier_icons/main/svg/royalmail.svg
- evri: https://raw.githubusercontent.com/gil--/shipping_carrier_icons/main/svg/evri.svg
- amazon: https://raw.githubusercontent.com/simple-icons/simple-icons/13.21.0/icons/amazon.svg
- shippo: https://cdn.prod.website-files.com/6462967bbf70fa5b5b227351/646bd3ac70ee08fca9869afe_shippo-logo-dark.svg
- gupshup: https://www.gupshup.ai/resources/wp-content/uploads/2025/02/logo.svg
- sendcloud: https://www.sendcloud.com/en-uk/
- easypost: https://docs.easypost.com/branding/easypost-primary-logo.svg

Simple Icons geometry is distributed under CC0: https://github.com/simple-icons/simple-icons/blob/develop/LICENSE.md . Carrier SVGs from `gil--/shipping_carrier_icons` use the MIT license reproduced below. Provider-owned marks remain their owners’ trademarks.

## Existing security controls

No authentication routes, registration request models, cookie flags, CSRF checks, CSP, JWKS verification, session revocation or assistance controls change. `mode` recognizes `signin` and `signup`; legacy `signup=1` remains supported. Only `ecommerce`, `dispatch` and `mobile` are accepted as onboarding hints. The optional workflow selection changes onboarding guidance only; it is not sent as a role, permission, tenant identifier, provider connection or unsupported registration field. Business/Personal selection and email verification remain explicit existing controls. No preference or token is written to browser storage.

## Carrier SVG license

Copyright 2024 Checkout Blocks Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the “Software”), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
