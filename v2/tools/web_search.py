"""
Outils Web Agent-OS V2.3.

Fonctions :
- recherche Web réelle avec DDGS ;
- récupération sécurisée du contenu de pages ;
- extraction de texte HTML ;
- contrôle des permissions hors LLM ;
- retour structuré des sources.
"""

from __future__ import annotations

import ipaddress
import socket

from dataclasses import (
    asdict,
    dataclass,
)

from html.parser import HTMLParser

from typing import (
    Any,
    Optional,
)

from urllib.parse import (
    urlparse,
)

from urllib.request import (
    Request,
    urlopen,
)

from ddgs import DDGS

from v2.permissions.permissions import (
    PermissionEngine,
    PermissionResult,
)


# ============================================================
# EXCEPTIONS
# ============================================================


class WebToolError(
    Exception
):
    """
    Erreur générique d'un outil Web.
    """


class WebToolPermissionError(
    WebToolError
):
    """
    Action Web refusée par le Permission Engine.
    """


# ============================================================
# DATA
# ============================================================


@dataclass
class WebSource:

    index: int

    title: str

    url: str

    snippet: str = ""

    content: str = ""

    fetched: bool = False

    error: Optional[str] = None

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return asdict(
            self
        )


@dataclass
class WebResearchResult:

    query: str

    sources: list[
        WebSource
    ]

    def to_dict(
        self,
    ) -> dict[str, Any]:

        return {
            "query": self.query,
            "sources": [
                source.to_dict()
                for source
                in self.sources
            ],
        }

    def build_context(
        self,
        max_chars_per_source: int = 6000,
    ) -> str:

        if not self.sources:

            return (
                "Aucune source Web trouvée."
            )

        sections = []

        for source in self.sources:

            text = (
                source.content.strip()
                or source.snippet.strip()
                or (
                    "Aucun contenu "
                    "exploitable."
                )
            )

            if (
                len(text)
                > max_chars_per_source
            ):

                text = (
                    text[
                        :max_chars_per_source
                    ]
                    + "\n[contenu tronqué]"
                )

            sections.append(
                "\n".join(
                    [
                        (
                            f"[S{source.index}] "
                            f"{source.title}"
                        ),
                        (
                            f"URL : "
                            f"{source.url}"
                        ),
                        (
                            f"Page récupérée : "
                            f"{'oui' if source.fetched else 'non'}"
                        ),
                        "",
                        text,
                    ]
                )
            )

        return (
            "\n\n"
            + (
                "\n\n"
                + "=" * 60
                + "\n\n"
            ).join(
                sections
            )
        )


# ============================================================
# HTML EXTRACTION
# ============================================================


class _HTMLTextExtractor(
    HTMLParser
):

    IGNORED_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
    }

    BLOCK_TAGS = {
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "nav",
        "p",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
        "ol",
    }

    def __init__(
        self,
    ) -> None:

        super().__init__()

        self.parts: list[
            str
        ] = []

        self.ignore_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs,
    ) -> None:

        tag = (
            tag.lower()
        )

        if (
            tag
            in self.IGNORED_TAGS
        ):

            self.ignore_depth += 1

            return

        if (
            self.ignore_depth == 0
            and tag
            in self.BLOCK_TAGS
        ):

            self.parts.append(
                "\n"
            )

    def handle_endtag(
        self,
        tag: str,
    ) -> None:

        tag = (
            tag.lower()
        )

        if (
            tag
            in self.IGNORED_TAGS
        ):

            if (
                self.ignore_depth > 0
            ):

                self.ignore_depth -= 1

            return

        if (
            self.ignore_depth == 0
            and tag
            in self.BLOCK_TAGS
        ):

            self.parts.append(
                "\n"
            )

    def handle_data(
        self,
        data: str,
    ) -> None:

        if (
            self.ignore_depth > 0
        ):

            return

        text = (
            data.strip()
        )

        if text:

            self.parts.append(
                text
            )

            self.parts.append(
                " "
            )

    def get_text(
        self,
    ) -> str:

        raw = "".join(
            self.parts
        )

        lines = []

        for line in (
            raw.splitlines()
        ):

            normalized = (
                " ".join(
                    line.split()
                )
            )

            if normalized:

                lines.append(
                    normalized
                )

        return "\n".join(
            lines
        )


# ============================================================
# WEB TOOL
# ============================================================


