<div dir="rtl">

# دليل المساهمة في ضاد

أهلًا بك! ضاد مشروع مجتمعي، وأثمن المساهمات فيه لا تحتاج برمجة أصلًا.

## 1) ساهم بقاعدة لغوية (لا يحتاج برمجة)

القواعد ملفات YAML في `src/dhad/data/rules/`:

- `hamza.yaml` — أخطاء الهمزات
- `taa_marbuta.yaml` — التاء المربوطة والهاء
- `alef_maqsura.yaml` — الألف المقصورة والياء
- `common_words.yaml` — كلمات وعبارات شائعة الخطأ
- `style.yaml` — تحسينات الأسلوب

### بنية القاعدة

<div dir="ltr">

```yaml
- schema_version: 2
  id: MEANINGFUL_ID
  type: literal                  # literal | regex | token_sequence | context | exception | document
  category: spelling            # spelling | grammar | style | punctuation | dialect
  severity: error               # error | warning | hint
  confidence: 0.99              # من 0 إلى 1
  priority: 80                  # أولوية حل التعارض
  autofix: true                 # لا تفعّله إلا للتصحيح القطعي الآمن
  profiles: [default]
  tags: [spelling]
  references: ["مرجع لغوي إن وجد"]
  pattern: "الكلمة الخاطئة"
  prefixes: true
  suggestion: "الصواب"
  message: "رسالة قصيرة للمستخدم"
  explanation: "لماذا هذا خطأ؟"
  examples:
    bad: "جملة تحتوي الخطأ"
    good: "الجملة الصحيحة"
```

</div>

### القواعد الذهبية

1. **المثالان إلزاميان** — CI يرفض أي قاعدة بلا مثالين، ويشغّلهما آليًا.
2. **تجنب الالتباس**: لا تكتب قاعدة تلتقط كلمة صحيحة في سياق آخر
   (مثال: لا تلتقط «علي» لأنه اسم عَلَم — اجعلها `hint` إن أصررت).
3. **درجة الشدة بأمانة**: خطأ إجماعي = `error`، خلاف لغوي أو أسلوب = `warning`/`hint`.
4. **اشرح** — حقل `explanation` هو ما يجعل ضاد معلمًا لا مصححًا فقط.
5. **وثّق الثقة** — لا تمنح قاعدة ملتبسة `confidence` مرتفعًا ولا تفعّل `autofix`.
6. **الـSchema إلزامي** — كل قاعدة تمر تلقائيًا على `data/rule.schema.json`.

## 2) ساهم بكود

<div dir="ltr">

```bash
git clone https://github.com/dhad-project/dhad && cd dhad
pip install -e ".[dev]"
pytest                 # يجب أن تبقى المجموعة كاملة خضراء
ruff check src tests   # تدقيق الكود
```

</div>

- الفحوص البرمجية (عدد ومعدود، ترقيم…) في `src/dhad/checks.py` ولها اختبارات في `tests/test_checks.py`.
- أي فحص جديد يجب أن يعيد كائنات `Match` بإزاحات تشير إلى النص الأصلي حرفيًا.

## 3) بلّغ عن إنذار كاذب

أزعجك التقاط خاطئ؟ افتح Issue بعنوان `[FP]` مع الجملة — الإنذارات الكاذبة أخطر عندنا من الأخطاء الفائتة، لأنها تفقد الثقة بالأداة.

## سير العمل

1. Fork ثم فرع باسم واضح: `rule/hamza-xxx` أو `fix/yyy`
2. تأكد أن `pytest` أخضر
3. افتح Pull Request واشرح القاعدة اللغوية بمصدر إن أمكن (معجم، مرجع نحوي)

شكرًا لأنك تجعل العربية الرقمية أفضل 🌿

</div>
