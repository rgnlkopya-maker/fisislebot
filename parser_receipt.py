import re
from typing import Dict, Any, Optional, List


# -------------------------
# Helpers
# -------------------------
def _clean(text: str) -> str:
    """Normalize OCR output."""
    text = text.replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()




def _find_first(pattern: str, text: str, flags=0) -> Optional[str]:
    """Return first regex capture group."""
    m = re.search(pattern, text, flags)
    if not m:
        return None
    return m.group(1).strip()


def _parse_tr_amount(s: str) -> Optional[float]:
    """
    Turkish amount parsing:
    - "6.900,00" -> 6900.00
    - "5750" -> 5750.00
    - OCR bozuk: "115000" -> 1150.00  (son 2 hane kuruş)
    """
    if not s:
        return None
    s = s.strip()

    # digits-only (5-9) -> last 2 digits are decimals
    if re.fullmatch(r"\d{5,9}", s):
        try:
            return float(s[:-2] + "." + s[-2:])
        except Exception:
            pass

    s = re.sub(r"[^\d\.,]", "", s)
    if not s:
        return None

    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def _extract_amount_candidates(text: str) -> List[float]:
    """
    Extract likely money values from text.
    """
    candidates = []

    for m in re.findall(r"([\d\.\,]{2,})\s*TL", text, flags=re.IGNORECASE):
        val = _parse_tr_amount(m)
        if val is not None:
            candidates.append(val)

    for m in re.findall(r"\b(\d{1,3}(?:\.\d{3})*(?:,\d{2})|\d{1,6},\d{2})\b", text):
        val = _parse_tr_amount(m)
        if val is not None:
            candidates.append(val)

    return sorted(set(candidates))


def detect_doc_type(text: str) -> Dict[str, Any]:
    """Detect document type by keyword signatures."""
    t = text.lower()

    signatures = {
        "e_fatura": [
            "gib", "etn", "vergiler dahil toplam tutar", "senaryo", "fatura no", "vkn", "mal hizmet toplam tutar"
        ],
        "pos_slip": [
            "pos", "slip", "onay kodu", "provizyon", "terminal", "kart no", "işlem no"
        ],
        "market_fis": [
            "fiş", "fis", "kasa", "kasiyer", "toplam", "kdv", "para üstü", "para ustu", "indirim"
        ],
        "restaurant_fis": [
            "masa", "adisyon", "servis", "garson", "kuver"
        ],
        "akaryakit_fis": [
            "litre", "pompa", "akaryakıt", "akaryakit", "istasyon", "nozzle"
        ],
    }

    best_type = "unknown"
    best_score = 0
    matched = []

    for doc_type, keys in signatures.items():
        hits = [k for k in keys if k in t]
        score = len(hits)
        if score > best_score:
            best_score = score
            best_type = doc_type
            matched = hits

    if best_score == 0:
        conf = 0.30
    elif best_score == 1:
        conf = 0.55
    elif best_score == 2:
        conf = 0.70
    else:
        conf = 0.90

    return {
        "value": best_type,
        "confidence": conf,
        "source": "signature_keywords",
        "matched_signatures": matched[:5]
    }


