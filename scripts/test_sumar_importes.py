"""
Tests unitarios del parser de importes de utils_importes.py, usado por
sumar_importes() en mcp_documentos.py. Solo prueban las funciones puras
del parser -- sin red ni llamada a Paperless, y sin arrastrar el import de
mcp_documentos.py (que abre un chromadb.PersistentClient en cuanto se
importa: importar solo utils_importes.py evita ese efecto).

Uso:
    python -m unittest scripts.test_sumar_importes -v
    (o, desde dentro de scripts\\: python -m unittest test_sumar_importes -v)
"""

import sys
import unittest
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from utils_importes import _parsear_importes_linea, _formatear_importe, procesar_linea


class TestParsearImportesLinea(unittest.TestCase):

    def test_importe_sin_miles(self):
        self.assertEqual(_parsear_importes_linea("Total: 234,56 EUR"), [Decimal("234.56")])

    def test_importe_con_miles_punto(self):
        self.assertEqual(_parsear_importes_linea("Importe: 1.234,56 EUR"), [Decimal("1234.56")])

    def test_importe_sin_punto_de_miles_pero_4_cifras(self):
        self.assertEqual(_parsear_importes_linea("Base imponible 1234,56"), [Decimal("1234.56")])

    def test_miles_multiples(self):
        self.assertEqual(_parsear_importes_linea("Total 12.345.678,90"), [Decimal("12345678.90")])

    def test_simbolo_euro_pegado_detras(self):
        self.assertEqual(_parsear_importes_linea("Total 1.234,56€"), [Decimal("1234.56")])

    def test_simbolo_euro_pegado_delante(self):
        self.assertEqual(_parsear_importes_linea("Total €1.234,56"), [Decimal("1234.56")])

    def test_cuatro_cifras_sin_separador_de_miles(self):
        self.assertEqual(_parsear_importes_linea("Importe 1234,56"), [Decimal("1234.56")])

    def test_negativo_con_guion(self):
        self.assertEqual(_parsear_importes_linea("Descuento -234,56"), [Decimal("-234.56")])

    def test_negativo_con_guion_y_espacio(self):
        self.assertEqual(_parsear_importes_linea("Descuento - 234,56"), [Decimal("-234.56")])

    def test_negativo_con_parentesis(self):
        self.assertEqual(_parsear_importes_linea("Ajuste (1.234,56)"), [Decimal("-1234.56")])

    def test_ignora_numeros_sin_decimales(self):
        # Numero de factura, fecha (ddmmaaaa) y referencia -- ninguno lleva
        # coma decimal, ninguno debe interpretarse como importe.
        self.assertEqual(
            _parsear_importes_linea("Factura 2024001 del 15012024 ref 987654"), []
        )

    def test_ignora_anio_suelto(self):
        self.assertEqual(_parsear_importes_linea("Ejercicio fiscal 2024"), [])

    def test_linea_sin_importe(self):
        self.assertEqual(_parsear_importes_linea("Gracias por su compra"), [])

    def test_linea_vacia(self):
        self.assertEqual(_parsear_importes_linea(""), [])

    def test_varios_importes_en_la_misma_linea(self):
        self.assertEqual(
            _parsear_importes_linea("Subtotal 100,00 IVA 21,00 Total 121,00"),
            [Decimal("100.00"), Decimal("21.00"), Decimal("121.00")],
        )

    def test_positivo_y_negativo_en_la_misma_linea(self):
        self.assertEqual(
            _parsear_importes_linea("Cargo 50,00 Abono -20,00"),
            [Decimal("50.00"), Decimal("-20.00")],
        )

    def test_usa_decimal_no_float(self):
        # 0,1 + 0,2 en float da 0.30000000000000004; con Decimal debe ser
        # exacto, sin arrastrar ese error de redondeo.
        importes = _parsear_importes_linea("0,10 0,20")
        self.assertEqual(sum(importes), Decimal("0.30"))
        self.assertIsInstance(importes[0], Decimal)


class TestFormatearImporte(unittest.TestCase):

    def test_formatea_sin_miles(self):
        self.assertEqual(_formatear_importe(Decimal("234.56")), "234,56")

    def test_formatea_con_miles(self):
        self.assertEqual(_formatear_importe(Decimal("1234.56")), "1.234,56")

    def test_formatea_negativo(self):
        self.assertEqual(_formatear_importe(Decimal("-1234.56")), "-1.234,56")

    def test_formatea_cero(self):
        self.assertEqual(_formatear_importe(Decimal("0")), "0,00")

    def test_redondea_a_2_decimales(self):
        self.assertEqual(_formatear_importe(Decimal("1234.5")), "1.234,50")


class TestProcesarLinea(unittest.TestCase):
    """procesar_linea() es la logica por linea de sumar_importes():
    exclusion de SALDO + seleccion solo_primero."""

    def test_excluye_linea_con_saldo_mayusculas(self):
        importes, excluida = procesar_linea("**SALDO ANTERIOR EN EUROS** 27.919,43")
        self.assertEqual(importes, [])
        self.assertTrue(excluida)

    def test_excluye_linea_con_saldo_minusculas(self):
        importes, excluida = procesar_linea("saldo anterior(eur) 26.813,02")
        self.assertEqual(importes, [])
        self.assertTrue(excluida)

    def test_excluye_linea_con_saldo_mixto_no_cabecera(self):
        # "SALDO" en medio de una linea normal (no de cabecera) tambien
        # debe excluirse -- el enunciado dice "sean o no de cabecera".
        importes, excluida = procesar_linea("Movimiento con SALDO parcial 100,00 200,00")
        self.assertEqual(importes, [])
        self.assertTrue(excluida)

    def test_no_excluye_linea_normal(self):
        importes, excluida = procesar_linea(
            "01-06-26 945 01-06-26 TRANSF /Isabel Rodriguez Royo 400,00 27.519,43"
        )
        self.assertFalse(excluida)
        self.assertEqual(importes, [Decimal("400.00")])

    def test_solo_primero_true_por_defecto_descarta_el_saldo(self):
        importes, excluida = procesar_linea(
            "01-06-26 280 01-06-26 RECIBO /FORUS BADAJOZ 61,27 27.098,16"
        )
        self.assertFalse(excluida)
        self.assertEqual(importes, [Decimal("61.27")])

    def test_solo_primero_false_conserva_todos_los_importes(self):
        importes, excluida = procesar_linea(
            "01-06-26 280 01-06-26 RECIBO /FORUS BADAJOZ 61,27 27.098,16",
            solo_primero=False,
        )
        self.assertFalse(excluida)
        self.assertEqual(importes, [Decimal("61.27"), Decimal("27098.16")])

    def test_linea_sin_importes_no_excluida(self):
        importes, excluida = procesar_linea("Movimientos y saldo de su cuenta")
        # Contiene "saldo" -> excluida, aunque no tenga ningun importe.
        self.assertEqual(importes, [])
        self.assertTrue(excluida)

    def test_linea_normal_sin_importes(self):
        importes, excluida = procesar_linea("Fecha Referencia Fecha valor Descripcion")
        self.assertEqual(importes, [])
        self.assertFalse(excluida)


if __name__ == "__main__":
    unittest.main()
