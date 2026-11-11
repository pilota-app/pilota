"""La pantalla principal en un solo lugar: lo que se ve al abrir Pilota, armado de lo que ya está escrito.

Esta capa **no decide, no opera y no toca la red**: junta lo que dejaron escrito los pasos anteriores —el estado firmado
de la cuenta (`lib_estado`), los dos pisos (`lib_frenos.piso_de`), el último tamaño (`lib_tamano.guardado`), el ejecutor
de prueba (`lib_ejecutor_prueba.guardado`), los tres modos (`lib_modos.estado`), el motor (`lib_reconciliar.estado`) y el
registro que no se borra (`lib_registro`)— y lo deja en una sola forma, la que lee la pantalla.

Las reglas de esta capa:

- **Un número que no está no se inventa.** Sin tamaño escrito, el medidor de ese par viene sin puntaje y con su motivo; sin
  velas de 1 m, una posición viene sin ganancia. La pantalla dice qué falta, no rellena.
- **La banda manda**: `ambiente` y `ficticio` van arriba de todo, porque de ellos depende con qué dinero se está jugando.
- **La moneda local es solo una referencia.** La operación es en USDT siempre; la equivalencia se muestra al lado con esa
  nota y sale de una tasa que escribe la persona (no hay ningún servicio de cambio: los datos son suyos y no salen de su
  computador). Sin tasa no se muestra ninguna equivalencia.
- **La mascota no opina: cuenta lo que pasó.** Da un ánimo (`ANIMOS`) y un código (`CUENTOS`) con sus números; las
  palabras y su inglés viven en la pantalla, como todo el texto visible.
- **La línea diaria es del día del mercado** (el día UTC, el mismo corte del registro y de los frenos), aunque se muestre
  en hora local.

Dónde queda: `<datos>/panel/local.json` (la moneda de referencia y a cuánto está un USDT en ella).
"""
import math
import os
import re

import lib_datos
import lib_ejecutor_prueba
import lib_estado
import lib_frenos
import lib_modos
import lib_reconciliar
import lib_registro
import lib_tamano
import nucleo

#: Los cinco ánimos de la mascota, los de la idea: sin celebraciones al cerrar (`neutral`).
ANIMOS = ("atento", "dudando", "operando", "neutral", "frenado")
#: Qué está contando la mascota. Son códigos: la pantalla los cuenta en palabras con sus números y nunca se muestra el
#: código pelado.
CUENTOS = ("frenado", "pausado", "arranque", "aviso", "cerrada", "esperando", "abierta", "llenas", "puesta",
           "rechazada", "apagado", "sobre_exigencia", "bajo_exigencia", "sin_oportunidad", "falta_algo")
#: Las razones del registro que cierran una posición y las que la abren: con ellas se sabe si hoy se operó.
CIERRES = ("objetivo", "stop", "stop_movil", "cierre_manual", "proteccion_sin_confirmar")
ENTRADAS = ("entrada_ruptura", "entrada_rebote")
#: Cuánto rato después de cerrar la mascota sigue en `neutral`: lo justo para alcanzar a leerlo.
RECIEN_MS = 30 * 60 * 1000
#: Cuántas líneas del registro se muestran en la pantalla principal (el registro completo es su propio paso).
LINEAS = 8
#: La moneda de referencia de partida y lo más alto que puede valer un USDT en ella (un número más grande es un dedazo).
MONEDA_LOCAL = "CLP"
TASA_MAXIMA = 100_000_000.0
#: Una moneda es un código de letras, como los de siempre (CLP, EUR, MXN): nada de texto libre en pantalla.
MONEDA = re.compile(r"^[A-Z]{3,8}$")
#: Por qué la pantalla todavía no puede mostrarlo todo. Códigos: la pantalla los traduce.
MOTIVOS = ("sin_cuenta", "sin_medida", "frenado", "motor_apagado", "sin_1m")
#: Por qué no se pudo guardar la moneda local.
RECHAZOS = ("moneda", "tasa")


