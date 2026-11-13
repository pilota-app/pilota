"""lib_datos — los datos de mercado de Pilota: velas cerradas de Binance, dónde se guardan y qué les falta. Solo biblioteca estándar.

No es una acción (nadie la corre sola): la usa bin/velas.py y, más adelante, el resto del motor.

Lo que no se negocia aquí:
- **Solo velas cerradas.** La vela en curso no se guarda nunca: decidir con una vela a medio hacer es decidir con datos que
  todavía pueden cambiar.
- **Solo Binance, solo https, sin redirecciones y sin proxies del entorno.** Mientras Pilota no tenga la pieza «Red», el candado
  vive en `pedir_api`: el dominio y las rutas son una lista blanca y el redirigir es un error, no un camino.
- **Los límites de la API se respetan.** Ante 429 o 418 se espera lo que pide Binance (`Retry-After`) y se reintenta; igual ante
  un 5xx o un corte de red.
- **Si falta historia, no se opera.** `estado()` dice qué serie falta y por qué, y `escribir_estado()` lo deja escrito.

Dónde vive todo (en los datos de la app, nunca en la carpeta de la persona): `<datos>/mercado/`
- `velas/<PAR>-<TEMPORALIDAD>.json`: `{"formato": 1, "par", "temporalidad", "paso_ms", "guardado",
  "velas": [[apertura_ms, abre, alto, bajo, cierra, volumen], …]}`, ordenadas y sin repetidas.
- `estado.json`: lo que devuelve `estado()`, con la última descarga.
- `muestras/<AAAA-MM>.jsonl`: una línea por muestra del mercado (`guardar_muestra`). Binance no da libro histórico: estas
  muestras son las únicas que Pilota va a tener, así que se guardan desde el primer día y no se reescriben nunca.
"""
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import nucleo

#: Los pares que se operan (contra FDUSD) y los que dan más historia y el filtro de BTC (contra USDT).
PARES = ("BTCFDUSD", "ETHFDUSD", "BTCUSDT", "ETHUSDT")
#: Los dos que se compran: solo de ellos se guardan velas de 1 m y muestras del libro.
PARES_OPERADOS = ("BTCFDUSD", "ETHFDUSD")
#: Las monedas que mira el robot en prueba (`lib_universo`), todas contra USDT. Sus series se guardan igual que las de
#: siempre (1 h, 4 h, 1 d y 1 m), pero no entran en el estado de los datos ni en el historial de los 3 años: las prepara
#: `lib_universo` y las mantiene al día el flujo en vivo.
UNIVERSO = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "TRXUSDT", "DOGEUSDT")
CONOCIDOS = PARES + tuple(p for p in UNIVERSO if p not in PARES)
TEMPORALIDADES = ("1h", "4h", "1d")
#: El minuto va aparte: solo de los pares que se operan y solo los últimos días (el ejecutor de prueba y reconciliar).
MINUTO = "1m"
PASO_MS = {MINUTO: 60_000, "5m": 300_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}
#: «5m» no se baja ni se guarda: se arma con las de 1 m (lib_perfiles.agrupar), para el perfil más rápido.
DIA_MS = 86_400_000
#: Lo primero que se baja para poder calcular: 90 días. Los 3 años vienen después, en segundo plano.
DIAS_MINIMOS = 90
#: El historial largo (bin/historial.py): 3 años para el backtest y la calibración.
DIAS_HISTORIAL = 1095
#: La ventana de velas de 1 m que se guarda (bin/muestreo.py): se corre con los días, nunca crece más que esto.
DIAS_MINUTOS = 30

