"""
Test di integrazione end-to-end
Testa l'intero flusso di estrazione con PDF reali
"""
import pytest
import os
from io import BytesIO
from extractors.extractor_factory import ExtractorFactory


class TestFactoryIntegration:
    """Test del factory con riconoscimento automatico"""

    @pytest.fixture
    def factory(self):
        return ExtractorFactory

    def test_factory_recognizes_tamoil(self, factory):
        """Verifica che il factory riconosca automaticamente Tamoil"""
        pdf_path = "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove/tamoil 1-10...pdf"
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        extractor = factory.get_extractor(pdf_content)
        assert extractor.fornitore == "TAMOIL"

    def test_factory_recognizes_esso(self, factory):
        """Verifica che il factory riconosca automaticamente Esso"""
        pdf_path = "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove/esso del 1-10.pdf"
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        extractor = factory.get_extractor(pdf_content)
        assert extractor.fornitore == "ESSO"

    def test_factory_recognizes_ip(self, factory):
        """Verifica che il factory riconosca automaticamente IP"""
        pdf_path = "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove/ip del 1-10.pdf"
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        extractor = factory.get_extractor(pdf_content)
        assert extractor.fornitore == "IP"


class TestEndToEndExtraction:
    """Test end-to-end completo con tutte le fatture"""

    @pytest.fixture
    def factory(self):
        return ExtractorFactory

    def test_extract_all_invoices(self, factory):
        """
        Test completo: estrae tutte le fatture nella cartella "Fatture nuove"
        Verifica che tutti gli estrattori funzionino senza errori
        """
        base_path = "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove"
        if not os.path.exists(base_path):
            pytest.skip(f"Cartella non trovata: {base_path}")

        pdf_files = [
            "tamoil 1-10...pdf",
            "esso del 1-10.pdf",
            "ip del 1-10.pdf",
            "q8 del 1-10.pdf"
        ]

        results = []
        for filename in pdf_files:
            pdf_path = os.path.join(base_path, filename)
            if not os.path.exists(pdf_path):
                continue

            with open(pdf_path, 'rb') as f:
                pdf_content = f.read()

            # Estrai usando il factory
            result = factory.extract_from_pdf(pdf_content, filename)
            results.append(result)

            # Verifica risultato
            assert result["status"] == "success", f"Estrazione fallita per {filename}"
            assert result["records_count"] > 0, f"Nessun record estratto da {filename}"
            total = sum(r["Importo_Totale"] for r in result["data"])
            assert total > 0, f"Totale zero per {filename}"

        # Almeno un PDF deve essere stato processato
        assert len(results) > 0, "Nessun PDF processato!"

    def test_tamoil_critical_checks(self, factory):
        """Test critici specifici per Tamoil"""
        pdf_path = "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove/tamoil 1-10...pdf"
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        result = factory.extract_from_pdf(pdf_content, "tamoil.pdf")

        # Check 1: Deve avere estratto 2 transazioni
        assert result["records_count"] == 2

        # Check 2: Tutte le transazioni devono avere targa FK444ZJ
        for record in result["data"]:
            assert record["Targa"] == "FK444ZJ"

        # Check 3: Totale deve essere 182.50 (101.49 + 81.01)
        actual_total = sum(r["Importo_Totale"] for r in result["data"])
        assert abs(actual_total - 182.50) < 0.01

        # Check 4: Tipo_Rifornimento deve contenere il carburante reale, non "esterno"
        for record in result["data"]:
            assert record["Tipo_Rifornimento"] != "esterno"
            assert record["Tipo_Rifornimento"] == "GASOLIO SELF"

    def test_esso_critical_checks(self, factory):
        """Test critici specifici per Esso"""
        pdf_path = "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove/esso del 1-10.pdf"
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        result = factory.extract_from_pdf(pdf_content, "esso.pdf")

        # Check 1: Deve avere estratto almeno 2 transazioni
        assert result["records_count"] >= 2

        # Check 2: Deve contenere la transazione senza KM (006241)
        scontrini = [record["Numero_Scontrino"] for record in result["data"]]
        assert "006241" in scontrini, "Transazione senza KM non estratta!"

        # Check 3: Tutti gli importi devono essere > 0 (fix IVA)
        for record in result["data"]:
            assert record["Importo_Totale"] > 0

        # Check 4: Tipo_Rifornimento deve contenere il carburante reale
        for record in result["data"]:
            assert record["Tipo_Rifornimento"] != "esterno"
            assert "GASOLIO" in record["Tipo_Rifornimento"]

    def test_ip_critical_checks(self, factory):
        """Test critici specifici per IP"""
        pdf_path = "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove/ip del 1-10.pdf"
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        result = factory.extract_from_pdf(pdf_content, "ip.pdf")

        # Check 1: Deve avere estratto transazioni
        assert result["records_count"] > 0

        # Check 1b: Tipo_Rifornimento non deve essere mai "esterno"
        for record in result["data"]:
            assert record["Tipo_Rifornimento"] != "esterno"
            assert len(record["Tipo_Rifornimento"]) > 0

        # Check 2: Deve contenere la transazione METANO (00005546)
        found_metano = False
        for record in result["data"]:
            if record["Numero_Scontrino"] == "00005546":
                found_metano = True
                # Tipo_Rifornimento deve contenere METANO
                assert "METANO" in record.get("Tipo_Rifornimento", "").upper()
                break

        assert found_metano, "Transazione METANO non estratta!"


class TestCSVExport:
    """Test per la generazione CSV"""

    def test_csv_structure(self):
        """Verifica che il CSV abbia la struttura corretta"""
        from extractors.extractor_factory import ExtractorFactory

        pdf_path = "/Users/mirkopapadopoli/Code/fastapi/Fatture nuove/tamoil 1-10...pdf"
        if not os.path.exists(pdf_path):
            pytest.skip(f"PDF non trovato: {pdf_path}")

        with open(pdf_path, 'rb') as f:
            pdf_content = f.read()

        result = ExtractorFactory.extract_from_pdf(pdf_content, "tamoil.pdf")

        # Verifica che ogni record abbia i campi richiesti
        required_fields = [
            "Targa",
            "Data_Rifornimento",
            "Ora_Rifornimento",
            "Chilometraggio",
            "Litri",
            "Importo_Totale",
            "Fornitore",
            "Tipo_Rifornimento",
            "Numero_Scontrino",
            "Localita",
            "Numero_Fattura",
            "Note",
            "Autista"
        ]

        for record in result["data"]:
            for field in required_fields:
                assert field in record, f"Campo {field} mancante in record"
            # Tipo_Rifornimento deve contenere il carburante, non il valore hardcoded
            assert record["Tipo_Rifornimento"] != "esterno"
            assert len(record["Tipo_Rifornimento"]) > 0


class TestErrorHandling:
    """Test per gestione errori"""

    def test_invalid_pdf_format(self):
        """
        Verifica gestione file non leggibile come PDF.
        Il messaggio distingue questo caso da 'Tipo di fattura non riconosciuto',
        che riguarda un PDF valido di un fornitore non supportato.
        """
        fake_pdf_text = b"Questo non e' un PDF di fattura valido"

        with pytest.raises(ValueError, match="PDF non leggibile"):
            ExtractorFactory.get_extractor(fake_pdf_text)

    def test_empty_pdf(self):
        """Verifica gestione PDF vuoto"""
        empty_pdf = b""

        with pytest.raises(ValueError):
            ExtractorFactory.get_extractor(empty_pdf)