def carpeta():
    return nucleo.carpeta_privada(os.path.join(nucleo.carpeta_datos(), "panel"))


def ruta_local():
    return os.path.join(carpeta(), "local.json")


# ── Números, sin creerle a nadie ─────────────────────────────────────────────────────────────────────────────────────

def _numero(valor, defecto=0.0):
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        return defecto
    return float(valor)


def _entero(valor, defecto=0):
    return int(_numero(valor, defecto))


def _ms(ahora_ms):
    return int(ahora_ms if ahora_ms is not None else lib_datos.ahora_local_ms())


def _puntaje(valor):
    """El puntaje si es un número de la escala y, si no, `None`: un puntaje que no está no se dibuja en el medidor."""
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        return None
    return min(max(float(valor), 0.0), lib_registro.PUNTAJE_MAXIMO)


# ── La moneda de referencia ──────────────────────────────────────────────────────────────────────────────────────────

def local(d=None):
    """La moneda local y a cuánto está un USDT en ella, como las dejó la persona. Sin tasa, `listo` es falso y la
    pantalla no muestra ninguna equivalencia: una referencia inventada es peor que ninguna."""
    g = d if isinstance(d, dict) else nucleo.leer_json(ruta_local(), {}, maximo=lib_datos.MAXIMO_ARCHIVO)
    g = g if isinstance(g, dict) else {}
    moneda = g.get("moneda") if isinstance(g.get("moneda"), str) and MONEDA.match(g.get("moneda") or "") else MONEDA_LOCAL
    tasa = _numero(g.get("tasa"))
    tasa = tasa if 0 < tasa <= TASA_MAXIMA else 0.0
    return {"moneda": moneda, "tasa": tasa, "cuando": g.get("cuando") or "", "listo": tasa > 0,
            "maxima": TASA_MAXIMA, "nota": "referencia"}


def guardar_local(moneda=None, tasa=None, ahora_ms=None):
    """Guarda la moneda de referencia y su tasa. Lo que no venga no se cambia; una tasa en cero borra la referencia."""
    ms = _ms(ahora_ms)
    antes = local()
    cual = antes["moneda"]
    if moneda is not None:
        cual = str(moneda).strip().upper()
        if not MONEDA.match(cual):
            return {"hecho": False, "motivo": "moneda", "datos": antes}
    valor = antes["tasa"] if tasa is None else _numero(tasa, -1.0)
    if valor < 0 or valor > TASA_MAXIMA:
        return {"hecho": False, "motivo": "tasa", "datos": antes}
    d = {"formato": 1, "moneda": cual, "tasa": float(valor), "cuando": lib_datos.iso(ms)}
    nucleo.escribir_json(ruta_local(), d)
    return {"hecho": True, "motivo": "", "datos": local(d)}


# ── El saldo con su línea del piso ───────────────────────────────────────────────────────────────────────────────────

def saldo_de(cuerpo, ahora_ms=None):
    """El saldo en USDT con todo lo que la pantalla dibuja a su lado: el capital de referencia, los dos pisos y en qué
    parte de ese tramo va el saldo (`sobre_piso`, de 0 a 1: la barra del saldo con la línea del piso)."""
    piso = lib_frenos.piso_de(cuerpo)
    alto = max(piso["referencia"], piso["saldo"])
    tramo = alto - piso["piso"]
    sobre = min(max((piso["saldo"] - piso["piso"]) / tramo, 0.0), 1.0) if tramo > 0 else 0.0
    return {**piso, "sobre_piso": sobre, "alto": alto, "toco_piso": piso["referencia"] > 0 and piso["saldo"] <= piso["piso"],
            "toco_piso_absoluto": piso["aportado"] > 0 and piso["saldo"] <= piso["piso_absoluto"],
            "dia": lib_frenos.dia_de(cuerpo, ahora_ms)}


# ── Los medidores: el puntaje de cada par contra la exigencia ────────────────────────────────────────────────────────

