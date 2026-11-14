"""lib_alpaca — las noticias de Alpaca (Benzinga) con la llave de la persona. Solo biblioteca estándar. No es una acción.

Es la segunda salida de red de Pilota (la primera es Binance, en `lib_datos`). Sirve para leer noticias de BTC y ETH con
su hora exacta: no compra, no vende y no toca ninguna cuenta.

Lo que no se negocia aquí:
- **Un solo destino y una sola ruta**: `https://data.alpaca.markets/v1beta1/news`, sin redirecciones y sin los proxies del
  entorno. La respuesta tiene que venir de ese mismo lugar.
- **La llave vive en el llavero** (`lib_llavero`, servicio `SERVICIO`), nunca en un archivo ni en el registro. Antes de
  guardarla se prueba con un pedido de verdad: una llave que Alpaca no acepta no se guarda.
- **Nada de lo que responde Alpaca llega a la pantalla como error**: los fallos son códigos (`MOTIVOS`) que la pantalla
  traduce. Los titulares se pasan como datos (la pantalla los escapa) y con un largo máximo.
- `pedir` se reemplaza en las pruebas: así se prueba sin salir a la red.
"""
import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import lib_llavero

DOMINIO = "data.alpaca.markets"
RUTA = "/v1beta1/news"
SERVICIO = "app.pilota.alpaca"
#: La Key ID de Alpaca: letras mayúsculas y números. La Secret Key: letras y números.
FORMATO_LLAVE = re.compile(r"^[A-Z0-9]{16,64}$")
FORMATO_SECRETO = re.compile(r"^[A-Za-z0-9]{20,128}$")
FORMATOS = (FORMATO_LLAVE, FORMATO_SECRETO)
SIMBOLOS = ("BTCUSD", "ETHUSD")
TIEMPO = 20
MAXIMO = 2_000_000
TITULAR = 200
DIA_MS = 86_400_000
MOTIVOS = ("formato", "sin_llavero", "rechazada", "sin_red", "respuesta", "no_guardo")


class Falla(Exception):
    def __init__(self, motivo):
        super().__init__(motivo)
        self.motivo = motivo


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SinRedirecciones())


