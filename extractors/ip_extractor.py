"""
Estrattore per fatture IP Plus.
Basato sulla logica esistente del main.py originale.
"""
import logging
import re
from typing import List, Dict, Any
from collections import defaultdict
from .base_extractor import BaseExtractor
from models.invoice_models import Transaction

logger = logging.getLogger(__name__)


class IPExtractor(BaseExtractor):
    """Estrattore specifico per fatture IP Plus"""

    def __init__(self):
        super().__init__()
        self.fornitore = "IP"

    def can_handle(self, pdf_text: str) -> bool:
        """Verifica se il PDF è una fattura IP Plus"""
        indicators = ["IP PLUS S.R.L", "IP PLUS", "IP Plus"]
        return any(indicator in pdf_text for indicator in indicators)

    def extract_invoice_header(self, pdf) -> Dict[str, Any]:
        """Estrae i dati dell'intestazione della fattura IP"""
        text = self.get_pdf_text(pdf)

        header = {
            "numero_fattura": "",
            "data_fattura": "",
            "cliente": "BEEBUS SPA",
            "totale_imponibile": 0.0,
            "totale_iva": 0.0,
            "totale_fattura": 0.0
        }

        # Estrai numero fattura
        match_nr = re.search(r"Nr:\s*(\d+)", text)
        if match_nr:
            header["numero_fattura"] = match_nr.group(1)

        # Estrai data fattura
        match_data = re.search(r"Data:\s*(\d{2}/\d{2}/\d{4})", text)
        if match_data:
            header["data_fattura"] = match_data.group(1)

        # Estrai totali
        match_acquisti = re.search(r"Acquisti del periodo:\s*EUR\s*([\d.,]+)", text)
        if match_acquisti:
            header["totale_imponibile"] = self.normalizza_numero(match_acquisti.group(1))

        match_iva = re.search(r"IVA\s*EUR\s*([\d.,]+)", text)
        if match_iva:
            header["totale_iva"] = self.normalizza_numero(match_iva.group(1))

        match_totale = re.search(r"Totale Importo:\s*EUR\s*([\d.,]+)", text)
        if match_totale:
            header["totale_fattura"] = self.normalizza_numero(match_totale.group(1))

        return header

    def extract_transactions(self, pdf) -> List[Transaction]:
        """Estrae le transazioni dalla fattura IP"""
        transactions = []
        transazioni_in_attesa = []
        visti = set()
        targa_corrente = None

        for page in pdf.pages:
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=True
            )

            # Raggruppa parole per riga (basato su coordinata Y)
            righe = defaultdict(list)
            for w in words:
                righe[round(w["top"])].append(w["text"])

            # Processa ogni riga
            for top in sorted(righe.keys()):
                line = " ".join(righe[top]).strip()
                if not line:
                    continue

                # Cerca targa
                targa = self._estrai_targa(line)
                if targa:
                    # Assegna targa alle transazioni in attesa
                    for trans_dict in transazioni_in_attesa:
                        trans_dict["targa"] = targa
                        key = (
                            trans_dict["data"],
                            trans_dict["ora"],
                            trans_dict["numero_scontrino"]
                        )
                        if key not in visti:
                            visti.add(key)
                            transactions.append(Transaction(**trans_dict))

                    transazioni_in_attesa = []
                    targa_corrente = targa
                    continue

                # Cerca transazione
                match_txn = self._trova_transazione(line)
                if match_txn:
                    try:
                        trans_dict = self._parse_transaction(match_txn, line)
                        transazioni_in_attesa.append(trans_dict)
                    except Exception as e:
                        logger.debug("Riga transazione scartata: %s (%s)", line, e)
                        continue

        # Gestisci transazioni rimaste (senza targa)
        for trans_dict in transazioni_in_attesa:
            trans_dict["targa"] = "SCONOSCIUTA"
            key = (trans_dict["data"], trans_dict["ora"], trans_dict["numero_scontrino"])
            if key not in visti:
                visti.add(key)
                transactions.append(Transaction(**trans_dict))

        return transactions

    def _trova_transazione(self, line: str):
        """Pattern regex per identificare una transazione IP"""
        pattern = (
            r"^(\d{2}/\d{2}/\d{2})\s+"     # Data
            r"(\d{2}:\d{2})\s+"            # Ora
            r"(\d{8})\s+"                  # Numero scontrino
            r"(\d{5})\s+"                  # Codice PV
            r"(.+?)\s+"                    # Località
            r"(\d{1,3}(?:\.\d{3})*|1)\s+"  # Chilometraggio
            r"0000\s+"                     # Codice fisso
            r"([A-Z]+(?:\s+[A-Z]+)?)\s+"   # Prodotto generico (es: GASOLIO, METANO, GASOLIO SELF)
            r"([\d,]+)"                    # Quantità (litri/kg)
        )
        return re.search(pattern, line)

    def _estrai_targa(self, line: str) -> str:
        """Estrae la targa italiana dal testo"""
        pattern = r"TARGA\s+([A-Z]{2}[0-9]{3}[A-Z]{2})"
        match = re.search(pattern, line)
        return match.group(1) if match else None

    def _estrai_importo_finale(self, line: str) -> float:
        """Estrae l'importo finale dalla riga"""
        importi = re.findall(r"\d+,\d+", line)
        return self.normalizza_numero(importi[-1]) if importi else 0.0

    def _valida_chilometraggio(self, raw: str) -> int:
        """Valida e converte il chilometraggio"""
        try:
            km = int(raw.replace('.', ''))
            if km > 10_000_000:
                return 0
            return km
        except (ValueError, AttributeError, TypeError):
            return 0

    def _determina_tipo_gasolio(self, line: str) -> str:
        """Determina il tipo di gasolio"""
        if "GASOLIO SELF" in line:
            return "esterno"
        elif "GASOLIO" in line:
            return "esterno"
        return "esterno"

    def _parse_transaction(self, match, line: str) -> Dict[str, Any]:
        """Converte il match regex in un dizionario per Transaction"""
        data = match.group(1)
        ora = match.group(2)
        numero_scontrino = match.group(3)
        codice_pv = match.group(4)
        localita_raw = match.group(5)
        chilometraggio_raw = match.group(6)
        prodotto_raw = match.group(7)  # Prodotto catturato dal pattern
        quantita_raw = match.group(8)  # Litri/Kg

        localita = localita_raw.strip().rstrip(',')
        chilometraggio = self._valida_chilometraggio(chilometraggio_raw)
        quantita = self.normalizza_numero(quantita_raw)
        importo_totale = self._estrai_importo_finale(line)
        prodotto = self.normalizza_prodotto(prodotto_raw)

        return {
            "data": data,
            "ora": ora,
            "numero_scontrino": numero_scontrino,
            "codice_sede": codice_pv,
            "localita": localita,
            "targa": "",  # Verrà assegnata dopo
            "chilometraggio": chilometraggio,
            "prodotto": prodotto,  # Prodotto generico (GASOLIO, GASOLIO SELF, METANO, ecc.)
            "quantita": quantita,
            "prezzo_unitario": importo_totale / quantita if quantita > 0 else 0.0,
            "importo_totale": importo_totale,
            "fornitore": "IP"
        }
