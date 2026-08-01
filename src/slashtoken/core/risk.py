"""Conservative local language and high-stakes classification."""

from __future__ import annotations

import re
from dataclasses import dataclass


SUPPORTED_LANGUAGES = frozenset({"zh", "ar", "tr"})


_ARABIC = re.compile(r"[\u0600-\u06ff]")
_CHINESE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_TURKISH_CHARS = re.compile(r"[çÇğĞıİöÖşŞüÜ]")
_LATIN = re.compile(r"[A-Za-z]")

_TURKISH_WORDS = {
    "bir", "bu", "için", "ile", "değil", "lütfen", "nasıl", "neden", "analiz",
    "yazılım", "kod", "hata", "gerekir", "çıktı", "yanıt", "olarak",
}

_ENGLISH_WORDS = {
    "a", "an", "and", "analyze", "answer", "as", "code", "complete", "error",
    "for", "from", "how", "in", "is", "of", "please", "provide", "return", "test",
    "the", "this", "to", "use", "what", "with",
}

_RISK_TERMS: dict[str, tuple[str, ...]] = {
    "medical": (
        "diagnosis", "dosage", "symptom", "medicine", "medical emergency",
        "تشخيص", "جرعة", "أعراض", "دواء", "طوارئ طبية",
        "诊断", "剂量", "症状", "药物", "医疗急救",
        "teşhis", "doz", "belirti", "ilaç", "tıbbi acil",
    ),
    "legal": (
        "legal advice", "lawsuit", "contract liability", "criminal charge",
        "استشارة قانونية", "دعوى قضائية", "مسؤولية تعاقدية",
        "法律建议", "诉讼", "合同责任", "刑事指控",
        "hukuki tavsiye", "dava", "sözleşme sorumluluğu", "ceza suçlaması",
    ),
    "financial": (
        "investment advice", "buy this stock", "tax advice", "guaranteed return",
        "نصيحة استثمارية", "اشتر هذا السهم", "نصيحة ضريبية",
        "投资建议", "购买这只股票", "税务建议", "保证回报",
        "yatırım tavsiyesi", "bu hisseyi al", "vergi tavsiyesi", "garantili getiri",
    ),
    "safety": (
        "build a weapon", "make a bomb", "suicide method", "self harm",
        "صنع سلاح", "صنع قنبلة", "طريقة انتحار", "إيذاء النفس",
        "制造武器", "制造炸弹", "自杀方法", "自残",
        "silah yap", "bomba yap", "intihar yöntemi", "kendine zarar",
    ),
}


@dataclass(frozen=True, slots=True)
class RiskAssessment:
    high_stakes: bool
    categories: tuple[str, ...]


def detect_language(text: str) -> str:
    """Detect the three supported languages, English, or an unknown language."""
    if _CHINESE.search(text):
        return "zh"
    if _ARABIC.search(text):
        return "ar"
    words = {word.casefold() for word in re.findall(r"[^\W\d_]+", text, re.UNICODE)}
    if _TURKISH_CHARS.search(text) or len(words & _TURKISH_WORDS) >= 2:
        return "tr"
    if _LATIN.search(text) and len(words & _ENGLISH_WORDS) >= 2:
        return "en"
    return "und"


def classify_risk(text: str) -> RiskAssessment:
    """Flag explicit high-stakes terminology before any transformation occurs."""
    normalized = text.casefold()
    categories = tuple(
        category
        for category, terms in _RISK_TERMS.items()
        if any(term.casefold() in normalized for term in terms)
    )
    return RiskAssessment(high_stakes=bool(categories), categories=categories)
