<div dir="rtl">

# تقرير Phase 5 وإكمال Dhad vMAX

**التاريخ:** 2026-07-22  
**البيئة:** macOS على Apple M3 Max، Python 3.14.6، Rust 1.97.1، Node 26.5.0، Chromium/Playwright.  
**الحالة:** مكتملة وفق بوابات القبول المحلية أدناه.

## السياق المحمّل

بُنيت المرحلة الخامسة فوق العقود المثبتة في تقارير المراحل 1–4: حل المقاطع `O(n log n)` ومسح Aho–Corasick، واجهة WASM الثنائية الدائمة عديمة نسخة الاستجابة، عامل ONNX بترتيب WebGPU ثم WASM SIMD، وYrs/Yjs مع بروتوكول WebSocket v4 وRedis Streams/PubSub وE2EE. لم تُستبدل هذه العقود أو تُضعف.

## PWA والعمل الكامل دون اتصال

- يثبت `web_demo/service-worker.js` قائمة إصدار واحدة بـ`cache.addAll()`؛ فشل أي أصل يفشل install بالكامل ويبقي العامل السابق مسيطراً.
- تستعمل ملفات WASM والقواعد والقاموس وONNX Runtime والنموذج الكمّي CacheFirst، ويستعمل app shell أسلوب StaleWhileRevalidate مع fallback للتنقل.
- أضيف `manifest.json` بنطاق نسبي قابل للنشر، وأيقونتا PNG بقياسي 192 و512 مع `any maskable`، وصفحة `offline.html`.
- أصبح نموذج INT8 مثبتاً محلياً في `web_demo/models/model_int8.onnx`: الحجم 135,080,470 بايت، والبصمة `d21142a1421d3cda61b7d016d1170e5d7ab682c62ce4f0609c1ce3d579676186` المطابقة للـmanifest.
- أثبت Chromium أن reload بعد `context.setOffline(true)` أعاد 130 قاعدة، والنموذج نفسه، وموفر WebGPU، وست ملاحظات، والمستند المحفوظ، مع صفر أخطاء أو تحذيرات console.

## محرك IndexedDB

- أضيف `web_demo/storage/db.js` بقاعدة `dhad-vmax` ذات إصدار صريح ومخازن: `documents` و`yjsUpdates` و`outbox` و`dictionaries` و`settings`.
- يدعم wrapper معاملات متعددة المخازن مع abort/rollback حقيقي، ورفض callbacks غير المتزامنة التي قد تفقد نشاط المعاملة.
- يحفظ تحديثات Yjs كبايتات، ويستأنف outbox عند حدث `online` أو رسالة Background Sync، مع exponential retry metadata.
- يطلب التخزين الدائم ويقيس الحصة. عند `QuotaExceededError` يحذف فقط تحديثات Yjs المعلّمة `compacted` ورسائل outbox المعلّمة `acknowledged`، ثم يعيد الكتابة مرة واحدة؛ لا يحذف مستندات المستخدم أو قواميسه أو إعداداته.
- أثبت المتصفح استعادة مستند IndexedDB نفسه بعد reload دون شبكة.

## خط 60fps والعرض

- انتقل التدقيق الحتمي الحي إلى `analysis/analysis-worker.js`، فلم تعد عمليات WASM/parse الطويلة تعمل على خيط الواجهة أثناء الكتابة.
- بقي محرر `contenteditable` نصياً ثابتاً، وانتقلت التموجات إلى `editor-overlay` منفصلة تستخدم `contain` و`will-change` و`translate3d`؛ لا يعاد بناء DOM المحرر ولا موضع المؤشر بعد كل فحص.
- تُقرأ القياسات قبل الكتابات، وتُجمّع تحديثات scroll في `requestAnimationFrame`، وتُبنى العلامات الكبيرة على دفعات لا تتجاوز 320 segment لكل إطار.
- يصبح الشريط الجانبي افتراضياً بعد 80 ملاحظة مع overscan صفّين.
- اختبار ضغط حقيقي: 19,500 محرف و2,500 ملاحظة، ظهرت 7 بطاقات sidebar فقط مع بقاء 2,500 علامة صحيحة، ولم يرصد Long Task API أي مهمة تتجاوز 50ms. كان الاختبار الأحمر الأول قد كشف 65ms قبل تجزئة العلامات وتصحيح قيد Flex، ثم أصبح أخضر.

## بوابات القبول

| البوابة | النتيجة |
|---|---:|
| `python -m pytest -W error` عبر `venv/bin` | 1788 passed، 1 skipped، 32.17s |
| `cargo test` | 16 passed، 0 failed |
| `cargo clippy -- -D warnings` | exit 0، بلا تحذيرات |
| `npm test` | 53 passed، 0 failed |
| Chromium متصل/غير متصل | WASM + WebGPU/ONNX + IndexedDB، console نظيف |
| ضغط واجهة 19,500 محرف | 0 long tasks فوق 50ms |

## Wheel والتغليف

- بُنيت `dist/dhad-1.0.0rc1-py3-none-any.whl` من المصدر؛ الحجم 484,247 بايت.
- ثُبتت wheel مع extras `server,production` داخل venv معزولة في `/private/tmp` ومن خارج شجرة المصدر.
- نجح `pip check`، وأثبت الاستيراد الإصدار `1.0.0rc1` و22 route و`CrdtDocument` المبني على Yrs.
- حزمة التسليم هي `dhad-vMAX.zip`. يستبعد الأرشيف فقط بيئات التطوير والمخرجات القابلة لإعادة البناء (`venv` و`node_modules` وRust `target` والكاشات وملفات Playwright) ويضم النموذج المحلي وWASM والمصدر والاختبارات والتقارير وwheel.
- كان `SHA256SUMS.txt` الأصلي ملفاً خارجياً لتجنب المرجع الدائري، ويغطي أرشيف vMAX وwheel والنموذج العصبي. حُفظت تلك البصمات التاريخية في `reports/release-archives/SHA256SUMS-vMAX-original.txt` بعد تنظيف مستودع المصدر.

## حدود باقية معلنة

- اختبار Redis الحقيقي متعدد العقد مع chaos/load وTLS/ACL ما زال مطلوباً قبل نشر تعاوني عام؛ اختبارات Phase 4 المحلية استعملت fakeredis كما وثّق تقريرها.
- WebGPU ليس مضموناً على كل جهاز؛ fallback المحلي إلى WASM SIMD جزء من العقد المختبر.
- الإملاء الصوتي Web Speech قدرة متصفح اختيارية، وليس جزءاً من ضمان NLP المحلي غير المتصل.

</div>
