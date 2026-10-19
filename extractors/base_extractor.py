"""
Classe astratta base per tutti gli estrattori di fatture.
Ogni estrattore specifico (IP, Esso, Q8) deve implementare questi metodi.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
import pdfplumber
from models.invoice_models import Transaction, InvoiceData, ExtractionResult
from datetime import datetime


class BaseExtractor(ABC):
    """Classe astratta per l'estrazione dati da fatture PDF"""

    def __init__(self):
        self.fornitore = "UNKNOWN"

    @abstractmethod
    def can_handle(self, pdf_text: str) -> bool:
        """
        Determina se questo estrattore può gestire il PDF dato.

        Args:
            pdf_text: Testo estratto dal PDF

        Returns:
            True se questo estrattore può gestire il PDF
        """
        pass

    @abstractmethod
    def extract_invoice_header(self, pdf) -> Dict[str, Any]:
        """
        Estrae i dati dell'intestazione della fattura.

        Args:
            pdf: Oggetto pdfplumber PDF

        Returns:
            Dizionario con numero_fattura, data_fattura, cliente, totali, etc.
        """
        pass

    @abstractmethod
    def extract_transactions(self, pdf) -> List[Transaction]:
        """
        Estrae tutte le transazioni dal PDF.

        Args:
            pdf: Oggetto pdfplumber PDF

        Returns:
            Lista di oggetti Transaction
        """
        pass

    def extract(self, pdf_content: bytes, filename: str) -> ExtractionResult:
        """
        Metodo principale per estrarre tutti i dati dalla fattura.
        Questo metodo orchestra l'estrazione chiamando i metodi specifici.

        Args:
            pdf_content: Contenuto binario del PDF
            filename: Nome del file

        Returns:
            ExtractionResult con tutti i dati estratti
        """
        try:
            with pdfplumber.open(pdf_content) as pdf:
                # Estrai intestazione
                header = self.extract_invoice_header(pdf)

                # Estrai transazioni
                transactions = self.extract_transactions(pdf)

                # Crea oggetto InvoiceData
                invoice_data = InvoiceData(
                    numero_fattura=header.get("numero_fattura", ""),
                    data_fattura=header.get("data_fattura", ""),
                    fornitore=self.fornitore,
                    cliente=header.get("cliente", ""),
                    totale_imponibile=header.get("totale_imponibile", 0.0),
                    totale_iva=header.get("totale_iva", 0.0),
                    totale_fattura=header.get("totale_fattura", 0.0),
                    transactions=transactions
                )

                # Crea risultato
                result = ExtractionResult(
                    status="success",
                    filename=filename,
                    timestamp=datetime.now().isoformat(),
                    fornitore=self.fornitore,
                    invoice_data=invoice_data,
                    records_count=len(transactions),
                    total_amount=header.get("totale_fattura", 0.0)
                )

                return result

        except Exception as e:
            # In caso di errore, restituisci un risultato con errore
            return ExtractionResult(
                status="error",
                filename=filename,
                timestamp=datetime.now().isoformat(),
                fornitore=self.fornitore,
                invoice_data=InvoiceData(
                    numero_fattura="",
                    data_fattura="",
                    fornitore=self.fornitore,
                    cliente="",
                    totale_imponibile=0.0,
                    totale_iva=0.0,
                    totale_fattura=0.0
                ),
                records_count=0,
                total_amount=0.0,
                message=f"Errore durante l'estrazione: {str(e)}"
            )

    @staticmethod
    def normalizza_prodotto(stringa: str) -> str:
        """Normalizza il nome prodotto: strip + uppercase."""
        return stringa.strip().upper() if stringa else ""

    @staticmethod
    def normalizza_numero(stringa: str) -> float:
        """
        Converte una stringa numerica in formato europeo (1.234,56) in float.
        Se non c'e' la virgola, il punto e' considerato separatore decimale
        (1234.56 -> 1234.56), non separatore delle migliaia.

        Args:
            stringa: Stringa da convertire

        Returns:
            Numero convertito
        """
        try:
            if not stringa or stringa == '':
                return 0.0
            # Rimuovi spazi
            stringa = stringa.strip()
            if ',' in stringa:
                # Formato europeo: punto = migliaia, virgola = decimali
                stringa = stringa.replace('.', '').replace(',', '.')
            return float(stringa)
        except (ValueError, AttributeError, TypeError):
            return 0.0

    @staticmethod
    def get_pdf_text(pdf) -> str:
        """
        Estrae tutto il testo dal PDF.

        Args:
            pdf: Oggetto pdfplumber PDF

        Returns:
            Testo completo del PDF
        """
        text = ""
        for page in pdf.pages:
            text += page.extract_text() or ""
        return text
