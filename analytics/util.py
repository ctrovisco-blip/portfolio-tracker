"""Utilitários partilhados: datas, XIRR, arredondamentos."""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Iterable


def to_date(v) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return date.fromisoformat(str(v)[:10])


def add_years(d: date, years: int) -> date:
    """d + N anos (29 fev → 28 fev quando o ano destino não é bissexto)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def business_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def r2(v, nd=2):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return round(v, nd)


def pct(v, nd=2):
    """Fração → percentagem arredondada."""
    return None if v is None else r2(v * 100, nd)


def xirr(flows: Iterable[tuple[date, float]], guess: float = 0.1) -> float | None:
    """
    Taxa interna de rendibilidade anualizada para fluxos datados
    (convenção: dinheiro que SAI do investidor é negativo).
    Newton-Raphson com fallback para bissecção. Devolve fração (0.12 = 12%).
    """
    fl = sorted(((to_date(d), float(a)) for d, a in flows if a), key=lambda x: x[0])
    if len(fl) < 2:
        return None
    if not (any(a < 0 for _, a in fl) and any(a > 0 for _, a in fl)):
        return None
    t0 = fl[0][0]
    ts = [((d - t0).days / 365.0, a) for d, a in fl]

    def npv(r):
        return sum(a / (1 + r) ** t for t, a in ts)

    def dnpv(r):
        return sum(-t * a / (1 + r) ** (t + 1) for t, a in ts)

    r = guess
    for _ in range(100):
        try:
            f, df = npv(r), dnpv(r)
        except (OverflowError, ZeroDivisionError):
            break
        if df == 0:
            break
        nr = r - f / df
        if nr <= -0.9999:
            break
        if abs(nr - r) < 1e-10:
            return nr
        r = nr

    # Bissecção em [-0.9999, 100]
    lo, hi = -0.9999, 100.0
    try:
        flo, fhi = npv(lo), npv(hi)
    except OverflowError:
        return None
    if flo * fhi > 0:
        return None
    for _ in range(300):
        mid = (lo + hi) / 2
        fm = npv(mid)
        if abs(fm) < 1e-9:
            return mid
        if flo * fm < 0:
            hi = mid
        else:
            lo, flo = mid, fm
    return (lo + hi) / 2


ISIN_COUNTRY_NUM = {
    # Códigos numéricos de país (ISO 3166) usados nos anexos do IRS
    "US": "840", "DE": "276", "GB": "826", "IE": "372", "NL": "528", "FR": "250",
    "CA": "124", "CH": "756", "ES": "724", "IT": "380", "LU": "442", "DK": "208",
    "SE": "752", "NO": "578", "FI": "246", "BE": "056", "AT": "040", "JP": "392",
    "CN": "156", "HK": "344", "KY": "136", "BM": "060", "JE": "832", "AU": "036",
    "BR": "076", "TW": "158", "KR": "410", "IL": "376", "PT": "620", "GG": "831",
    "IM": "833", "SG": "702", "IN": "356", "MX": "484", "ZA": "710", "PL": "616",
}

COUNTRY_NAME_PT = {
    "US": "EUA", "DE": "Alemanha", "GB": "Reino Unido", "IE": "Irlanda", "NL": "Países Baixos",
    "FR": "França", "CA": "Canadá", "CH": "Suíça", "ES": "Espanha", "IT": "Itália",
    "LU": "Luxemburgo", "DK": "Dinamarca", "SE": "Suécia", "NO": "Noruega", "FI": "Finlândia",
    "BE": "Bélgica", "AT": "Áustria", "JP": "Japão", "CN": "China", "HK": "Hong Kong",
    "KY": "Ilhas Caimão", "BM": "Bermudas", "JE": "Jersey", "AU": "Austrália", "BR": "Brasil",
    "TW": "Taiwan", "KR": "Coreia do Sul", "IL": "Israel", "PT": "Portugal", "SG": "Singapura",
}


def isin_country(isin: str | None) -> str | None:
    if not isin or len(isin) < 2:
        return None
    return isin[:2].upper()
