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
    # A missing rate does not prove the package exceeds every carrier's limits.
    from backend.package_guidance import PARCEL_RULES
    if request.dimensions:
        for dimensions, weight in zip(request.dimensions, request.weights_kg):
            longest, middle, shortest = sorted(
                [dimensions.length_cm, dimensions.width_cm, dimensions.height_cm], reverse=True)
            for rule in PARCEL_RULES:
                if (request.origin.country_code in rule['origin_countries']
                        and request.destination.country_code not in rule['excluded_destinations']
                        and (longest >= rule['max_longest_cm_exclusive']
                             or longest + 2 * (middle + shortest) >= rule['max_combined_cm_exclusive']
                             or weight > rule['max_weight_kg'])):
                    return ('Your package is larger or heavier than the standard limits of some carriers. '
                            'Open Packaging sizes for guidance, then check your actual packed measurements. '
                            'If they are correct, contact support for a suitable large-package service. '
                            'No rates are available from your connected services for this request.')
    return ('No shipping options are available for these details. Open Packaging sizes to check your '
            'package, and check the delivery address. If everything is correct, contact support to '
            'check available services for this route.')