def _pedir(parametros, llave, secreto):
    url = f"https://{DOMINIO}{RUTA}?" + urllib.parse.urlencode(parametros)
    pedido = urllib.request.Request(url, method="GET", headers={
        "Accept": "application/json", "User-Agent": "Pilota", "APCA-API-KEY-ID": llave, "APCA-API-SECRET-KEY": secreto})
    try:
        with _abridor.open(pedido, timeout=TIEMPO) as r:
            if r.geturl().split("?")[0] != f"https://{DOMINIO}{RUTA}":
                raise Falla("respuesta")
            crudo = r.read(MAXIMO + 1)
    except urllib.error.HTTPError as e:
        raise Falla("rechazada" if e.code in (401, 403) else "respuesta") from None
    except (urllib.error.URLError, OSError):
        raise Falla("sin_red") from None
    if len(crudo) > MAXIMO:
        raise Falla("respuesta")
    try:
        return json.loads(crudo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Falla("respuesta") from None


pedir = _pedir


def _noticia(x):
    """Una noticia revisada: id, hora en ms, titular (cortado) y los símbolos que conocemos. `None` si no se entiende."""
    try:
        ms = int(datetime.datetime.fromisoformat(str(x["created_at"]).replace("Z", "+00:00")).timestamp() * 1000)
        return {"id": int(x["id"]), "ms": ms, "titular": str(x.get("headline") or "")[:TITULAR],
                "simbolos": [s for s in x.get("symbols") or [] if s in SIMBOLOS]}
    except (KeyError, TypeError, ValueError):
        return None


def noticias(llave, secreto, desde_ms=None, limite=50):
    """Las últimas noticias de BTC y ETH (la más nueva primero), revisadas."""
    q = {"symbols": ",".join(SIMBOLOS), "limit": max(1, min(50, int(limite))), "sort": "desc", "include_content": "false"}
    if desde_ms:
        q["start"] = datetime.datetime.fromtimestamp(desde_ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    d = pedir(q, llave, secreto)
    if not isinstance(d, dict) or not isinstance(d.get("news"), list):
        raise Falla("respuesta")
    return [n for n in (_noticia(x) for x in d["news"]) if n]


def guardada():
    return lib_llavero.leer(SERVICIO, FORMATOS) if lib_llavero.disponible() else None


def estado():
    llave = guardada()
    return {"formato": 1, "llavero": lib_llavero.disponible(), "conectado": llave is not None,
            "pista": lib_llavero.pista(llave[0], FORMATO_LLAVE) if llave else ""}


def conectar(llave, secreto):
    """Prueba la llave con un pedido de verdad y, si Alpaca la acepta, la guarda en el llavero."""
    llave, secreto = (llave or "").strip(), (secreto or "").strip()
    if not (lib_llavero.valida(llave, FORMATO_LLAVE) and lib_llavero.valida(secreto, FORMATO_SECRETO)):
        return {**estado(), "ok": False, "motivo": "formato"}
    if not lib_llavero.disponible():
        return {**estado(), "ok": False, "motivo": "sin_llavero"}
    try:
        ultimas = noticias(llave, secreto, limite=5)
    except Falla as e:
        return {**estado(), "ok": False, "motivo": e.motivo}
    try:
        lib_llavero.guardar(llave, secreto, SERVICIO, FORMATOS)
    except lib_llavero.Llavero:
        return {**estado(), "ok": False, "motivo": "no_guardo"}
    return {**estado(), "ok": True, "ultimas": ultimas}


def revisar():
    """Prueba la llave guardada (la pantalla lo pide al abrir Ajustes)."""
    llave = guardada()
    if not llave:
        return {**estado(), "ok": False}
    try:
        return {**estado(), "ok": True, "ultimas": noticias(*llave, limite=5)}
    except Falla as e:
        return {**estado(), "ok": False, "motivo": e.motivo}


def desconectar():
    lib_llavero.borrar(SERVICIO, FORMATOS)
    return {**estado(), "ok": True}


# ── Las noticias al día, en disco (las trae el flujo en vivo; la pantalla y las decisiones leen de aquí) ─────────────
GUARDAR_DIAS = 7
GUARDAR_MAXIMO = 500
TRAER_CADA_S = 60


def ruta():
    import nucleo
    return os.path.join(nucleo.carpeta_privada(os.path.join(nucleo.carpeta_datos(), "noticias")), "alpaca.json")


def guardadas():
    try:
        with open(ruta(), encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {"formato": 1, "noticias": [], "traido_ms": 0}
    lista = [n for n in (d.get("noticias") or []) if isinstance(n, dict) and isinstance(n.get("ms"), int)
             and isinstance(n.get("titular"), str) and isinstance(n.get("id"), int)]
    return {"formato": 1, "noticias": lista, "traido_ms": int(d.get("traido_ms") or 0), "motivo": d.get("motivo")}


def al_dia(ms):
    """Trae las noticias nuevas desde la última guardada y las deja en disco (las de los últimos `GUARDAR_DIAS`). Sin
    llave no hace nada. Un fallo queda como código (`motivo`) y no borra lo que ya había."""
    llave = guardada()
    if not llave:
        return None
    d = guardadas()
    desde = max([n["ms"] for n in d["noticias"]] or [ms - DIA_MS])
    try:
        nuevas = noticias(*llave, desde_ms=desde, limite=50)
        motivo = None
    except Falla as e:
        nuevas, motivo = [], e.motivo
    por_id = {n["id"]: n for n in d["noticias"]}
    for n in nuevas:
        por_id[n["id"]] = {**n, "tipos": tipos_de(n["titular"])}
    lista = sorted((n for n in por_id.values() if n["ms"] >= ms - GUARDAR_DIAS * DIA_MS), key=lambda n: n["ms"])
    salida = {"formato": 1, "noticias": lista[-GUARDAR_MAXIMO:], "traido_ms": ms if motivo is None else d["traido_ms"],
              "motivo": motivo}
    temporal = ruta() + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(salida, f, ensure_ascii=False)
    os.replace(temporal, ruta())
    return salida


#: De qué habla una noticia, por palabras del titular (en inglés: Benzinga escribe en inglés).
TIPOS = {
    "trump": ("trump",), "musk": ("musk", "tesla"), "fed": ("fed ", "powell", "warsh", "rate cut", "rate hike", "fomc"),
    "regulacion": ("sec ", "regulat", "lawsuit", "clarity act", "ban "), "etf": ("etf",),
    "hackeo": ("hack", "exploit", "stolen"), "exchange": ("binance", "coinbase"), "aranceles": ("tariff",),
}


def tipos_de(titular):
    t = (titular or "").lower()
    return [k for k, palabras in TIPOS.items() if any(p in t for p in palabras)]


def recientes(ms, horas=24):
    """Lo que lee la pantalla: las noticias de las últimas `horas`, la más nueva primero, sin tocar la red."""
    d = guardadas()
    lista = [n for n in d["noticias"] if ms - horas * 3_600_000 <= n["ms"] <= ms]
    return {"conectado": guardada() is not None, "noticias": lista[::-1][:8], "traido_ms": d["traido_ms"],
            "motivo": d.get("motivo"), "horas": horas}