def medidor_de(par, oportunidades, exigencia):
    """El medidor de un par: la oportunidad que más puntúa de las suyas, con su puntaje contra la exigencia. Sin ninguna
    oportunidad —o sin tamaño escrito todavía— viene sin puntaje y con su motivo: un medidor vacío se dice."""
    suyas = [o for o in oportunidades if o.get("par") == par and _puntaje(o.get("puntaje")) is not None]
    mejor = max(suyas, key=lambda o: _puntaje(o.get("puntaje"))) if suyas else None
    if mejor is None:
        return {"par": par, "puntaje": None, "exigencia": exigencia, "pasa": False, "puede": False,
                "motivo": "sin_oportunidad", "parte": 0.0}
    t = mejor.get("tamano") if isinstance(mejor.get("tamano"), dict) else {}
    puntaje = _puntaje(mejor.get("puntaje"))
    return {"par": par, "puntaje": puntaje, "exigencia": exigencia,
            "pasa": puntaje >= exigencia, "parte": puntaje / lib_registro.PUNTAJE_MAXIMO,
            "estrategia": mejor.get("estrategia") or "", "temporalidad": mejor.get("temporalidad") or "",
            "razon": mejor.get("razon") or "", "entrada": _numero(mejor.get("entrada")),
            "stop": _numero(mejor.get("stop")), "objetivo": _numero(mejor.get("objetivo")),
            "monto": _numero(t.get("monto")), "arriesgado": _numero(t.get("arriesgado")),
            "puede": bool(mejor.get("puede")), "motivo": mejor.get("motivo") or ""}


# ── Las posiciones, como se ven ──────────────────────────────────────────────────────────────────────────────────────

def posicion_de(p):
    """Una posición con lo que la pantalla muestra de ella: lo que lleva ganado, su stop y su objetivo. Los números
    salen del ejecutor; acá no se calcula ninguno de nuevo."""
    return {"id": p.get("id") or "", "par": p.get("par") or "", "estrategia": p.get("estrategia") or "",
            "temporalidad": p.get("temporalidad") or "", "estado": p.get("estado") or "",
            "precio": _numero(p.get("precio")), "stop": _numero(p.get("stop")),
            "objetivo": _numero(p.get("objetivo")), "cantidad": _numero(p.get("cantidad")),
            "monto": _numero(p.get("monto")), "puntaje": _puntaje(p.get("puntaje")),
            "precio_ahora": p.get("precio_ahora"), "valor": p.get("valor"), "ganancia": p.get("ganancia"),
            "ganancia_relativa": p.get("ganancia_relativa"), "protegida": bool(p.get("protegida")),
            "movido": bool(p.get("movido")), "entera": bool(p.get("entera")),
            "vence_ms": _entero(p.get("vence_ms"))}


# ── La línea diaria y la mascota ─────────────────────────────────────────────────────────────────────────────────────

def dia_de(registro, exigencia, mejor_puntaje, ahora_ms=None):
    """La línea diaria: si hoy se operó y, si no, cuál fue el mejor puntaje del día contra la exigencia. El día es el
    del mercado (UTC), el mismo del registro y de los frenos, aunque la pantalla lo muestre en hora local.

    Se mira sobre las últimas líneas del registro: es lo que la pantalla ya tiene a mano y alcanza de sobra para un día
    (más atrás que eso es el registro completo, que es su propio paso)."""
    ms = _ms(ahora_ms)
    hasta = lib_frenos.fin_del_dia_ms(ms)
    desde = hasta - lib_datos.DIA_MS
    hoy = [f for f in (registro.get("ultimas") or []) if desde <= _entero(f.get("ms")) < hasta]
    puntajes = [_puntaje(f.get("puntaje")) for f in hoy]
    puntajes = [p for p in puntajes if p is not None]
    if mejor_puntaje is not None:
        puntajes.append(mejor_puntaje)
    entradas = [f for f in hoy if f.get("razon") in ENTRADAS]
    cerradas = [f for f in hoy if f.get("razon") in CIERRES]
    return {"fecha": lib_frenos.fecha_de(ms), "hasta_ms": hasta, "opero": bool(entradas or cerradas),
            "entradas": len(entradas), "cerradas": len(cerradas),
            "vencidas": len([f for f in hoy if f.get("razon") == "propuesta_vencida"]),
            "mejor_puntaje": max(puntajes) if puntajes else None, "exigencia": exigencia,
            "lineas": len(hoy)}


