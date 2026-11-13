"""Las noticias de influencia que viajan en la app: se revisan antes de mostrarlas y no se inventan."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin"))
import lib_influencia as I  # noqa: E402


class Influencia(unittest.TestCase):
    def archivo(self, datos):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(datos, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_el_archivo_de_la_app_se_entiende(self):
        d = I.cargar()
        self.assertGreater(len(d["eventos"]), 10)
        self.assertTrue(all(e["activo"].isupper() for e in d["eventos"]))

    def test_lo_que_no_se_entiende_se_salta(self):
        ruta = self.archivo({"al": "2026-11-13", "personas": [{"id": "a", "nombre": "Ana"}], "eventos": [
            {"persona": "a", "fecha": "2026-11-10", "que": "x", "activo": "BTC", "movimiento": {"dia": 0.05}},
            {"persona": "a", "fecha": "ayer", "que": "x", "activo": "BTC", "movimiento": {}},
            {"persona": "a", "fecha": "2026-11-11", "que": "x", "activo": "<b>", "movimiento": {}},
            {"persona": "a", "fecha": "2026-11-12", "que": "x", "activo": "ETH", "movimiento": {"dia": "mucho"}}]})
        d = I.cargar(ruta)
        self.assertEqual([e["activo"] for e in d["eventos"]], ["BTC", "ETH"])
        self.assertIsNone(d["eventos"][1]["dia"], "un número que no es número no se muestra")
        r = I.recientes(I._ms("2026-11-13"), ["BTC"], 30, datos=d)
        self.assertEqual(len(r["eventos"]), 1)

    def test_sin_archivo_no_hay_noticias(self):
        self.assertEqual(I.cargar("/no/existe.json")["eventos"], [])


if __name__ == "__main__":
    unittest.main()