DOMINIO = "api.binance.com"
RUTAS = ("/api/v3/time", "/api/v3/klines", "/api/v3/exchangeInfo", "/api/v3/ticker/bookTicker", "/api/v3/trades")
VELAS_POR_PEDIDO = 1000          # el máximo que da Binance en un pedido de velas
TRADES_POR_MUESTRA = 20          # los últimos trades que se guardan en cada muestra
ESPERA_ENTRE_PEDIDOS = 0.25      # un respiro fijo entre pedidos: así no se llega al límite por apurado
ESPERA_MAXIMA = 60               # nunca se duerme más que esto de una vez
INTENTOS = 5
TIEMPO_LIMITE = 20               # segundos por pedido
MAXIMO_RESPUESTA = 8 * 1024 * 1024
MAXIMO_ARCHIVO = 64 * 1024 * 1024
MAXIMO_HUECOS = 20               # en el informe: los primeros, para no escribir un archivo inmenso


class Limitado(Exception):
    """Binance pidió esperar (429 demasiados pedidos, 418 IP bloqueada un rato)."""

    def __init__(self, segundos, codigo=429):
        super().__init__(f"Binance pidió esperar {segundos} s.")
        self.segundos = segundos
        self.codigo = codigo


class Temporal(Exception):
    """Algo pasajero: la red, un 5xx de Binance. Se vuelve a intentar."""


class Respuesta(Exception):
    """Binance respondió algo que no entendemos: mejor no calcular nada con eso."""


# ── Hablar con Binance ───────────────────────────────────────────────────────────────────────────────────────────────────────

def url_api(ruta, parametros=None):
    """La URL de un pedido a la API pública de Binance. Solo las rutas de la lista blanca: nada que venga de afuera arma una URL."""
    if ruta not in RUTAS:
        raise ValueError(f"Ruta de Binance no permitida: {ruta!r}")
    consulta = urllib.parse.urlencode(parametros or {})
    return f"https://{DOMINIO}{ruta}" + (f"?{consulta}" if consulta else "")