def mascota_de(frenos, propuestas, posiciones, medidores, dia, registro, exigencia, ahora_ms=None, motor=None):
    """Qué cuenta la mascota ahora mismo, en el orden en que importa: un freno puesto manda sobre todo, después un aviso
    del mercado (el que en prueba no frena pero en real sí), después lo que recién cerró (sin celebrar), después lo que
    espera tu respuesta, después lo que está abierto y, al final, lo que está mirando y por qué no entra —no llega a la
    exigencia, la pasa pero no sale monto, o la pasa y nadie está mirando los cruces—.

    Devuelve el ánimo (`ANIMOS`), el código de lo que cuenta (`CUENTOS`) y sus números: las palabras y su inglés viven
    en la pantalla. Ninguno de esos números se calcula acá: todos salen de lo que ya está escrito."""
    ms = _ms(ahora_ms)
    mt = motor if isinstance(motor, dict) else {}
    activos = [c for c in (frenos.get("activos") or []) if isinstance(c, str)]
    if frenos.get("arranque"):
        return {"animo": "frenado", "cuento": "arranque", "datos": {"motivo": frenos.get("arranque_motivo") or ""}}
    if activos:
        return {"animo": "frenado", "cuento": "frenado", "datos": {"freno": activos[0], "n": len(activos)}}
    if frenos.get("pausado"):
        return {"animo": "frenado", "cuento": "pausado",
                "datos": {"n": _entero(frenos.get("protegidas"))}}
    # Los dos frenos del mercado (la comisión y FDUSD) en prueba no frenan: se dicen, y con el mismo número.
    avisos = [c for c in (frenos.get("avisos") or []) if isinstance(c, str)]
    if avisos:
        return {"animo": "dudando", "cuento": "aviso", "datos": {"aviso": avisos[0], "n": len(avisos)}}
    ultima = next(iter(registro.get("ultimas") or []), None) or {}
    if ultima.get("razon") in CIERRES and ms - _entero(ultima.get("ms")) <= RECIEN_MS:
        r = ultima.get("resultado") if isinstance(ultima.get("resultado"), dict) else {}
        return {"animo": "neutral", "cuento": "cerrada",
                "datos": {"par": ultima.get("par") or "", "por": r.get("por") or ultima.get("razon"),
                          "neto": _numero(r.get("neto"))}}
    if propuestas:
        p = propuestas[0]
        return {"animo": "dudando", "cuento": "esperando",
                "datos": {"n": len(propuestas), "par": p.get("par") or "", "puntaje": _puntaje(p.get("puntaje")),
                          "queda_min": _entero(p.get("queda_min")), "monto": _numero(p.get("monto")),
                          "stop": _numero(p.get("stop")), "motivo": p.get("motivo") or ""}}
    abiertas = [p for p in posiciones if p.get("estado") == lib_ejecutor_prueba.ABIERTA]
    if abiertas:
        # Las que caben se cuentan de las que hay abiertas, no de lo guardado: es lo mismo que muestra la lista.
        quedan = max(0, lib_tamano.POSICIONES - len(abiertas))
        return {"animo": "operando", "cuento": "abierta" if quedan else "llenas",
                "datos": {"n": len(abiertas), "maximas": lib_tamano.POSICIONES, "quedan": quedan,
                          "par": abiertas[0].get("par") or "", "ganancia": abiertas[0].get("ganancia")}}
    puestas = [p for p in posiciones if p.get("estado") == lib_ejecutor_prueba.PUESTA]
    if puestas:
        return {"animo": "operando", "cuento": "puesta",
                "datos": {"n": len(puestas), "par": puestas[0].get("par") or "",
                          "entrada": _numero(puestas[0].get("precio"))}}
    suyos = [m for m in medidores if m.get("puntaje") is not None]
    mejor = max(suyos, key=lambda m: m["puntaje"]) if suyos else None
    if mejor is None:
        cuento = "falta_algo" if not medidores or all(m.get("motivo") for m in medidores) else "sin_oportunidad"
        return {"animo": "atento", "cuento": cuento, "datos": {"n": 0}}
    datos = {"par": mejor.get("par") or "", "puntaje": mejor["puntaje"], "exigencia": exigencia,
             "opero": dia.get("opero"), "vencidas": _entero(dia.get("vencidas"))}
    if not mejor.get("pasa"):
        return {"animo": "atento", "cuento": "bajo_exigencia", "datos": datos}
    if not mejor.get("puede"):
        # Pasa la exigencia, pero el tamaño no deja abrirla: el motivo se muestra, nunca se calla.
        return {"animo": "atento", "cuento": "rechazada",
                "datos": {**datos, "motivo": mejor.get("motivo") or "", "n": len(posiciones)}}
    if not mt.get("corriendo"):
        return {"animo": "atento", "cuento": "apagado", "datos": datos}
    return {"animo": "atento", "cuento": "sobre_exigencia", "datos": datos}


