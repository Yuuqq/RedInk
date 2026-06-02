"""Safe helpers for consuming image bytes returned by upstream APIs."""

from __future__ import annotations

import ipaddress
import os
import socket
import base64
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter


DEFAULT_MAX_IMAGE_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_REDIRECTS = 3


@dataclass(frozen=True)
class _ResolvedHttpTarget:
    url: str
    hostname: str
    host_header: str
    ip_address: str


def _max_image_bytes() -> int:
    try:
        value = int(os.environ.get("REDINK_REMOTE_IMAGE_MAX_BYTES", str(DEFAULT_MAX_IMAGE_BYTES)))
    except Exception:
        value = DEFAULT_MAX_IMAGE_BYTES
    return max(1, value)


def _resolved_addresses(hostname: str) -> Iterable[ipaddress._BaseAddress]:
    try:
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError("URL 主机名无法解析") from e

    seen = set()
    for info in infos:
        address = info[4][0]
        if address in seen:
            continue
        seen.add(address)
        try:
            yield ipaddress.ip_address(address)
        except ValueError:
            continue


def _is_blocked_address(
    address: ipaddress._BaseAddress,
    *,
    allow_private: bool,
) -> bool:
    is_never_safe = (
        address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
    is_private_provider = address.is_loopback or address.is_private
    is_non_public = not address.is_global or is_private_provider
    return is_never_safe or (is_non_public and not allow_private) or (is_non_public and not is_private_provider)


def _validate_addresses(
    addresses: Iterable[ipaddress._BaseAddress],
    *,
    label: str,
    allow_private: bool,
) -> list[ipaddress._BaseAddress]:
    resolved = list(addresses)
    if not resolved:
        raise ValueError(f"{label} 主机名未解析到有效地址")

    for address in resolved:
        if _is_blocked_address(address, allow_private=allow_private):
            raise ValueError(f"{label} 指向非公网地址，已拒绝请求")

    return resolved


def allow_private_provider_urls() -> bool:
    return os.environ.get("REDINK_ALLOW_PRIVATE_PROVIDER_URLS", "").strip().lower() in ("1", "true", "yes")


def allow_unpinned_provider_urls() -> bool:
    return os.environ.get("REDINK_ALLOW_UNPINNED_PROVIDER_URLS", "").strip().lower() in ("1", "true", "yes")


def validate_public_http_url(
    url: str,
    *,
    label: str = "URL",
    allow_private: bool = False,
) -> str:
    """Validate that a server-side HTTP request target resolves to public IPs."""

    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"{label} 只允许 http/https")
    if not parsed.hostname:
        raise ValueError(f"{label} 缺少主机名")
    if parsed.username or parsed.password:
        raise ValueError(f"{label} 不允许包含用户名或密码")

    _validate_addresses(
        _resolved_addresses(parsed.hostname),
        label=label,
        allow_private=allow_private,
    )

    return parsed.geturl()


def _resolve_http_target(
    url: str,
    *,
    label: str,
    allow_private: bool,
) -> _ResolvedHttpTarget:
    safe_url = validate_public_http_url(url, label=label, allow_private=allow_private)
    parsed = urlparse(safe_url)
    addresses = _validate_addresses(
        _resolved_addresses(parsed.hostname or ""),
        label=label,
        allow_private=allow_private,
    )

    return _ResolvedHttpTarget(
        url=safe_url,
        hostname=parsed.hostname or "",
        host_header=parsed.netloc,
        ip_address=str(addresses[0]),
    )


class _PinnedIpAdapter(HTTPAdapter):
    """Requests adapter that connects to a vetted IP while preserving HTTP/TLS host identity."""

    def __init__(self, *, original_hostname: str, pinned_ip: str):
        self._original_hostname = original_hostname
        self._pinned_ip = pinned_ip
        super().__init__()

    def build_connection_pool_key_attributes(self, request, verify, cert=None):  # type: ignore[override]
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(request, verify, cert)
        host_params["host"] = self._pinned_ip
        if host_params.get("scheme") == "https":
            pool_kwargs["assert_hostname"] = self._original_hostname
            pool_kwargs["server_hostname"] = self._original_hostname
        return host_params, pool_kwargs


