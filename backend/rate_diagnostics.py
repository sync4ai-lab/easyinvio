"""Safe rate diagnostics; never expose upstream response bodies or credentials."""


class RateCurrencyUnavailable(ValueError):
    def __init__(self, currencies):
        self.available_currencies = sorted(set(currencies) & {'GBP', 'EUR', 'USD'})
        super().__init__('NO_RATES_IN_REQUESTED_CURRENCY')


class RateHTTPRejected(ValueError):
    def __init__(self, status):
        self.status = status
        super().__init__('UPSTREAM_HTTP_REJECTED')


def no_rates_message(request, issues):
    if request.cargo_type in {'PALLET', 'OVERLAND_FREIGHT'}:
        return 'Freight booking requires a verified freight adapter and carrier contract. These parcel integrations cannot confirm freight availability.'
    if request.cargo_type == 'LETTER':
        return 'No eligible document service returned a rate. Platform support must check document-service availability and address verification.'
    currencies = sorted({currency for issue in issues for currency in issue.available_currencies})
    if currencies:
        return (f'Carrier quotes were returned in {", ".join(currencies)}, but none matched {request.currency}. '
                'Choose one of those quote currencies and request fresh rates. Payment requires a matching wallet currency; prices are never silently converted.')
    codes = {issue.code for issue in issues}
    if codes & {'UPSTREAM_AUTHENTICATION_REJECTED'}:
        return 'A connected provider rejected its credentials. Platform support must verify the API key and account permissions; no eligible quotes were returned by the other connections.'
    if codes & {'SENDCLOUD_METHODS_NOT_CONFIGURED', 'SENDCLOUD_CONFIGURATION_OR_PRICE_UNAVAILABLE'}:
        return 'A rate connection needs platform configuration. No eligible quotes were returned by the other connections. Platform support should check the configured rate adapter and enabled carrier contracts.'
    if codes & {'UPSTREAM_TIMEOUT', 'UPSTREAM_UNAVAILABLE'}:
        return 'A provider could not be reached or timed out. Retry the quote; platform support can verify the affected connection if this continues.'
    size = ''
    if request.dimensions:
        dimensions = request.dimensions[0]
        sides = sorted([dimensions.length_cm, dimensions.width_cm, dimensions.height_cm], reverse=True)
        combined = sides[0] + 2 * (sides[1] + sides[2])
        size = (f' Package dimensions: {dimensions.length_cm} × {dimensions.width_cm} × {dimensions.height_cm} cm; '
                f'combined length and girth: {combined} cm. Carrier-specific size limits may apply.')
    return ('The connected accounts returned no eligible priced services for this package and route.' + size +
            ' Check the packed weight and destination country/address. Platform support can check enabled carrier contracts.')
