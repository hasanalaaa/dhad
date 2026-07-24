<div dir="rtl">

# خطوات النشر على GitHub (المرة الأولى)

## 1) إنشاء المستودع

```
gh repo create dhad-project/dhad --public --source . --push
```

أو يدويًا: أنشئ منظمة `dhad-project` ثم مستودع `dhad` عام، ثم:

```
git remote add origin https://github.com/dhad-project/dhad.git
git push -u origin main
```

## 2) قائمة ما قبل الإعلان

- [ ] استبدل ملف LICENSE بالنص الكامل لرخصة AGPL-3.0 (زر Add license في GitHub)
- [ ] فعّل GitHub Actions (يعمل تلقائيًا مع أول push — تأكد أن CI أخضر)
- [ ] فعّل Issues وDiscussions
- [ ] أضف Topics للمستودع: `arabic` `nlp` `grammar-checker` `spellcheck` `languagetool` `rtl`
- [ ] ارفع لقطة شاشة المحرر في README (docs/screenshot.png)
- [ ] وسم أول إصدار: `git tag v0.1.0 && git push --tags`
- [ ] أنشئ Release مع ملاحظات الإصدار

## 3) الإعلان

- حسوب I/O + مجتمعات المطورين العرب (تيليغرام/ديسكورد)
- Show HN بعنوان: "Show HN: Dhad – open-source Grammarly for Arabic (LanguageTool-compatible)"
- ويكيبيديا العربية (ميدان التقنية) — المحررون أكثر من يحتاج الأداة
- r/arabs و r/learn_arabic

## 4) الخدمة التجريبية العامة (اختياري)

```
docker build -t dhad .
docker run -d -p 8010:8010 --restart unless-stopped dhad
```

ضعها خلف Nginx/Caddy مع نطاق مثل `demo.dhad.io`.

</div>