class _SinRedirecciones(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Respuesta(f"Binance redirigió el pedido ({code}): no lo sigo.")


#: Sin ProxyHandler del entorno (ningún http_proxy nos cambia el destino) y sin redirecciones.
_abridor = urllib.request.build_opener(urllib.request.ProxyHandler({}), _SinRedirecciones())


def _segundos_de(cabeceras, defecto):
    try:
        return max(1, min(ESPERA_MAXIMA, int(float(cabeceras.get("Retry-After", "")))))
    except (TypeError, ValueError):
        return defecto


def pedir_api(ruta, parametros=None):
    """Un GET a la API pública de Binance, una sola vez. Los reintentos los pone `Binance.obtener`."""
    pedido = urllib.request.Request(url_api(ruta, parametros), method="GET",
                                    headers={"Accept": "application/json", "User-Agent": "Pilota"})
    try:
        with _abridor.open(pedido, timeout=TIEMPO_LIMITE) as r:
            if r.geturl().split("?")[0] != f"https://{DOMINIO}{ruta}":
                raise Respuesta("La respuesta no viene de Binance.")
            crudo = r.read(MAXIMO_RESPUESTA + 1)
    except urllib.error.HTTPError as e:
        if e.code in (429, 418):
            raise Limitado(_segundos_de(e.headers, 30 if e.code == 429 else 60), e.code) from None
        if e.code >= 500:
            raise Temporal(f"Binance respondió {e.code}.") from None
        raise Respuesta(f"Binance respondió {e.code}.") from None
    except (urllib.error.URLError, OSError) as e:
        raise Temporal(f"No pude hablar con Binance: {e.__class__.__name__}") from None
    if len(crudo) > MAXIMO_RESPUESTA:
        raise Respuesta("La respuesta de Binance es demasiado grande.")
    try:
        return json.loads(crudo.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Respuesta("La respuesta de Binance no es un JSON válido.") from None


class Binance:
    """Lo mínimo de la API pública que Pilota necesita, con los límites respetados.

    `pedir` y `dormir` se reemplazan en las pruebas: así se prueba la espera sin tocar la red."""

    def __init__(self, pedir=None, dormir=time.sleep):
        self.pedir = pedir or pedir_api
        self.dormir = dormir
        self.pedidos = 0
        self.esperas = 0

    def obtener(self, ruta, parametros=None):
        ultimo = None
        for intento in range(INTENTOS):
            if self.pedidos:
                self.dormir(ESPERA_ENTRE_PEDIDOS)
            self.pedidos += 1
            try:
                return self.pedir(ruta, parametros)
            except Limitado as e:
                ultimo, espera = e, min(ESPERA_MAXIMA, max(1, e.segundos))
            except Temporal as e:
                ultimo, espera = e, min(ESPERA_MAXIMA, 2 ** intento)
            if intento < INTENTOS - 1:
                self.esperas += 1
                self.dormir(espera)
        raise ultimo

    def ahora_ms(self):
        """La hora de Binance: la que dice qué vela está cerrada (el reloj del computador puede andar corrido)."""
        d = self.obtener("/api/v3/time")
        try:
            ms = int(d["serverTime"])
        except (KeyError, TypeError, ValueError):
            raise Respuesta("Binance no dio su hora.") from None
        if ms < 1_000_000_000_000:
            raise Respuesta("La hora de Binance no tiene sentido.")
        return ms

    def info_pares(self, pares):
        """Los símbolos de `pares` como los da exchangeInfo: sus filtros vigentes (tick, paso de cantidad, mínimos) y si
        aceptan protección automática. Los nombres salen de PARES o del universo, nunca de afuera."""
        for par in pares:
            if par not in CONOCIDOS:
                raise ValueError(f"No conozco ese par: {par!r}")
        d = self.obtener("/api/v3/exchangeInfo", {"symbols": json.dumps(list(pares), separators=(",", ":"))})
        if not isinstance(d, dict) or not isinstance(d.get("symbols"), list):
            raise Respuesta("Binance no devolvió los filtros de los pares.")
        return d["symbols"]

    def klines(self, par, temporalidad, desde_ms):
        filas = self.obtener("/api/v3/klines", {"symbol": par, "interval": temporalidad,
                                                "startTime": int(desde_ms), "limit": VELAS_POR_PEDIDO})
        if not isinstance(filas, list):
            raise Respuesta("Binance no devolvió una lista de velas.")
        return filas

    def libro(self, par):
        """El mejor precio de compra y el mejor de venta, ahora mismo. Binance no da libro histórico: esto es lo que Pilota
        guarda cada 5 minutos para armar más adelante su modelo de spread y de no llenado."""
        if par not in PARES:
            raise ValueError(f"No conozco ese par: {par!r}")
        d = self.obtener("/api/v3/ticker/bookTicker", {"symbol": par})
        if not isinstance(d, dict) or d.get("symbol") != par:
            raise Respuesta("Binance no devolvió el libro de ese par.")
        try:
            compra, compra_cantidad = numero(d["bidPrice"]), numero(d["bidQty"], positivo=False)
            venta, venta_cantidad = numero(d["askPrice"]), numero(d["askQty"], positivo=False)
        except (KeyError, TypeError, ValueError):
            raise Respuesta("Binance devolvió un libro que no entiendo.") from None
        if venta < compra:
            raise Respuesta("Binance devolvió un libro imposible: la venta por debajo de la compra.")
        diferencia, medio = venta - compra, (venta + compra) / 2
        # El spread es un precio y va en el tick del par: 8 decimales es más fino que cualquier tick, así que ahí redondear
        # solo saca el ruido del float. La diferencia **relativa** es otra cosa: en un par líquido es del orden de 1e-6, y
        # redondearla la borra (3,16e-06 en vez de 3,157886426614667e-06). Es la base del modelo de spread y de no llenado
        # del backtest, así que se guarda entera; el redondeo es solo para mostrarla (`porcentaje()` en ui/app.js).
        return {"compra": compra, "compra_cantidad": compra_cantidad, "venta": venta, "venta_cantidad": venta_cantidad,
                "spread": round(diferencia, 8), "spread_relativo": diferencia / medio}

    def trades(self, par, cuantos=TRADES_POR_MUESTRA):
        """Los últimos trades: `[[ms, precio, cantidad, compra], …]`. `compra` es cierto cuando el que apuró fue el comprador
        (Binance lo dice al revés, con `isBuyerMaker`): con eso se ve de qué lado llegan las órdenes."""
        if par not in PARES:
            raise ValueError(f"No conozco ese par: {par!r}")
        cuantos = max(1, min(VELAS_POR_PEDIDO, int(cuantos)))
        filas = self.obtener("/api/v3/trades", {"symbol": par, "limit": cuantos})
        if not isinstance(filas, list):
            raise Respuesta("Binance no devolvió una lista de trades.")
        r = []
        for f in filas[-cuantos:]:
            if not isinstance(f, dict):
                raise Respuesta("Binance devolvió un trade con otra forma.")
            try:
                ms, precio, cantidad = int(f["time"]), numero(f["price"]), numero(f["qty"], positivo=False)
            except (KeyError, TypeError, ValueError):
                raise Respuesta("Binance devolvió un trade que no entiendo.") from None
            if ms <= 0:
                raise Respuesta("Binance devolvió un trade sin hora.")
            r.append([ms, precio, cantidad, f.get("isBuyerMaker") is not True])
        return r


# ── Velas guardadas ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def ahora_local_ms():
    return int(time.time() * 1000)


def iso(ms):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ms / 1000))


