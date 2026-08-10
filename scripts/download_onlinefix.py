"""
Descarga onlinefix.json usando FlareSolverr.

SETUP LOCAL:
  1. Instala Docker Desktop
  2. docker run -d --name flaresolverr -p 8191:8191 ghcr.io/flaresolverr/flaresolverr:latest
  3. python scripts/download_onlinefix.py
"""

import json
import re
import sys
import urllib.error
import urllib.request

URL = "https://hydralinks.cloud/sources/onlinefix.json"
OUTPUT_FILE = "public/onlinefix.json"
FLARESOLVERR_URL = "http://localhost:8191/v1"
FLARESOLVERR_HEALTH_URL = "http://localhost:8191/health"


def check_flaresolverr():
    try:
        req = urllib.request.urlopen(FLARESOLVERR_HEALTH_URL, timeout=5)
        return req.status == 200
    except Exception:
        return False


def post_json(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
            message = parsed.get("message") or parsed.get("error") or body
        except Exception:
            message = body or str(error)
        raise RuntimeError(f"FlareSolverr HTTP {error.code}: {message}") from error


def extract_json(body):
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass

    match = re.search(r"<pre[^>]*>(.*?)</pre>", body, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    raise ValueError("No se encontró JSON válido en la respuesta")


def count_entries(data):
    if isinstance(data, dict):
        for key in ("downloads", "games", "sources"):
            if key in data and hasattr(data[key], "__len__"):
                return len(data[key])
        return len(data)
    return len(data)


def normalize_output(data):
    if isinstance(data, dict) and isinstance(data.get("downloads"), list):
        return {
            "name": "OnlineFix",
            "downloads": data["downloads"],
        }

    if isinstance(data, dict):
        for key in ("games", "sources", "items", "data"):
            if isinstance(data.get(key), list):
                return {
                    "name": "OnlineFix",
                    "downloads": data[key],
                }

    if isinstance(data, list):
        return {
            "name": "OnlineFix",
            "downloads": data,
        }

    raise ValueError("El JSON descargado no tiene una estructura reconocible para normalizarlo.")


def download():
    print("=" * 58)
    print("  Descargador onlinefix.json via FlareSolverr")
    print("=" * 58)
    print()

    print("[*] Verificando FlareSolverr en localhost:8191...")
    if not check_flaresolverr():
        print("[x] FlareSolverr no está corriendo.")
        print(
            "    Ejecuta: docker run -d --name flaresolverr -p 8191:8191 "
            "ghcr.io/flaresolverr/flaresolverr:latest"
        )
        sys.exit(1)

    print("[ok] FlareSolverr detectado")
    print(f"[*] Solicitando: {URL}")
    print("[*] Esperando respuesta (puede tardar ~15-30 segundos)...")
    print()

    try:
        result = post_json(
            FLARESOLVERR_URL,
            {
                "cmd": "request.get",
                "url": URL,
                "maxTimeout": 60000,
            },
        )
    except Exception as error:
        print(f"[x] FlareSolverr devolvió un error: {error}")
        sys.exit(1)

    status = result.get("status")
    print(f"[*] FlareSolverr status: {status}")

    if status != "ok":
        print(f"[x] Error: {result.get('message', 'desconocido')}")
        sys.exit(1)

    solution = result.get("solution", {})
    http_code = solution.get("status")
    body = solution.get("response", "")

    print(f"[*] HTTP status de la página: {http_code}")

    if http_code != 200:
        print(f"[x] La página devolvió HTTP {http_code}")
        sys.exit(1)

    try:
        data = extract_json(body)
    except Exception as error:
        print(f"[x] No se pudo extraer el JSON: {error}")
        sys.exit(1)

    try:
        normalized = normalize_output(data)
    except Exception as error:
        print(f"[x] No se pudo normalizar el JSON: {error}")
        sys.exit(1)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as file_handle:
        json.dump(normalized, file_handle, ensure_ascii=False, indent=2)

    print(f"[ok] JSON guardado en: {OUTPUT_FILE}")
    print(f"[ok] Entradas encontradas: {count_entries(normalized)}")


if __name__ == "__main__":
    download()
