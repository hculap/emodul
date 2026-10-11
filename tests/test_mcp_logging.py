import logging


def test_mcp_server_keeps_http_request_urls_out_of_logs() -> None:
    # Request URLs carry user id, udid and menu PINs (/menu/MS/0:<pin>).
    import emodul.mcp.server  # noqa: F401  (configures logging on import)

    for name in ("httpx", "httpcore"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.WARNING