def _find_lines_containing_amount(text: str, amount: float, max_lines: int = 3) -> List[str]:
    """Return up to max_lines lines that likely contain the amount."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    amt_int = int(round(amount))
    variants = [
        str(amt_int),
        f"{amt_int:,}".replace(",", "."),
        f"{amt_int:,}".replace(",", ".") + ",00",
        str(amt_int) + ",00",
    ]

    hits = []
    for ln in lines:
        if any(v in ln for v in variants):
            hits.append(ln)
            if len(hits) >= max_lines:
                break
    return hits


def _find_lines_containing_keywords(text: str, keywords: List[str], max_lines: int = 3) -> List[str]:
    """Return up to max_lines lines containing any keyword."""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    hits = []
    kw_lower = [k.lower() for k in keywords]

    for ln in lines:
        ln_lower = ln.lower()
        if any(k in ln_lower for k in kw_lower):
            hits.append(ln)
            if len(hits) >= max_lines:
                break
    return hits

def _extract_date_by_label(text: str) -> Optional[str]:
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    label_keywords = [
        "tarih",
        "düzenleme tarihi",
        "duzenleme tarihi",
        "belge tarihi",
        "düzenlenme tarihi",
        "duzenlenme tarihi",
        "date"
    ]

    date_regexes = [
        r"(\d{2}[./-]\d{2}[./-]\d{4})",  # 05.01.2026
        r"(\d{4}[./-]\d{2}[./-]\d{2})",  # 2026-01-05
        r"(\d{2}[./-]\d{2}[./-]\d{2})",  # 05.01.26
    ]

    for i, ln in enumerate(lines):
        ln_l = ln.lower()
        if any(k in ln_l for k in label_keywords):

            # same line
            for rx in date_regexes:
                m = re.search(rx, ln)
                if m:
                    return m.group(1)

            # next line
            if i + 1 < len(lines):
                next_ln = lines[i + 1]
                for rx in date_regexes:
                    m = re.search(rx, next_ln)
                    if m:
                        return m.group(1)

    return None



def add_warning(
    warnings: List[Dict[str, Any]],
    code: str,
    severity: str = "medium",
    message: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None
) -> None:
    w = {
        "code": code,
        "severity": severity,
        "message": message or code,
    }
    if meta:
        w["meta"] = meta
    warnings.append(w)


def _field(value, confidence: float, source: str) -> Dict[str, Any]:
    return {"value": value, "confidence": round(float(confidence), 2), "source": source}


def _normalize_weird_ocr_amount_digits(s: str) -> Optional[str]:
    """
    Fix cases like: "11500071" -> should likely be "115000" (drop trailing noise)
    Strategy:
    - If too long and ends with 1-2 noise digits, truncate to 5-9 digits window.
    """
    if not s:
        return None
    s = re.sub(r"\D", "", s)
    if not s:
        return None

    # If length > 9, take first 9
    if len(s) > 9:
        s = s[:9]

    # If ends with 1-2 extra digits (like 11500071),
    # try to cut down to 6 digits or 7 digits range where parse_tr_amount makes sense.
    if len(s) == 8 and s.endswith(("71", "11", "01", "91")):
        s = s[:-2]

    return s


# -------------------------
# Main Parser (Prod-Oriented V2)
# -------------------------
def parse_receipt_fields(raw_text: str, filename: str = "") -> Dict[str, Any]:
    text = _clean(raw_text)

    out: Dict[str, Any] = {
        "schema_version": "2.0",
        "fields": {},
        "warnings": [],
        "amount_candidates": [],
        "overall_confidence": 0.0,
    }

    fields = out["fields"]
    warnings: List[Dict[str, Any]] = out["warnings"]

    # doc type
    fields["doc_type"] = detect_doc_type(text)
    if fields["doc_type"]["value"] == "unknown":
        add_warning(
            warnings,
            code="doc_type_unknown",
            severity="medium",
            message="Belge tipi tespit edilemedi (unknown)",
            meta={"matched_signatures": fields["doc_type"]["matched_signatures"]}
        )

    # amount candidates
    amounts = _extract_amount_candidates(text)
    out["amount_candidates"] = amounts

    # -------------------------
    # Identity
    # -------------------------
    vkn = _find_first(r"\bVKN[: ]*\s*(\d{10,11})\b", text, flags=re.IGNORECASE)
    if vkn:
        fields["vkn"] = _field(vkn, 0.95, "keyword_vkn")

    tckn = _find_first(r"\bTCKN[: ]*\s*(\d{11})\b", text, flags=re.IGNORECASE)
    if tckn and not tckn.startswith("0"):
        fields["tckn"] = _field(tckn, 0.70, "keyword_tckn")
    elif tckn:
        add_warning(
            warnings,
            code="tckn_suspect",
            severity="medium",
            message="TCKN şüpheli görünüyor",
            meta={"tckn": tckn}
        )

    # -------------------------
    # Invoice No
    # -------------------------
    invoice_no = _find_first(
        r"\bFatura No[: ]*\s*([A-Z]{2,}[\w\-_/]{4,})\b",
        text,
        flags=re.IGNORECASE
    )
    if not invoice_no:
        invoice_no = _find_first(r"\b(GIB[\w\-_/]{6,})\b", text, flags=re.IGNORECASE)
        if invoice_no:
            fields["invoice_no"] = _field(invoice_no, 0.85, "fallback_gib")
    else:
        fields["invoice_no"] = _field(invoice_no, 0.95, "keyword_invoice_no")

    # -------------------------
    # ETTN / ETN
    # -------------------------
    ettn = _find_first(r"\bETN[: ]*\s*([0-9a-fA-F\-]{20,})\b", text, flags=re.IGNORECASE)
    if ettn:
        fields["ettn"] = _field(ettn, 0.95, "keyword_ettn")

    # -------------------------
    # Date
    # -------------------------
    date_patterns = [
        (r"\b(\d{2}[./-]\d{2}[./-]\d{4})\b", "dd.mm.yyyy"),
        (r"\b(\d{4}[./-]\d{2}[./-]\d{2})\b", "yyyy-mm-dd"),
        (r"\b(\d{2}[./-]\d{2}[./-]\d{2})\b", "dd.mm.yy"),
    ]

    date_str = None
    date_source = None

    # 1) global scan
    for pattern, label in date_patterns:
        date_str = _find_first(pattern, text)
        if date_str:
            date_source = f"pattern_date_{label}"
            break

    # 2) label-based scan (tarih satırı + alt satır)
    if not date_str:
        date_str = _extract_date_by_label(text)
        if date_str:
            date_source = "label_based_date"

    if date_str:
        fields["date"] = _field(date_str, 0.75, date_source)
    else:
        hint_lines = _find_lines_containing_keywords(
            text,
            keywords=["tarih", "düzenleme", "duzenleme", "düzenlenme", "duzenlenme", "belge", "date"],
            max_lines=5
        )
        add_warning(
            warnings,
            code="date_not_found",
            severity="high",
            message="Belge tarihi bulunamadı",
            meta={
                "tried_patterns": [lbl for _, lbl in date_patterns],
                "hint_lines": hint_lines
            }
        )


    # -------------------------
    # Amounts
    # -------------------------
    # TOTAL (including VAT)
    total_incl = None

    total_incl_str = _find_first(
        r"Vergiler\W*Dahil\W*Toplam\W*Tutar.{0,80}?([>\-]*\s*[\d\.\,]+)\s*TL?",
        text,
        flags=re.IGNORECASE
    )
    if not total_incl_str:
        total_incl_str = _find_first(
            r"(?:Genel\W*Toplam|Ödenecek\W*Tutar|TOPLAM).{0,80}?([>\-]*\s*[\d\.\,]+)\s*TL?",
            text,
            flags=re.IGNORECASE
        )

    if total_incl_str:
        total_incl = _parse_tr_amount(total_incl_str)

    if total_incl is not None:
        fields["total_including_vat"] = _field(total_incl, 0.90, "keyword_total")
    else:
        if amounts:
            selected_total = max(amounts)
            fields["total_including_vat"] = _field(selected_total, 0.55, "heuristic_max_amount")
            add_warning(
                warnings,
                code="total_fallback_max_amount",
                severity="medium",
                message="Toplam tutar max(amounts) ile seçildi",
                meta={
                    "amount_candidates": amounts,
                    "selected_total": selected_total,
                    "evidence_lines": _find_lines_containing_amount(text, selected_total)
                }
            )
        else:
            add_warning(warnings, code="total_not_found", severity="high", message="Toplam tutar bulunamadı")

    # SUBTOTAL (excluding VAT)  ✅ FIX: Tutarı / Tutari / Tutar*
    subtotal = None
    subtotal_str = _find_first(
        r"(?:Mal\s*Hizmet\s*Toplam\s*Tutar\w*|Ara\s*Toplam)\W*[: ]*\W*([>\-]*\s*[\d\.\,]+)\s*TL",
        text,
        flags=re.IGNORECASE
    )
    if subtotal_str:
        subtotal = _parse_tr_amount(subtotal_str)

    if subtotal is not None:
        fields["total_excluding_vat"] = _field(subtotal, 0.85, "keyword_subtotal")

    # VAT AMOUNT ✅ OCR weird digits support
    vat_amount = None
    vat_amount_str = _find_first(
        r"(?:Hesaplanan\s*KDV|KDV)\w*\W*[: ]*\W*([>\-]*\s*[\d\.\,]+)\s*TL?",
        text,
        flags=re.IGNORECASE
    )
    if vat_amount_str:
        vat_amount = _parse_tr_amount(vat_amount_str)

    if vat_amount is None:
        weird_digits = _find_first(
            r"Hesaplanan.{0,20}?KDV.{0,20}?([0-9]{5,12})",
            text,
            flags=re.IGNORECASE
        )

        weird_digits = _normalize_weird_ocr_amount_digits(weird_digits)
        if weird_digits:
            vat_amount = _parse_tr_amount(weird_digits)

    if vat_amount is not None:
        fields["vat_amount"] = _field(vat_amount, 0.80, "keyword_vat")

    # -------------------------
    # Consistency check
    # -------------------------
    subtotal_v = fields.get("total_excluding_vat", {}).get("value")
    vat_v = fields.get("vat_amount", {}).get("value")
    total_v = fields.get("total_including_vat", {}).get("value")

    if subtotal_v is not None and vat_v is not None and total_v is not None:
        if abs((subtotal_v + vat_v) - total_v) <= max(1.0, total_v * 0.01):
            fields["total_including_vat"]["confidence"] = min(1.0, fields["total_including_vat"]["confidence"] + 0.15)
            fields["total_excluding_vat"]["confidence"] = min(1.0, fields["total_excluding_vat"]["confidence"] + 0.10)
            fields["vat_amount"]["confidence"] = min(1.0, fields["vat_amount"]["confidence"] + 0.10)
        else:
            add_warning(
                warnings,
                code="amounts_inconsistent",
                severity="high",
                message="Ara toplam + KDV toplamı genel toplam ile uyuşmuyor",
                meta={"subtotal": subtotal_v, "vat": vat_v, "total": total_v}
            )

    # Currency constant
    fields["currency"] = _field("TRY", 1.00, "constant")

    # -------------------------
    # Overall confidence
    # -------------------------
    score = 0.0
    if "total_including_vat" in fields:
        score += fields["total_including_vat"]["confidence"] * 0.55
    if "date" in fields:
        score += fields["date"]["confidence"] * 0.20
    if "vkn" in fields:
        score += fields["vkn"]["confidence"] * 0.25

    penalty = 0.0
    for w in warnings:
        sev = w.get("severity")
        if sev == "high":
            penalty += 0.20
        elif sev == "medium":
            penalty += 0.10
        elif sev == "low":
            penalty += 0.05

    score = max(0.0, score - penalty)
    out["overall_confidence"] = round(score, 2)

    if out["overall_confidence"] < 0.60:
        add_warning(
            warnings,
            code="overall_confidence_low",
            severity="medium",
            message="Genel güven skoru düşük",
            meta={"overall_confidence": out["overall_confidence"]}
        )

    return out