class WebResearchTool:
    """
    Outil de recherche Web utilisé
    par le Researcher.

    Le LLM ne peut pas contourner
    les permissions :
    elles sont vérifiées ici,
    avant chaque action.
    """

    USER_AGENT = (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/152.0 Safari/537.36 "
        "Agent-OS/2.3"
    )

    def __init__(
        self,
        permissions: PermissionEngine,
        timeout: float = 8.0,
        max_download_bytes: int = (
            1_000_000
        ),
    ) -> None:

        self.permissions = (
            permissions
        )

        self.timeout = (
            timeout
        )

        self.max_download_bytes = (
            max_download_bytes
        )

    # ========================================================
    # PERMISSIONS
    # ========================================================

    def _require_allowed(
        self,
        action: str,
    ) -> None:

        permission = (
            self.permissions.check(
                action
            )
        )

        if (
            permission.result
            == PermissionResult.ALLOWED
        ):

            return

        raise (
            WebToolPermissionError(
                (
                    f"Action '{action}' "
                    f"refusée : "
                    f"{permission.reason}"
                )
            )
        )

    # ========================================================
    # SEARCH
    # ========================================================

    def search(
        self,
        query: str,
        max_results: int = 6,
    ) -> list[
        WebSource
    ]:

        self._require_allowed(
            "web_search"
        )

        query = (
            query.strip()
        )

        if not query:

            raise WebToolError(
                "La requête Web est vide."
            )

        try:

            raw_results = (
                DDGS(
                    timeout=int(
                        max(
                            self.timeout,
                            5,
                        )
                    )
                )
                .text(
                    query=query,
                    region="fr-fr",
                    safesearch="moderate",
                    max_results=(
                        max_results
                    ),
                    backend="auto",
                )
            )

        except Exception as exc:

            raise WebToolError(
                (
                    "La recherche Web "
                    "a échoué : "
                    f"{exc}"
                )
            ) from exc

        sources = []

        for raw in (
            raw_results
            or []
        ):

            if not isinstance(
                raw,
                dict,
            ):

                continue

            url = str(
                raw.get(
                    "href",
                    "",
                )
            ).strip()

            if not url:

                continue

            sources.append(
                WebSource(
                    index=(
                        len(sources)
                        + 1
                    ),
                    title=(
                        str(
                            raw.get(
                                "title",
                                "",
                            )
                        ).strip()
                        or url
                    ),
                    url=url,
                    snippet=str(
                        raw.get(
                            "body",
                            "",
                        )
                    ).strip(),
                )
            )

        return sources

    # ========================================================
    # URL SECURITY
    # ========================================================

    @staticmethod
    def _is_safe_remote_url(
        url: str,
    ) -> bool:

        try:

            parsed = (
                urlparse(
                    url
                )
            )

        except Exception:

            return False

        if (
            parsed.scheme
            not in {
                "http",
                "https",
            }
        ):

            return False

        hostname = (
            parsed.hostname
        )

        if not hostname:

            return False

        if (
            hostname.lower()
            in {
                "localhost",
                "localhost.localdomain",
            }
        ):

            return False

        try:

            addresses = (
                socket.getaddrinfo(
                    hostname,
                    parsed.port
                    or (
                        443
                        if (
                            parsed.scheme
                            == "https"
                        )
                        else 80
                    ),
                    type=socket.SOCK_STREAM,
                )
            )

        except OSError:

            return False

        if not addresses:

            return False

        for address_info in (
            addresses
        ):

            ip_text = (
                address_info[4][0]
            )

            try:

                ip = (
                    ipaddress.ip_address(
                        ip_text
                    )
                )

            except ValueError:

                return False

            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):

                return False

        return True

    # ========================================================
    # FETCH
    # ========================================================

    def fetch(
        self,
        source: WebSource,
    ) -> WebSource:

        self._require_allowed(
            "web_fetch"
        )

        if not (
            self._is_safe_remote_url(
                source.url
            )
        ):

            source.error = (
                "URL refusée "
                "par la protection réseau."
            )

            return source

        request = Request(
            source.url,
            headers={
                "User-Agent": (
                    self.USER_AGENT
                ),
                "Accept": (
                    "text/html,"
                    "application/xhtml+xml,"
                    "text/plain;q=0.9,*/*;q=0.1"
                ),
                "Accept-Language": (
                    "fr-FR,fr;q=0.9,"
                    "en;q=0.7"
                ),
            },
        )

        try:

            with urlopen(
                request,
                timeout=(
                    self.timeout
                ),
            ) as response:

                content_type = (
                    response.headers.get(
                        "Content-Type",
                        "",
                    )
                    .lower()
                )

                if (
                    "text/html"
                    not in content_type
                    and "text/plain"
                    not in content_type
                    and "application/xhtml+xml"
                    not in content_type
                ):

                    source.error = (
                        "Type de contenu "
                        "non textuel."
                    )

                    return source

                raw = (
                    response.read(
                        self.max_download_bytes
                        + 1
                    )
                )

                if (
                    len(raw)
                    > self.max_download_bytes
                ):

                    raw = raw[
                        :self.max_download_bytes
                    ]

                charset = (
                    response.headers
                    .get_content_charset()
                    or "utf-8"
                )

        except Exception as exc:

            source.error = (
                f"Lecture impossible : {exc}"
            )

            return source

        try:

            decoded = (
                raw.decode(
                    charset,
                    errors="replace",
                )
            )

        except LookupError:

            decoded = (
                raw.decode(
                    "utf-8",
                    errors="replace",
                )
            )

        if (
            "text/plain"
            in content_type
        ):

            text = decoded

        else:

            parser = (
                _HTMLTextExtractor()
            )

            try:

                parser.feed(
                    decoded
                )

                text = (
                    parser.get_text()
                )

            except Exception as exc:

                source.error = (
                    "Extraction HTML "
                    f"impossible : {exc}"
                )

                return source

        text = (
            text.strip()
        )

        if not text:

            source.error = (
                "Page sans texte "
                "exploitable."
            )

            return source

        source.content = text

        source.fetched = True

        source.error = None

        return source

    # ========================================================
    # FULL RESEARCH
    # ========================================================

    def research(
        self,
        query: str,
        max_results: int = 6,
        max_pages: int = 3,
    ) -> WebResearchResult:

        sources = (
            self.search(
                query=query,
                max_results=(
                    max_results
                ),
            )
        )

        pages_to_fetch = (
            min(
                max_pages,
                len(sources),
            )
        )

        for index in range(
            pages_to_fetch
        ):

            self.fetch(
                sources[index]
            )

        return WebResearchResult(
            query=query,
            sources=sources,
        )