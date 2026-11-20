import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Query
from youtube_transcript_api import YouTubeTranscriptApi

app = FastAPI(
    title="Servidor Python - YouTube e HTTPS",
    description="API para obter legendas do YouTube e consultar páginas HTTPS.",
    version="1.0.0",
)

YOUTUBE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MAX_HTML_BYTES = 1_000_000
TIMEOUT = httpx.Timeout(20.0, connect=10.0)


def extract_video_id(value: str) -> str:
    value = value.strip()
    if YOUTUBE_ID_RE.fullmatch(value):
        return value

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()

    if host in ("youtu.be", "www.youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
    elif host.endswith("youtube.com"):
        if parsed.path == "/watch":
            from urllib.parse import parse_qs
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        else:
            parts = [part for part in parsed.path.split("/") if part]
            video_id = parts[1] if len(parts) >= 2 and parts[0] in ("embed", "shorts", "live") else ""
    else:
        video_id = ""

    if not YOUTUBE_ID_RE.fullmatch(video_id):
        raise HTTPException(status_code=400, detail="URL ou ID de vídeo do YouTube inválido.")
    return video_id


@app.get("/")
async def home():
    return {
        "service": "servidor-python-youtube",
        "status": "online",
        "docs": "/docs",
        "endpoints": ["/youtube/transcript", "/web/fetch", "/health"],
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/youtube/transcript")
async def youtube_transcript(
    url: str = Query(..., description="URL ou ID do vídeo do YouTube"),
    languages: str = Query("pt,pt-BR,en", description="Idiomas em ordem de preferência, separados por vírgula"),
):
    video_id = extract_video_id(url)
    language_list = [lang.strip() for lang in languages.split(",") if lang.strip()]

    try:
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id, languages=language_list)
        segments = [
            {
                "start": item.start,
                "duration": item.duration,
                "text": item.text,
            }
            for item in transcript
        ]
        return {
            "video_id": video_id,
            "language": getattr(transcript, "language_code", None),
            "is_generated": getattr(transcript, "is_generated", None),
            "text": " ".join(item["text"] for item in segments),
            "segments": segments,
        }
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail="Não foi possível obter a legenda. O vídeo pode não ter legendas acessíveis, "
                   "ou o YouTube pode ter bloqueado a consulta. Detalhe: " + str(exc)[:300],
        )


def validate_public_https_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Somente URLs HTTPS são permitidas.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="URL inválida.")

    host = parsed.hostname.rstrip(".")
    if host.lower() in ("localhost",) or host.lower().endswith(".localhost"):
        raise HTTPException(status_code=403, detail="Acesso a endereços locais bloqueado.")

    try:
        addresses = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise HTTPException(status_code=400, detail="Não foi possível resolver o domínio.")

    if not addresses:
        raise HTTPException(status_code=400, detail="Domínio sem endereço IP.")

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise HTTPException(status_code=403, detail="Acesso a IPs não públicos bloqueado.")
    return url


@app.get("/web/fetch")
async def web_fetch(url: str = Query(..., description="URL HTTPS da página a consultar")):
    current_url = validate_public_https_url(url)
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PythonFetchAPI/1.0)"}

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=False,
            headers=headers,
        ) as client:
            response = None
            for _ in range(5):
                current_url = validate_public_https_url(current_url)
                response = await client.get(current_url)
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                location = response.headers.get("location")
                if not location:
                    break
                current_url = str(response.url.join(location))
            else:
                raise HTTPException(status_code=502, detail="Muitos redirecionamentos.")

            content = response.content[:MAX_HTML_BYTES]
            encoding = response.encoding or "utf-8"
            html = content.decode(encoding, errors="replace")

            title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
            title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else None

            return {
                "requested_url": url,
                "final_url": str(response.url),
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "title": title,
                "truncated": len(response.content) > MAX_HTML_BYTES,
                "html": html,
            }
    except HTTPException:
        raise
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail="Falha na requisição HTTPS: " + str(exc)[:250])
