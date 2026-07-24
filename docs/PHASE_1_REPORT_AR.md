<div dir="rtl">

# تقرير إغلاق Phase 1 — بنية النص العربي وRule Engine v2

**الإصدار:** `0.3.0`  
**الحالة:** مكتملة  
**التاريخ:** 2026-07-21

## ما نُفّذ

- Tokenizer فاقد للصفر مع إزاحات أصلية، ويصنّف العربية واللاتينية والأرقام والروابط والبريد والكود والوسوم والإشارات والرموز.
- Sentence segmenter يراعي علامات الترقيم العربية والاختصارات والأعداد العشرية والقوائم.
- أربعة أوضاع Normalization صريحة: `strict` و`lookup` و`search` و`aggressive`.
- Rule Engine v2 مع JSON Schema رسمي وإصدار `schema_version: 2`.
- ترحيل 141 قاعدة مدمجة إلى Schema v2 صراحةً.
- ستة أنواع قواعد: `literal` و`regex` و`token_sequence` و`context` و`exception` و`document`.
- حقول `confidence` و`priority` و`autofix` و`tags` و`references` و`profiles`.
- حل تعارض عالمي يعتمد الأولوية والثقة والشدة والنطاق.
- Suppression محلي للقاعدة والكلمة والسطر والمستند، عبر API وCLI.
- إظهار provenance والثقة في JSON وواجهة LanguageTool-compatible API.

## بوابة الخروج

| المعيار | النتيجة |
|---|---:|
| حالات Unicode/offsets | 1,024 حالة مستقلة |
| أخطاء offset في الاختبارات | 0 |
| القواعد المارة على Schema validation | 141/141 |
| الاختبارات الكلية | 1,379 ناجحة |
| P95 لنص 500 حرف | 1.65ms تقريبًا |
| حد المرحلة | أقل من 75ms |
| Seed benchmark | Precision 1.0 / Recall 1.0 / F0.5 1.0 على 22 حالة صغيرة |

> نتيجة Seed ليست ادعاء دقة إنتاجية؛ Phase 2 ستبني Gold corpus مستقلًا واسعًا.

## الملفات المركزية

- `src/dhad/text.py`
- `src/dhad/rules.py`
- `src/dhad/match.py`
- `src/dhad/suppression.py`
- `src/dhad/data/rule.schema.json`
- `tests/test_phase1_text.py`
- `tests/test_phase1_rules_v2.py`

</div>
