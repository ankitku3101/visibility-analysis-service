"""Citation counts with a written-down dedup rule. Citations are counted, never treated as verified support."""
from collections import defaultdict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

DEDUP_RULE = (
    "occurrences = every citation row (inline and sources panel counted separately). "
    "unique = per response, after normalising the URL: lowercase scheme and host, drop '#fragment', "
    "drop utm_* query parameters, drop a trailing '/'. Domains drop a leading 'www.'. "
    "All citations are unverified: no cited page was opened."
)


def normalise_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    query = urlencode([(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                       if not k.lower().startswith("utm_")])
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def domain_of(row: dict) -> str:
    host = row.get("domain")
    if not host:
        try:
            host = urlsplit(row.get("url") or "").hostname
        except ValueError:
            host = None
    host = (host or "unknown").lower()
    return host[4:] if host.startswith("www.") else host


def is_kasparro(domain: str) -> bool:
    return domain == "kasparro.com" or domain.endswith(".kasparro.com")


def citation_stats(rows: list[dict], response_ids: list[str], top: int = 10) -> dict:
    """rows: citation rows (response_id, url, domain, citation_type) for the responses in `response_ids`."""
    by_response = defaultdict(set)
    by_type = defaultdict(int)
    domain_rows, domain_responses = defaultdict(int), defaultdict(set)
    for row in rows:
        by_response[row["response_id"]].add(normalise_url(row["url"]))
        by_type[row["citation_type"]] += 1
        d = domain_of(row)
        domain_rows[d] += 1
        domain_responses[d].add(row["response_id"])

    kasparro_domains = [d for d in domain_rows if is_kasparro(d)]
    kasparro_responses = set().union(*(domain_responses[d] for d in kasparro_domains)) if kasparro_domains else set()
    ranked = sorted(domain_rows, key=lambda d: (-len(domain_responses[d]), -domain_rows[d], d))[:top]
    n = len(response_ids)

    def share(x: int) -> dict:
        return {"x": x, "n": n, "rate": round(x / n, 3) if n else None}

    return {
        "status": "unverified",
        "occurrences": len(rows),
        "by_type": dict(sorted(by_type.items())),
        "unique_urls_per_response_summed": sum(len(urls) for urls in by_response.values()),
        "unique_urls_overall": len(set().union(*by_response.values())) if by_response else 0,
        "unique_domains": len(domain_rows),
        "responses_with_citations": share(len(by_response)),
        "kasparro_cited": share(len(kasparro_responses)) | {
            "occurrences": sum(domain_rows[d] for d in kasparro_domains)},
        "top_domains": [{"domain": d, "responses": len(domain_responses[d]), "occurrences": domain_rows[d]}
                        for d in ranked],
        "dedup_rule": DEDUP_RULE,
    }