def carpeta_mercado():
    return nucleo.carpeta_privada(os.path.join(nucleo.carpeta_datos(), "mercado"))


def serie_valida(par, temporalidad):
    """Las series que Pilota guarda: las 12 de siempre (4 pares × 1 h, 4 h, 1 d), la de 1 m de los pares que se operan, y las
    del universo del robot (1 h, 4 h, 1 d y 1 m)."""
    if par in UNIVERSO:
        return temporalidad in TEMPORALIDADES or temporalidad == MINUTO
    return par in PARES and (temporalidad in TEMPORALIDADES or (temporalidad == MINUTO and par in PARES_OPERADOS))


def ruta_serie(par, temporalidad):
    if not serie_valida(par, temporalidad):
        raise ValueError(f"No conozco esa serie: {par!r} {temporalidad!r}")
    return os.path.join(nucleo.carpeta_privada(os.path.join(carpeta_mercado(), "velas")), f"{par}-{temporalidad}.json")


def ruta_estado():
    return os.path.join(carpeta_mercado(), "estado.json")


def numero(x, positivo=True):
    """Un número de Binance (vienen como texto): finito y no negativo. Lo usan las velas y los filtros de los pares."""
    v = float(x)
    if not math.isfinite(v) or v < 0 or (positivo and v == 0):
        raise Respuesta("Binance devolvió un precio que no entiendo.")
    return v


def vela_de(fila, paso):
    """Una fila de Binance → [apertura_ms, abre, alto, bajo, cierra, volumen]. El cierre va implícito en el paso."""
    if not isinstance(fila, (list, tuple)) or len(fila) < 6:
        raise Respuesta("Binance devolvió una vela con otra forma.")
    try:
        apertura = int(fila[0])
    except (TypeError, ValueError):
        raise Respuesta("Binance devolvió una vela sin hora.") from None
    if apertura <= 0 or apertura % paso:
        raise Respuesta("Binance devolvió una vela fuera de hora.")
    try:
        abre, alto, bajo, cierra = (numero(fila[i]) for i in (1, 2, 3, 4))
        volumen = numero(fila[5], positivo=False)
    except ValueError:
        raise Respuesta("Binance devolvió una vela que no entiendo.") from None
    if not (bajo <= abre <= alto and bajo <= cierra <= alto):
        raise Respuesta("Binance devolvió una vela imposible: el máximo y el mínimo no cuadran.")
    return [apertura, abre, alto, bajo, cierra, volumen]


