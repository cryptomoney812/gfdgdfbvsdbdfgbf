import json
import base64
import re

KNOWN_PLACEHOLDERS = {"domain", "token", "amount", "address", "from", "d", "s"}

TEMPLATE_PRESETS = {
    "heleket":   "{domain}/?t={token}",
    "coinbase":  "{domain}/?d={d}",
    "cryptomus": "{domain}/?s={s}",
}

PRESET_LABELS = {
    "heleket":   "Heleket",
    "coinbase":  "Coinbase",
    "cryptomus": "Cryptomus",
}


def validate_template(template: str) -> list[str]:
    """
    Находит все {placeholder} в шаблоне.
    Возвращает список тех, что не входят в KNOWN_PLACEHOLDERS.
    """
    found = re.findall(r"\{(\w+)\}", template)
    return [p for p in found if p not in KNOWN_PLACEHOLDERS]


def _encode_coinbase(address: str, amount: float, from_tag: str) -> str:
    """
    Кодирует JSON {address, amount, from} в Base64 (UTF-8 совместимый).
    Аналог JS: btoa(unescape(encodeURIComponent(json)))
    """
    payload = json.dumps(
        {
            "address": address,
            "amount": f"{amount:.2f}",
            "from": from_tag,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    encoded = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return encoded


def _encode_cryptomus(amount: float) -> str:
    """
    Кодирует сумму в URL-safe Base64 без символов '='.
    Аналог JS: btoa(amount.toFixed(2)).replace('+','-').replace('/','_').rstrip('=')
    """
    raw = f"{amount:.2f}"
    encoded = base64.b64encode(raw.encode("ascii")).decode("ascii")
    return encoded.replace("+", "-").replace("/", "_").rstrip("=")


def build_invoice_url(
    site: dict,
    token: str,
    amount: float,
    user_tag: str,
) -> str:
    """
    Формирует ссылку на чек по шаблону сайта.

    :param site: запись из таблицы sites (dict с ключами domain, url_template, wallet_address)
    :param token: токен чека
    :param amount: сумма чека
    :param user_tag: тег воркера
    :returns: готовая ссылка
    :raises ValueError: если сумма невалидна, wallet_address отсутствует для Coinbase,
                        или шаблон содержит неизвестные плейсхолдеры
    """
    if amount <= 0 or amount > 1_000_000:
        raise ValueError("Invalid amount")

    url_template = site["url_template"]

    unknown = validate_template(url_template)
    if unknown:
        raise ValueError(f"Unknown placeholder: {{{unknown[0]}}}")

    # Вычисляем значения для специальных плейсхолдеров
    d_value = ""
    s_value = ""

    if "{d}" in url_template:
        wallet_address = site.get("wallet_address") or ""
        if not wallet_address:
            raise ValueError("wallet_address is required for Coinbase template")
        d_value = _encode_coinbase(wallet_address, amount, user_tag)

    if "{s}" in url_template:
        s_value = _encode_cryptomus(amount)

    domain = site.get("domain", "").rstrip("/")
    wallet_address = site.get("wallet_address") or ""

    url = url_template
    url = url.replace("{domain}", domain)
    url = url.replace("{token}", token)
    url = url.replace("{amount}", f"{amount:.2f}")
    url = url.replace("{address}", wallet_address)
    url = url.replace("{from}", user_tag)
    url = url.replace("{d}", d_value)
    url = url.replace("{s}", s_value)

    return url