# ── Lo que lee la pantalla ───────────────────────────────────────────────────────────────────────────────────────────

def parametros():
    """Con qué reglas se arma la pantalla principal: las lee la pantalla y quedan en la respuesta."""
    return {"animos": list(ANIMOS), "cuentos": list(CUENTOS), "motivos": list(MOTIVOS), "rechazos": list(RECHAZOS),
            "lineas": LINEAS, "recien_min": RECIEN_MS // 60_000, "pares": list(lib_datos.PARES_OPERADOS),
            "puntaje_maximo": lib_registro.PUNTAJE_MAXIMO, "moneda_local": MONEDA_LOCAL, "tasa_maxima": TASA_MAXIMA,
            "ambientes": list(lib_estado.AMBIENTES), "posiciones": lib_tamano.POSICIONES,
            "piso": lib_frenos.PISO, "piso_absoluto": lib_frenos.PISO_ABSOLUTO}


def estado(ahora_ms=None):
    """La pantalla principal entera: la banda, el saldo con su línea del piso y su referencia en moneda local, los
    medidores de puntaje y exigencia por par, las posiciones con lo que llevan ganado, las propuestas que esperan con
    su cuenta atrás, el estado del motor, las últimas líneas del registro, la línea diaria y lo que cuenta la mascota.

    No decide ni opera nada: todo sale de lo que ya está escrito. Lo único que se mueve al mirar son las propuestas que
    se pasaron de su hora (`lib_modos.estado`: mirar también es aplicar) y el plan del motor, igual que al abrir sus
    pantallas."""
    ms = _ms(ahora_ms)
    e = lib_estado.estado(ahora_ms=ms)
    amb = e.get("activo") or lib_estado.PRUEBA
    esta = next((c for c in (e.get("cuentas") or []) if c.get("ambiente") == amb), {})
    cuerpo = lib_estado.cuerpo_de(esta) if esta else lib_estado.nuevo(amb, ahora_ms=ms)
    f = lib_frenos.guardado()
    suyos = next((c for c in (f.get("cuentas") or []) if c.get("ambiente") == amb), {})
    t = lib_tamano.guardado()
    ej = lib_ejecutor_prueba.guardado()
    ej = ej if ej.get("ambiente") == amb else {}
    m = lib_modos.estado(ms, tamano=t, frenos=f, ejecutor=ej)
    mt = lib_reconciliar.estado(ms)
    # El registro se lee después de mirar los modos: mirar también es aplicar, y una propuesta que venció al mirar ya
    # es parte del día y de lo último que hice.
    registro = lib_registro.resumen(amb, ahora_ms=ms)
    exigencia = _numero(m.get("exigencia"), lib_registro.PUNTAJE_MAXIMO)

    medidores = [medidor_de(par, t.get("oportunidades") or [], exigencia) for par in lib_datos.PARES_OPERADOS]
    posiciones = [posicion_de(p) for p in (ej.get("posiciones") or [])]
    propuestas = [p for p in (m.get("propuestas") or []) if p.get("espera")]
    mejor = max((d["puntaje"] for d in medidores if d.get("puntaje") is not None), default=None)
    dia = dia_de(registro, exigencia, mejor, ms)
    frenos = {"estado": suyos.get("estado") or ("frenado" if esta.get("frenado") else ""),
              "frenado": bool(suyos.get("frenado") or esta.get("frenado")),
              "pausado": bool(suyos.get("pausado") or cuerpo.get("pausado")),
              "arranque": bool(esta.get("frenado")), "arranque_motivo": esta.get("motivo") or "",
              "activos": list(suyos.get("activos") or []), "avisos": list(suyos.get("avisos") or []),
              "motivo": ((suyos.get("entradas") or {}).get("motivo") or ""),
              "quedan": _entero((suyos.get("entradas") or {}).get("quedan")),
              "protegidas": _entero(suyos.get("protegidas"), _entero(ej.get("protegidas")))}
    cobertura = ej.get("cobertura") if isinstance(ej.get("cobertura"), dict) else {}
    motivos = []
    if esta.get("frenado"):
        motivos.append({"codigo": "sin_cuenta", "par": "", "n": 0})
    if not t.get("formato"):
        motivos.append({"codigo": "sin_medida", "par": "", "n": 0})
    if frenos["frenado"] and not esta.get("frenado"):
        motivos.append({"codigo": "frenado", "par": "", "n": 0})
    if not mt.get("corriendo"):
        motivos.append({"codigo": "motor_apagado", "par": "", "n": 0})
    if ej and not cobertura.get("cubierto"):
        motivos.append({"codigo": "sin_1m", "par": "", "n": _entero(cobertura.get("sin_cobertura_min"))})
    return {"formato": 1, "cuando": lib_datos.iso(ms), "ambiente": amb, "ficticio": amb == lib_estado.PRUEBA,
            "moneda": "USDT", "modo": m.get("modo") or lib_estado.MODO_FRENADO,
            "efectivo": m.get("efectivo") or lib_estado.MODO_FRENADO, "motivo_modo": m.get("motivo_modo") or "",
            "saldo": saldo_de(cuerpo, ms), "local": local(),
            "exigencia": exigencia, "puntaje_maximo": lib_registro.PUNTAJE_MAXIMO, "modelo": m.get("modelo") or {},
            "medidores": medidores, "mejor_puntaje": mejor,
            "posiciones": posiciones, "abiertas": _entero(ej.get("abiertas")), "puestas": _entero(ej.get("puestas")),
            "propuestas": propuestas, "esperando": len(propuestas),
            "vencidas_hoy": _entero(m.get("vencidas_hoy")), "vencimiento_min": _entero(m.get("vencimiento_min")),
            "frenos": frenos,
            "motor": {"corriendo": bool(mt.get("corriendo")), "activo": bool(mt.get("activo")),
                      "dormido": bool(mt.get("dormido")), "hace_min": mt.get("hace_min"),
                      "ultima": mt.get("ultima") or "", "ciclo_segundos": _entero(mt.get("ciclo_segundos")),
                      "resumen": mt.get("resumen") or {}, "cubierto": bool(cobertura.get("cubierto")),
                      "sin_cobertura_min": cobertura.get("sin_cobertura_min")},
            "historial": {"lineas": _entero(registro.get("lineas")), "desde": registro.get("desde") or "",
                          "dias": _entero(registro.get("dias")), "campos": list(lib_registro.CAMPOS),
                          "ultimas": (registro.get("ultimas") or [])[:LINEAS]},
            "dia": dia,
            "mascota": mascota_de(frenos, propuestas, posiciones, medidores, dia, registro, exigencia, ms,
                                  motor={"corriendo": bool(mt.get("corriendo"))}),
            "parametros": parametros(), "motivos": motivos, "listo": not motivos}