def safe_http_request(
    method: str,
    url: str,
    *,
    label: str = "URL",
    allow_private: bool = False,
    **kwargs: Any,
) -> requests.Response:
    """
    Perform a server-side HTTP request with DNS-rebinding-resistant SSRF guards.

    The hostname is resolved and validated immediately before connection. The
    request is then pinned to that vetted IP while preserving the original Host
    header and HTTPS SNI/certificate hostname.
    """

    target = _resolve_http_target(url, label=label, allow_private=allow_private)
    if kwargs.get("proxies"):
        raise ValueError(f"{label} 不允许使用代理请求")
    if kwargs.get("allow_redirects") is True:
        raise ValueError(f"{label} 不允许自动跟随重定向")

    headers = dict(kwargs.pop("headers", {}) or {})
    headers["Host"] = target.host_header
    kwargs["headers"] = headers
    kwargs.setdefault("allow_redirects", False)
    kwargs["proxies"] = {}

    session = requests.Session()
    session.trust_env = False
    adapter = _PinnedIpAdapter(
        original_hostname=target.hostname,
        pinned_ip=target.ip_address,
    )
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    try:
        response = session.request(method, target.url, **kwargs)
        if kwargs.get("stream"):
            original_close = response.close

            def _close_with_session() -> None:
                try:
                    original_close()
                finally:
                    session.close()

            response.close = _close_with_session  # type: ignore[method-assign]
            return response

        session.close()
        return response
    except Exception:
        session.close()
        raise


def safe_download_image(
    url: str,
    *,
    timeout: int = 60,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
    allow_private: bool = False,
) -> bytes:
    """
    Download an upstream image URL with SSRF and memory guardrails.

    Upstream image APIs sometimes return a URL instead of base64 bytes. Treat
    those URLs as untrusted input because a compromised/proxy upstream can point
    the server at private metadata or local services.
    """

    current_url = validate_public_http_url(url, label="图片 URL", allow_private=allow_private)
    max_bytes = _max_image_bytes()

    for _ in range(max_redirects + 1):
        response = safe_http_request(
            "GET",
            current_url,
            label="图片 URL",
            allow_private=allow_private,
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )

        if 300 <= response.status_code < 400:
            location = response.headers.get("Location")
            response.close()
            if not location:
                raise Exception("下载图片失败: 重定向缺少 Location")
            current_url = validate_public_http_url(
                urljoin(current_url, location),
                label="图片 URL",
                allow_private=allow_private,
            )
            continue

        if response.status_code != 200:
            response.close()
            raise Exception(f"下载图片失败: HTTP {response.status_code}")

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                declared_length = 0
            if declared_length > max_bytes:
                response.close()
                raise ValueError("图片下载大小超过限制")

        chunks = []
        total = 0
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("图片下载大小超过限制")
                chunks.append(chunk)
        finally:
            response.close()

        return b"".join(chunks)

    raise Exception("下载图片失败: 重定向次数过多")


def safe_decode_base64_image(value: str) -> bytes:
    """
    Decode an upstream base64 image response with the same memory limit as URL downloads.

    Upstream providers may return either a raw base64 string or a data URL.
    Treat the payload as untrusted because a misconfigured provider can return
    arbitrarily large content.
    """

    if not isinstance(value, str) or not value:
        raise ValueError("图片 Base64 数据为空")

    raw = value.strip()
    if raw.startswith("data:"):
        if "," not in raw:
            raise ValueError("图片 Base64 data URL 格式错误")
        meta, raw = raw.split(",", 1)
        if ";base64" not in meta.lower():
            raise ValueError("图片 data URL 必须使用 base64 编码")

    raw = raw.strip()
    max_bytes = _max_image_bytes()
    max_b64_len = int(max_bytes * 4 / 3) + 8
    if len(raw) > max_b64_len:
        raise ValueError("图片 Base64 数据超过大小限制")

    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as e:
        raise ValueError("图片 Base64 数据格式错误") from e

    if len(data) > max_bytes:
        raise ValueError("图片 Base64 数据超过大小限制")

    return data
