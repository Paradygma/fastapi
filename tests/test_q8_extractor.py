"""
Test suite per Q8Extractor
Verifica l'estrazione corretta di dati da fatture Q8 (Kuwait Petroleum Italia)
"""
import pytest
import pdfplumber
from pathlib import Path
from extractors.q8_extractor import Q8Extractor


FATTURE_DIR = Path(__file__).parent.parent / "Fatture nuove"
PDF_15_08 = FATTURE_DIR / "q8 15-8.pdf"
PDF_31_07 = FATTURE_DIR / "q8 del 31-7.pdf"


def _estrai(extractor, pdf_path):
    if not pdf_path.exists():
        pytest.skip(f"PDF non trovato: {pdf_path}")
    with pdfplumber.open(pdf_path) as pdf:
        return extractor.extract_transactions(pdf)


def _trova(transactions, data, numero_scontrino):
    trans = next(
        (t for t in transactions
         if t.data == data and t.numero_scontrino == numero_scontrino),
        None
    )
    assert trans is not None, f"Transazione {data} {numero_scontrino} non estratta"
    return trans


@pytest.mark.q8
@pytest.mark.unit
class TestQ8Extractor:
    """Test per l'estrattore Q8"""

    @pytest.fixture
    def extractor(self):
        """Fixture che restituisce un'istanza di Q8Extractor"""
        return Q8Extractor()

    def test_can_handle_q8_text(self, extractor):
        """Verifica che can_handle riconosca testo Q8"""
        assert extractor.can_handle("Kuwait Petroleum Italia SpA") is True

    def test_cannot_handle_other_provider(self, extractor):
        """Verifica che can_handle rifiuti altri fornitori"""
        assert extractor.can_handle("TAMOIL ITALIA S.p.A.") is False

    def test_parse_transaction_km(self, extractor):
        """Verifica che il KM venga letto dalla colonna dopo Cod Veic."""
        line = ("7028009864300008038 00028 05/08/26 1145 GLS 0000 589392 5484 "
                "VIA CASSIA KM.21+525 ROMA SF 129,07 61,49 2,099 0,021 2,078 127,78")
        match = extractor._trova_transazione(line)
        trans = extractor._parse_transaction(match, line)

        assert trans["chilometraggio"] == 589392
        assert trans["codice_sede"] == "5484"
        assert trans["localita"] == "VIA CASSIA KM.21+525 ROMA"

    def test_parse_transaction_km_uno_lasciato_invariato(self, extractor):
        """KM 000001 nel PDF resta 1"""
        line = ("7028009864300008038 00021 03/08/26 1021 GLS 0000 000001 5484 "
                "VIA CASSIA KM.21+525 ROMA SF 135,01 64,32 2,099 0,021 2,078 133,66")
        match = extractor._trova_transazione(line)
        trans = extractor._parse_transaction(match, line)

        assert trans["chilometraggio"] == 1

    def test_parse_transaction_km_zeri_iniziali_rimossi(self, extractor):
        """KM con zeri iniziali: zeri rimossi, numero lasciato intero"""
        line = ("7071161600754546725 00005 11/08/26 1245 SSP 0000 011209 5500 "
                "VIA DI BACCANELLO, 1 ROMA SV 247,39 111,99 2,209 0,021 2,188 245,03")
        match = extractor._trova_transazione(line)
        trans = extractor._parse_transaction(match, line)

        assert trans["chilometraggio"] == 11209
        assert trans["codice_sede"] == "5500"
        assert trans["prodotto"] == "BENZINA"


@pytest.mark.q8
@pytest.mark.integration
@pytest.mark.critical
class TestQ8ExtractorKmIntegration:
    """Test KM su fatture Q8 reali"""

    @pytest.fixture
    def extractor(self):
        return Q8Extractor()

    def test_km_fattura_15_08(self, extractor):
        """Fattura 15/08/26: KM estratti dalla colonna KM"""
        transactions = _estrai(extractor, PDF_15_08)

        assert len(transactions) == 38
        assert _trova(transactions, "05/08/26", "00028").chilometraggio == 589392
        assert _trova(transactions, "03/08/26", "00021").chilometraggio == 1
        assert _trova(transactions, "07/08/26", "00020").chilometraggio == 540040
        assert _trova(transactions, "11/08/26", "00005").chilometraggio == 11209
        assert _trova(transactions, "11/08/26", "00005").targa == "HE973JX"

    def test_km_fattura_31_07(self, extractor):
        """Fattura 31/07/26: KM anomali lasciati come nel PDF"""
        transactions = _estrai(extractor, PDF_31_07)

        assert len(transactions) == 39
        assert _trova(transactions, "21/07/26", "00730").chilometraggio == 568395
        assert _trova(transactions, "29/07/26", "00008").chilometraggio == 56907
        assert _trova(transactions, "20/07/26", "19515").chilometraggio == 799
        assert _trova(transactions, "27/07/26", "00012").chilometraggio == 1

    def test_nessun_km_a_zero_quando_presente(self, extractor):
        """Nessuna transazione deve avere KM 0: nel PDF il KM è sempre valorizzato"""
        for pdf_path in (PDF_15_08, PDF_31_07):
            transactions = _estrai(extractor, pdf_path)
            assert all(t.chilometraggio > 0 for t in transactions)


@pytest.mark.q8
@pytest.mark.integration
class TestQ8ColonneAutoroute:
    """Q8 non riporta la matricola: Note vuota, Numero_Fattura valorizzato"""

    def test_colonne_nuove_q8(self):
        from extractors.extractor_factory import ExtractorFactory

        if not PDF_15_08.exists():
            pytest.skip(f"PDF non trovato: {PDF_15_08}")
        result = ExtractorFactory.extract_from_pdf(PDF_15_08.read_bytes(), PDF_15_08.name)

        assert all(r["Numero_Fattura"] == "PJ11921777" for r in result["data"])
        assert all(r["Note"] == "" for r in result["data"])
        assert all(r["Autista"] == "" for r in result["data"])