def leer_serie(par, temporalidad):
    """Las velas guardadas, ordenadas y sin repetidas. Si el archivo no está o no se entiende: ninguna (se vuelven a bajar)."""
    paso = PASO_MS[temporalidad]
    d = nucleo.leer_json(ruta_serie(par, temporalidad), {}, maximo=MAXIMO_ARCHIVO)
    if not isinstance(d, dict) or d.get("formato") != 1 or not isinstance(d.get("velas"), list):
        return []
    buenas = {}
    for v in d["velas"]:
        if not isinstance(v, list) or len(v) != 6 or not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v):
            return []
        apertura = int(v[0])
        if apertura <= 0 or apertura % paso:
            return []
        buenas[apertura] = [apertura, float(v[1]), float(v[2]), float(v[3]), float(v[4]), float(v[5])]
    return [buenas[k] for k in sorted(buenas)]


def guardar_serie(par, temporalidad, velas):
    nucleo.escribir_json(ruta_serie(par, temporalidad), {
        "formato": 1, "par": par, "temporalidad": temporalidad, "paso_ms": PASO_MS[temporalidad],
        "guardado": iso(ahora_local_ms()), "velas": velas})


# ── Continuidad: ¿están todas las velas, una tras otra? ──────────────────────────────────────────────────────────────────────

