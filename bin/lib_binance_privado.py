#!/usr/bin/env python3
"""lib_binance_privado — la API privada de Binance, firmada, con lista blanca. Solo biblioteca estándar. No es una acción.

La usa el conector real (`bin/lib_ejecutor_real.py`) y la revisión de la conexión (`bin/lib_real.py`).

Lo que no se negocia aquí:
- **Lista blanca de rutas y métodos** (`RUTAS`): el dominio es el mismo de la API pública (`lib_datos.DOMINIO`), una
  redirección es un error, y una ruta que no está en la lista no se pide nunca. Ninguna ruta de retiro, de transferencia
  ni de margen o futuros está en la lista.
- **Firma HMAC-SHA256** de los parámetros, con `timestamp` y `recvWindow`. La hora se corrige con la del servidor
  (`sincronizar`): un reloj corrido no puede hacer que una orden vieja se acepte tarde.
- **El secreto nunca sale de este objeto**: no se escribe, no se registra y no va en ningún mensaje de error.
- **Los errores de Binance viajan como código** (`ErrorBinance.codigo`, el `code` de Binance) para que quien llama decida;
  el mensaje de Binance no se muestra tal cual.
- `pedir` y `reloj` se reemplazan en las pruebas: así se prueba todo con un Binance falso, sin red.
"""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request

import lib_datos

#: Las únicas rutas privadas que Pilota pide, con su método. Nada de retiros, transferencias, margen ni futuros.
RUTAS = {
    ("GET", "/api/v3/time"): False,                      # pública: la hora del servidor
    ("GET", "/api/v3/account"): True,                    # saldos y si la cuenta puede operar
    ("GET", "/api/v3/account/commission"): True,         # la comisión de verdad de un par
    ("GET", "/sapi/v1/account/apiRestrictions"): True,   # qué permisos tiene la llave (retiro, IP, spot)
    ("GET", "/api/v3/order"): True,                      # una orden por su id propio
    ("GET", "/api/v3/openOrders"): True,                 # las órdenes abiertas de un par
    ("GET", "/api/v3/orderList"): True,                  # una protección (OCO) por su id propio
    ("GET", "/api/v3/myTrades"): True,                   # los llenados de una orden, con su comisión
    ("POST", "/api/v3/order"): True,                     # una compra límite, una venta a mercado o una conversión
    ("POST", "/api/v3/orderList/oco"): True,             # la protección: objetivo + stop
    ("DELETE", "/api/v3/order"): True,                   # cancelar una orden propia
    ("DELETE", "/api/v3/orderList"): True,               # cancelar una protección propia
}
VENTANA_MS = 5000
TIEMPO_LIMITE = 20
MAXIMO_RESPUESTA = 2 * 1024 * 1024
#: Códigos de Binance que Pilota entiende (el resto se trata como «Binance dijo que no»).
NO_EXISTE = -2013            # la orden no existe
SIN_SALDO = -2010            # rechazada: saldo insuficiente, o una LIMIT_MAKER que se habría llenado al tiro
CANCELAR_FALLO = -2011       # no se pudo cancelar (ya no estaba)
HORA = -1021                 # timestamp fuera de la ventana


class ErrorBinance(Exception):
    """Binance respondió con un error. `codigo` es el de Binance (o 0) y `http` el estado HTTP."""

    def __init__(self, codigo=0, http=0, que=""):
        super().__init__(f"Binance respondió {http} ({codigo}) en {que}.")
        self.codigo, self.http, self.que = int(codigo or 0), int(http or 0), que


class SinRed(Exception):
    """No se pudo hablar con Binance (red, 5xx, límite de pedidos). Se puede volver a intentar."""


