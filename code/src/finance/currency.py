from dataclasses import dataclass
from datetime import date
from code.src.data.repository import DataRepository


@dataclass
class CurrencyConversionResult:
    original_amount: float
    original_currency: str
    converted_amount: float
    home_currency: str
    exchange_rate_used: float
    exchange_rate_date: date
    warning: str | None = None


def convert_currency_detailed(
    original_amount: float,
    from_currency: str,
    home_currency: str,
    rate_date: date,
    repo: DataRepository,
) -> CurrencyConversionResult:
    """
    CURRENCY RULE:

    All financial calculations must be performed in the user's home currency.

    For every financial event:

    IF event.currency == user.home_currency:
        converted_amount = original_amount
    ELSE:
        look up the applicable exchange rate from exchange_rates.csv
        using the challenge-specified date and currency pair.
        converted_amount = original_amount * rate

    Never perform arithmetic across mixed currencies.

    Store both:
    - original_amount
    - original_currency
    - converted_amount
    - home_currency
    - exchange_rate_used
    - exchange_rate_date

    If a required exchange rate is unavailable:
        do NOT invent a rate.
        Record an error/warning and follow the repository's specified fallback.
    """
    if from_currency == home_currency:
        return CurrencyConversionResult(
            original_amount=original_amount,
            original_currency=from_currency,
            converted_amount=original_amount,
            home_currency=home_currency,
            exchange_rate_used=1.0,
            exchange_rate_date=rate_date,
            warning=None,
        )

    rate, effective_date, warning = repo.lookup_exchange_rate_detailed(
        from_currency, home_currency, rate_date
    )
    converted_amount = round(original_amount * rate, 4)

    return CurrencyConversionResult(
        original_amount=original_amount,
        original_currency=from_currency,
        converted_amount=converted_amount,
        home_currency=home_currency,
        exchange_rate_used=rate,
        exchange_rate_date=effective_date,
        warning=warning,
    )


def convert_currency(
    amount: float,
    from_currency: str,
    to_currency: str,
    rate_date: date,
    repo: DataRepository,
) -> float:
    """
    Convenience wrapper returning converted_amount.
    """
    res = convert_currency_detailed(
        original_amount=amount,
        from_currency=from_currency,
        home_currency=to_currency,
        rate_date=rate_date,
        repo=repo,
    )
    return res.converted_amount