def huecos(velas, temporalidad):
    """Los tramos sin velas de una serie ordenada: [{desde, hasta, faltan}]. Es la revisión «hora por hora» que se hace antes
    de calcular cualquier indicador: una serie con hoyos da medias y rupturas falsas."""
    paso = PASO_MS[temporalidad]
    encontrados = []
    for antes, despues in zip(velas, velas[1:]):
        salto = despues[0] - antes[0]
        if salto > paso and len(encontrados) < MAXIMO_HUECOS:
            encontrados.append({"desde": antes[0] + paso, "hasta": despues[0] - paso, "faltan": salto // paso - 1})
    return encontrados


def fin_continuo(velas, temporalidad, inicio):
    """Hasta dónde llega una serie ordenada sin ningún hoyo desde `inicio`: desde ahí hay que seguir pidiendo. Es lo que deja
    que «Seguir donde quedó» no vuelva a bajar lo que ya está (y que un hoyo se vuelva a pedir)."""
    paso = PASO_MS[temporalidad]
    borde = (int(inicio) // paso) * paso
    for v in velas:
        if v[0] < borde:
            continue
        if v[0] > borde:
            break
        borde = v[0] + paso
    return borde


def pedidos(desde_ms, fin_ms, temporalidad):
    """Cuántos pedidos a Binance falta hacer para cubrir [desde, fin): la unidad con la que se mide el avance y el tiempo que
    queda (cada pedido trae hasta `VELAS_POR_PEDIDO` velas y tarda más o menos lo mismo)."""
    paso = PASO_MS[temporalidad] * VELAS_POR_PEDIDO
    return max(0, -(-(int(fin_ms) - int(desde_ms)) // paso))


def estado_serie(par, temporalidad, dias=DIAS_MINIMOS, ahora_ms=None):
    """Qué tiene y qué le falta a una serie en los últimos `dias`, y por qué no se puede operar con ella."""
    paso = PASO_MS[temporalidad]
    ahora = ahora_ms or ahora_local_ms()
    fin = (ahora // paso) * paso          # la apertura de la vela en curso: el borde de lo cerrado
    inicio = fin - dias * DIA_MS
    guardadas = leer_serie(par, temporalidad)
    velas = [v for v in guardadas if inicio <= v[0] < fin]
    esperadas = dias * DIA_MS // paso
    hoyos = huecos(velas, temporalidad)
    faltan = max(0, esperadas - len(velas))
    e = {"par": par, "temporalidad": temporalidad, "velas": len(velas), "guardadas": len(guardadas),
         "esperadas": esperadas, "faltan": faltan, "huecos": hoyos,
         "desde": velas[0][0] if velas else None, "hasta": velas[-1][0] if velas else None,
         "ultima_cerrada": fin - paso}
    if not velas:
        e["estado"], e["motivo"], e["cuantas"] = "vacio", "sin_datos", esperadas
    elif hoyos:
        e["estado"], e["motivo"], e["cuantas"] = "incompleto", "huecos", len(hoyos)
    elif velas[-1][0] < fin - paso:
        e["estado"], e["motivo"], e["cuantas"] = "incompleto", "atrasado", (fin - paso - velas[-1][0]) // paso
    elif faltan:
        e["estado"], e["motivo"], e["cuantas"] = "incompleto", "faltan_velas", faltan
    else:
        e["estado"], e["motivo"], e["cuantas"] = "listo", "", 0
    return e


def estado(dias=DIAS_MINIMOS, ahora_ms=None):
    """El estado de los datos por par y temporalidad. `puede_operar` es falso mientras falte historia, con el motivo de cada serie."""
    ahora = ahora_ms or ahora_local_ms()
    series = [estado_serie(p, t, dias, ahora) for p in PARES for t in TEMPORALIDADES]
    motivos = [{"codigo": s["motivo"], "par": s["par"], "temporalidad": s["temporalidad"], "n": s["cuantas"]}
               for s in series if s["motivo"]]
    return {"formato": 1, "dias": dias, "ahora": iso(ahora), "series": series, "motivos": motivos,
            "puede_operar": not motivos, "velas": sum(s["velas"] for s in series), "descarga": ultima_descarga()}


def ultima_descarga():
    d = nucleo.leer_json(ruta_estado(), {}, maximo=MAXIMO_ARCHIVO)
    d = d.get("descarga") if isinstance(d, dict) else None
    return d if isinstance(d, dict) else None


def escribir_estado(e):
    """Deja escrito qué hay y qué falta: mientras falte historia, esto es lo que explica por qué Pilota no opera."""
    nucleo.escribir_json(ruta_estado(), e)
    return e


# ── Bajar lo que falta ───────────────────────────────────────────────────────────────────────────────────────────────────────

def bajar_serie(cliente, par, temporalidad, dias=DIAS_MINIMOS, ahora_ms=None):
    """Baja y guarda las velas cerradas que falten de una serie. Devuelve cuántas velas nuevas quedaron guardadas.

    Si lo guardado no llega al comienzo de la ventana o tiene hoyos, se baja el tramo completo de nuevo: una serie continua
    importa más que ahorrarse pedidos."""
    paso = PASO_MS[temporalidad]
    ahora = ahora_ms or cliente.ahora_ms()
    fin = (ahora // paso) * paso
    inicio = fin - dias * DIA_MS
    guardadas = leer_serie(par, temporalidad)
    velas = {v[0]: v for v in guardadas}
    en_ventana = [v for v in guardadas if inicio <= v[0] < fin]
    completa_hasta = max(velas) if velas else None
    if en_ventana and not huecos(en_ventana, temporalidad) and en_ventana[0][0] <= inicio:
        desde = completa_hasta + paso    # solo falta lo nuevo
    else:
        desde = inicio                   # falta historia o hay hoyos: el tramo entero
    nuevas = 0
    while desde < fin:
        filas = cliente.klines(par, temporalidad, desde)
        if not filas:
            break
        avance = desde
        for fila in filas:
            v = vela_de(fila, paso)
            if v[0] + paso > ahora:
                continue                 # la vela en curso no se guarda
            if v[0] not in velas:
                nuevas += 1
            velas[v[0]] = v
            avance = max(avance, v[0] + paso)
        if avance <= desde:
            break
        desde = avance
        if len(filas) < VELAS_POR_PEDIDO:
            break
    if nuevas:
        guardar_serie(par, temporalidad, [velas[k] for k in sorted(velas)])
    return nuevas


def _guardar_ventana(par, temporalidad, velas, desde=None):
    """Guarda la serie dejando fuera lo anterior a `desde` (la ventana de 1 m se corre: 30 días y nada más)."""
    quedan = [velas[k] for k in sorted(velas) if desde is None or k >= desde]
    guardar_serie(par, temporalidad, quedan)
    return {v[0]: v for v in quedan}


def bajar_tramo(cliente, par, temporalidad, desde_ms, fin_ms, detener=None, al_avanzar=None, recortar_desde=None):
    """Baja el tramo `[desde, fin)` de una serie, página por página y **guardando en cada página**: si se detiene, se corta la
    red o se cierra la app, lo bajado queda en disco y `siguiente` dice desde dónde retomar.

    `detener()` se revisa antes de cada pedido («Detener» no espera a que termine el tramo) y `al_avanzar(avance)` se llama
    después de cada página (para el latido y para el porcentaje). Devuelve `{nuevas, siguiente, paginas, cortado}`.

    Si Binance no tiene historia de ese tramo (un par más nuevo que la ventana), la página no trae nada que sirva y el tramo
    queda recorrido: se pide una vez, no en cada vuelta."""
    paso = PASO_MS[temporalidad]
    desde = max(0, (int(desde_ms) // paso) * paso)
    fin = (int(fin_ms) // paso) * paso
    guardadas = {v[0]: v for v in leer_serie(par, temporalidad)}
    avance = {"nuevas": 0, "siguiente": desde, "paginas": 0, "cortado": False}
    while avance["siguiente"] < fin:
        if detener is not None and detener():
            avance["cortado"] = True
            break
        filas = cliente.klines(par, temporalidad, avance["siguiente"])
        avance["paginas"] += 1
        hasta, nuevas = avance["siguiente"], 0
        for fila in filas:
            v = vela_de(fila, paso)
            if v[0] < desde or v[0] + paso > fin:
                continue                       # fuera del tramo, o todavía abierta: la vela en curso no se guarda
            if v[0] not in guardadas:
                nuevas += 1
            guardadas[v[0]] = v
            hasta = max(hasta, v[0] + paso)
        if nuevas or (recortar_desde is not None and any(k < recortar_desde for k in guardadas)):
            guardadas = _guardar_ventana(par, temporalidad, guardadas, recortar_desde)
        avance["nuevas"] += nuevas
        avance["siguiente"] = hasta if hasta > avance["siguiente"] else fin
        if al_avanzar is not None:
            al_avanzar(avance)
    return avance


# ── Las muestras del mercado: lo que Binance no guarda ───────────────────────────────────────────────────────────────────────

def carpeta_muestras():
    return nucleo.carpeta_privada(os.path.join(carpeta_mercado(), "muestras"))


def ruta_muestras(ms):
    return os.path.join(carpeta_muestras(), time.strftime("%Y-%m", time.gmtime(ms / 1000)) + ".jsonl")


def guardar_muestra(m):
    """Una línea al final del archivo del mes, solo para la persona (0600). Nada se reescribe: una muestra que ya se guardó
    es la única que vamos a tener de ese momento."""
    linea = json.dumps(m, ensure_ascii=False, separators=(",", ":")) + "\n"
    fd = os.open(ruta_muestras(m["ms"]), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(linea)
    return m


def meses_con_muestras():
    """Los meses que ya tienen muestras guardadas, del más viejo al más nuevo ("2026-02")."""
    try:
        nombres = os.listdir(carpeta_muestras())
    except OSError:
        return []
    return sorted(n[:-6] for n in nombres if n.endswith(".jsonl") and len(n) == 13)


def bajar_todo(cliente, dias=DIAS_MINIMOS):
    """Baja las 12 series (4 pares × 3 temporalidades) con una sola hora de referencia. Ante un problema para y lo cuenta:
    lo que ya se guardó queda guardado."""
    resumen = {"cuando": iso(ahora_local_ms()), "dias": dias, "nuevas": 0, "pedidos": 0, "esperas": 0, "error": "", "series": {}}
    try:
        ahora = cliente.ahora_ms()
        for par in PARES:
            for temporalidad in TEMPORALIDADES:
                nuevas = bajar_serie(cliente, par, temporalidad, dias, ahora)
                resumen["series"][f"{par}-{temporalidad}"] = nuevas
                resumen["nuevas"] += nuevas
    except Limitado:
        resumen["error"] = "limite"
    except Temporal:
        resumen["error"] = "red"
    except Respuesta:
        resumen["error"] = "respuesta"
    resumen["pedidos"], resumen["esperas"] = cliente.pedidos, cliente.esperas
    return resumen
