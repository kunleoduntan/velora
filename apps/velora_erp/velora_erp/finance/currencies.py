"""Major world currencies pre-loaded into the Currency master (ISO 4217). Idempotent: existing rows are never changed."""
from velora import get_list, new_doc

# code, name, symbol, fraction, decimals
MAJOR_CURRENCIES = [
    ("NGN", "Nigerian Naira", "₦", "Kobo", 2), ("USD", "US Dollar", "$", "Cent", 2), ("EUR", "Euro", "€", "Cent", 2),
    ("GBP", "Pound Sterling", "£", "Penny", 2), ("JPY", "Japanese Yen", "¥", "Sen", 0), ("CNY", "Chinese Yuan", "¥", "Fen", 2),
    ("CHF", "Swiss Franc", "CHF", "Rappen", 2), ("CAD", "Canadian Dollar", "$", "Cent", 2), ("AUD", "Australian Dollar", "$", "Cent", 2),
    ("NZD", "New Zealand Dollar", "$", "Cent", 2), ("INR", "Indian Rupee", "₹", "Paisa", 2), ("ZAR", "South African Rand", "R", "Cent", 2),
    ("GHS", "Ghanaian Cedi", "GH₵", "Pesewa", 2), ("KES", "Kenyan Shilling", "KSh", "Cent", 2), ("UGX", "Ugandan Shilling", "USh", "Cent", 0),
    ("TZS", "Tanzanian Shilling", "TSh", "Cent", 2), ("RWF", "Rwandan Franc", "FRw", "Centime", 0), ("ETB", "Ethiopian Birr", "Br", "Santim", 2),
    ("EGP", "Egyptian Pound", "E£", "Piastre", 2), ("MAD", "Moroccan Dirham", "MAD", "Centime", 2), ("XOF", "West African CFA Franc", "CFA", "Centime", 0),
    ("XAF", "Central African CFA Franc", "FCFA", "Centime", 0), ("ZMW", "Zambian Kwacha", "ZK", "Ngwee", 2), ("BWP", "Botswana Pula", "P", "Thebe", 2),
    ("AED", "UAE Dirham", "د.إ", "Fils", 2), ("SAR", "Saudi Riyal", "﷼", "Halala", 2), ("QAR", "Qatari Riyal", "﷼", "Dirham", 2),
    ("KWD", "Kuwaiti Dinar", "KD", "Fils", 3), ("TRY", "Turkish Lira", "₺", "Kuruş", 2), ("RUB", "Russian Ruble", "₽", "Kopeck", 2),
    ("BRL", "Brazilian Real", "R$", "Centavo", 2), ("MXN", "Mexican Peso", "$", "Centavo", 2), ("ARS", "Argentine Peso", "$", "Centavo", 2),
    ("SGD", "Singapore Dollar", "$", "Cent", 2), ("HKD", "Hong Kong Dollar", "$", "Cent", 2), ("MYR", "Malaysian Ringgit", "RM", "Sen", 2),
    ("THB", "Thai Baht", "฿", "Satang", 2), ("IDR", "Indonesian Rupiah", "Rp", "Sen", 2), ("PHP", "Philippine Peso", "₱", "Centavo", 2),
    ("KRW", "South Korean Won", "₩", "Jeon", 0), ("PKR", "Pakistani Rupee", "₨", "Paisa", 2), ("SEK", "Swedish Krona", "kr", "Öre", 2),
    ("NOK", "Norwegian Krone", "kr", "Øre", 2), ("DKK", "Danish Krone", "kr", "Øre", 2), ("PLN", "Polish Złoty", "zł", "Grosz", 2),
]


def ensure_currencies() -> int:
    have = {r["name"] for r in get_list("Currency", fields=["name"], limit=1000, ignore_permissions=True)}
    made = 0
    for code, name, symbol, fraction, dp in MAJOR_CURRENCIES:
        if code in have:
            continue
        new_doc("Currency", currency_code=code, currency_name=name, symbol=symbol, fraction_name=fraction, decimal_places=dp).insert(ignore_permissions=True)
        made += 1
    return made


# name, applies to
DEFAULT_TRANSACTION_TYPES = [
    ("Customer Receipt", "Receipt"), ("Customer Advance", "Receipt"), ("Other Income", "Receipt"), ("Loan Received", "Receipt"), ("Capital Introduced", "Receipt"),
    ("Supplier Payment", "Payment"), ("Expense", "Payment"), ("Salary & Wages", "Payment"), ("Tax Remittance", "Payment"), ("Loan Repayment", "Payment"),
    ("Asset Purchase", "Payment"), ("Refund", "Both"), ("Transfer", "Both"), ("Other", "Both"),
]


def ensure_transaction_types() -> int:
    have = {r["name"] for r in get_list("Transaction Type", fields=["name"], limit=1000, ignore_permissions=True)}
    made = 0
    for name, applies in DEFAULT_TRANSACTION_TYPES:
        if name not in have:
            new_doc("Transaction Type", type_name=name, applies_to=applies).insert(ignore_permissions=True)
            made += 1
    return made