def _pedir_http(metodo, url, cabeceras, cuerpo):
    pedido = urllib.request.Request(url, data=cuerpo, method=metodo, headers=cabeceras)
    try:
        with urllib.request.build_opener(_SinRedirigir).open(pedido, timeout=TIEMPO_LIMITE) as r:
            if r.geturl().split("?")[0] != url.split("?")[0]:
                raise SinRed("redirigido")
            return r.status, r.read(MAXIMO_RESPUESTA + 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read(MAXIMO_RESPUESTA + 1)
    except (urllib.error.URLError, OSError) as e:
        raise SinRed(e.__class__.__name__) from None


class _SinRedirigir(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class Privada:
    def __init__(self, llave, secreto, pedir=None, reloj=None):
        self._llave, self._secreto = llave, secreto.encode("utf-8")
        self.pedir = pedir or _pedir_http
        self.reloj = reloj or (lambda: int(time.time() * 1000))
        self.desfase = 0
        self.pedidos = 0

    def __repr__(self):
        return "Privada(…)"

    def _firmar(self, parametros):
        texto = urllib.parse.urlencode(parametros)
        firma = hmac.new(self._secreto, texto.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{texto}&signature={firma}"

    def llamar(self, metodo, ruta, parametros=None):
        """Un pedido. Si Binance dice que la hora no cuadra (-1021), se corrige la hora y se intenta una vez más."""
        try:
            return self._llamar(metodo, ruta, parametros)
        except ErrorBinance as e:
            if e.codigo != HORA or ruta == "/api/v3/time":
                raise
            self.sincronizar()
            return self._llamar(metodo, ruta, parametros)

    def _llamar(self, metodo, ruta, parametros=None):
        if (metodo, ruta) not in RUTAS:
            raise ValueError(f"ruta no permitida: {metodo} {ruta}")
        firmada = RUTAS[(metodo, ruta)]
        p = {k: v for k, v in (parametros or {}).items() if v is not None}
        cabeceras = {"Accept": "application/json", "User-Agent": "Pilota"}
        if firmada:
            p.update(timestamp=self.reloj() + self.desfase, recvWindow=VENTANA_MS)
            consulta = self._firmar(p)
            cabeceras["X-MBX-APIKEY"] = self._llave
        else:
            consulta = urllib.parse.urlencode(p)
        url = f"https://{lib_datos.DOMINIO}{ruta}"
        cuerpo = None
        if metodo == "POST":
            cuerpo = consulta.encode("utf-8")
            cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
        elif consulta:
            url = f"{url}?{consulta}"
        self.pedidos += 1
        estado, crudo = self.pedir(metodo, url, cabeceras, cuerpo)
        if len(crudo) > MAXIMO_RESPUESTA:
            raise SinRed("respuesta_grande")
        try:
            datos = json.loads(crudo.decode("utf-8")) if crudo else {}
        except (UnicodeDecodeError, ValueError):
            raise SinRed("respuesta_rara") from None
        if estado in (418, 429) or estado >= 500:
            raise SinRed(f"http_{estado}")
        if estado >= 400:
            codigo = datos.get("code") if isinstance(datos, dict) else 0
            raise ErrorBinance(codigo, estado, ruta)
        return datos

    def sincronizar(self):
        """Corrige la hora local con la del servidor de Binance."""
        d = self._llamar("GET", "/api/v3/time")
        servidor = int(d.get("serverTime") or 0)
        if servidor > 0:
            self.desfase = servidor - self.reloj()
        return self.desfase

    # ── Atajos con nombre: lo que de verdad se pide ──
    def cuenta(self):
        return self.llamar("GET", "/api/v3/account", {"omitZeroBalances": "true"})

    def permisos(self):
        return self.llamar("GET", "/sapi/v1/account/apiRestrictions")

    def comision(self, par):
        return self.llamar("GET", "/api/v3/account/commission", {"symbol": par})

    def orden(self, par, id_propio):
        return self.llamar("GET", "/api/v3/order", {"symbol": par, "origClientOrderId": id_propio})

    def llenados(self, par, orden_id):
        """Los llenados de una orden (por el orderId de Binance), con la comisión de cada uno y en qué moneda."""
        return self.llamar("GET", "/api/v3/myTrades", {"symbol": par, "orderId": orden_id})

    def abiertas(self, par):
        return self.llamar("GET", "/api/v3/openOrders", {"symbol": par})

    def proteccion(self, id_lista):
        return self.llamar("GET", "/api/v3/orderList", {"origClientOrderId": id_lista})

    def comprar_limite(self, par, cantidad, precio, id_propio):
        """Una compra límite que solo puede quedar en el libro (LIMIT_MAKER): si se llenara al tiro, Binance la rechaza."""
        return self.llamar("POST", "/api/v3/order", {"symbol": par, "side": "BUY", "type": "LIMIT_MAKER",
                                                     "quantity": cantidad, "price": precio,
                                                     "newClientOrderId": id_propio, "newOrderRespType": "FULL"})

    def vender_mercado(self, par, cantidad, id_propio):
        return self.llamar("POST", "/api/v3/order", {"symbol": par, "side": "SELL", "type": "MARKET",
                                                     "quantity": cantidad, "newClientOrderId": id_propio,
                                                     "newOrderRespType": "FULL"})

    def comprar_con(self, par, monto_cotizado, id_propio):
        """Una compra a mercado por un monto de la moneda cotizada (la conversión USDT → FDUSD)."""
        return self.llamar("POST", "/api/v3/order", {"symbol": par, "side": "BUY", "type": "MARKET",
                                                     "quoteOrderQty": monto_cotizado, "newClientOrderId": id_propio,
                                                     "newOrderRespType": "FULL"})

    def proteger(self, par, cantidad, objetivo, stop, id_lista):
        """La protección: una OCO de venta con el objetivo (límite, maker) y el stop (a mercado al tocarlo, para que salga
        aunque el precio salte)."""
        return self.llamar("POST", "/api/v3/orderList/oco", {
            "symbol": par, "side": "SELL", "quantity": cantidad,
            "aboveType": "LIMIT_MAKER", "abovePrice": objetivo, "aboveClientOrderId": f"{id_lista}-o",
            "belowType": "STOP_LOSS", "belowStopPrice": stop, "belowClientOrderId": f"{id_lista}-s",
            "listClientOrderId": id_lista, "newOrderRespType": "FULL"})

    def cancelar(self, par, id_propio):
        return self.llamar("DELETE", "/api/v3/order", {"symbol": par, "origClientOrderId": id_propio})

    def cancelar_proteccion(self, par, id_lista):
        return self.llamar("DELETE", "/api/v3/orderList", {"symbol": par, "listClientOrderId": id_lista})


def texto(numero, paso):
    """Un número como lo pide Binance: con los decimales del paso (o del tick), sin notación científica."""
    decimales = 0
    if paso and paso < 1:
        decimales = max(0, len(f"{paso:.10f}".rstrip("0").split(".")[1]))
    return f"{numero:.{decimales}f}"
