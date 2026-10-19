"""
Estrattore per fatture WEX (ex Esso) — WEX Europe Services SRL.
"""
import logging
import re
from typing import List, Dict, Any
from collections import defaultdict
from .base_extractor import BaseExtractor
from models.invoice_models import Transaction

logger = logging.getLogger(__name__)


class EssoExtractor(BaseExtractor):
    """Estrattore per fatture WEX Europe Services (ex Esso)"""

    def __init__(self):
        super().__init__()
        self.fornitore = "WEX"
        # Formato WEX:
        # DD.MM.YY TICKET DI <7-digit-code><LOCALITY NAME> TARGA [KM] prodotto qty ...
        # Esempio: 03.04.26 001621 DI 1452020MAGLIANO EM647VW 385756 gasolio autotrazion 122,18 263,79 ...
        # Esempio (senza KM): 13.04.26 007089 DI 1451479RIGNANO F FS549TP gasolio autotrazion 41,39 91,02 ...
        self._pattern_transazione = re.compile(
            r"(\d{2}\.\d{2}\.\d{2})\s+"            # Data DD.MM.YY       (gruppo 1)
            r"(\d{5,6})\s+"                         # Ticket              (gruppo 2)
            r"DI\s+"                                # Literal "DI"
            r"\d{7}"                                # Codice località (non catturato)
            r"([A-Z][A-Z ]*?)\s+"                   # Nome località       (gruppo 3)
            r"([A-Z]{2}\d{3}[A-Z]{2})\s+"          # Targa               (gruppo 4)
            r"(?:(\d+)\s+)?"                        # KM opzionale        (gruppo 5)
            r"([A-Za-z]\S*(?:\s+[A-Za-z.]\S*)?)\s+"  # Prodotto 1-2 parole (gruppo 6)
            r"([\d,]+)",                            # Quantità            (gruppo 7)
            re.IGNORECASE
        )

    def can_handle(self, pdf_text: str) -> bool:
        indicators = ["WEX Europe Services", "ESSO CARD", "essocard"]
        return any(indicator in pdf_text for indicator in indicators)

    def extract_invoice_header(self, pdf) -> Dict[str, Any]:
        text = self.get_pdf_text(pdf)

        header = {
            "numero_fattura": "",
            "data_fattura": "",
            "cliente": "BEEBUS SPA",
            "totale_imponibile": 0.0,
            "totale_iva": 0.0,
            "totale_fattura": 0.0
        }

        match_nr = re.search(r"Fattura No\s*:\s*(\d+)", text, re.IGNORECASE)
        if match_nr:
            header["numero_fattura"] = match_nr.group(1)

        match_data = re.search(r"Data\s*:\s*(\d{2}\.\d{2}\.\d{4})", text)
        if match_data:
            header["data_fattura"] = match_data.group(1).replace('.', '/')

        match_totale = re.search(r"TOTALE:\s*([\d.,]+)\s*([\d.,]+)\s*([\d.,]+)", text)
        if match_totale:
            header["totale_imponibile"] = self.normalizza_numero(match_totale.group(1))
            header["totale_iva"] = self.normalizza_numero(match_totale.group(2))
            header["totale_fattura"] = self.normalizza_numero(match_totale.group(3))

        return header

    def extract_transactions(self, pdf) -> List[Transaction]:
        transactions = []
        visti = set()

        for page in pdf.pages:
            words = page.extract_words(
                x_tolerance=3,
                y_tolerance=3,
                keep_blank_chars=False,
                use_text_flow=True
            )

            righe = defaultdict(list)
            for w in words:
                righe[round(w["top"])].append(w["text"])

            for top in sorted(righe.keys()):
                line = " ".join(righe[top]).strip()
                if not line:
                    continue

                match_txn = self._pattern_transazione.search(line)
                if match_txn:
                    try:
                        trans_dict = self._parse_transaction(match_txn, line)
                        key = (trans_dict["data"], trans_dict["ora"], trans_dict["numero_scontrino"])
                        if key not in visti:
                            visti.add(key)
                            transactions.append(Transaction(**trans_dict))
                    except Exception as e:
                        logger.debug("Riga transazione scartata: %s (%s)", line, e)
                        continue

        return transactions

    def _parse_transaction(self, match, line: str) -> Dict[str, Any]:
        data_raw = match.group(1)
        data = data_raw.replace('.', '/')

        numero_ticket = match.group(2)
        localita = match.group(3).strip()
        targa = match.group(4)
        km_raw = match.group(5)
        km = int(km_raw) if km_raw and int(km_raw) < 10_000_000 else 0
        prodotto_raw = match.group(6)
        quantita_raw = match.group(7)
        quantita = self.normalizza_numero(quantita_raw)

        # Ultimo importo nella riga = Totale incl. IVA
        importi = re.findall(r"[\d,]+", line)
        importo = self.normalizza_numero(importi[-1]) if importi else 0.0

        prezzo_unitario = importo / quantita if quantita > 0 else 0.0

        return {
            "data": data,
            "ora": "00:00",
            "numero_scontrino": numero_ticket,
            "codice_sede": "",
            "localita": localita,
            "targa": targa,
            "chilometraggio": km,
            "prodotto": self.normalizza_prodotto(prodotto_raw),
            "quantita": quantita,
            "prezzo_unitario": prezzo_unitario,
            "importo_totale": importo,
            "fornitore": "WEX"
        }
