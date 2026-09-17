from ipware import get_client_ip
import geoip2.database

reader = geoip2.database.Reader("/path/to/GeoLite2-Country.mmdb")


def get_country_from_request(request) -> str | None:
    ip, _ = get_client_ip(request)
    if not ip:
        return None
    try:
        return reader.country(ip).country.iso_code  # e.g. "US"
    except Exception:
        return None
