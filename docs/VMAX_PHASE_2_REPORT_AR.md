# تقرير Dhad vMAX — المرحلة الثانية: Rust/WASM Hyper-Optimization

تاريخ القياس: 2026-07-22. البيئة المرجعية: Apple M3 Max، Rust 1.97.1، Node 26.5.0، Binaryen 131. الأرقام قياسات محلية وليست ضماناً عابراً للأجهزة.

## النتيجة

انتقل مسار التدقيق الحار من `TextEncoder.encode → dc_alloc → JSON stringify/parse → copy → dc_free` إلى ABI ثنائي دائم:

1. `dc_doc_create(ptr,len)` ينشئ وثيقة بمقبض 32-bit يجمع slot وgeneration؛ لا يعاد استعمال slot بعد استنفاد generation كي لا يصبح أي stale handle صالحاً مجدداً.
2. `dc_doc_update(handle,ptr,len)` يعيد استعمال سعة `String` وسعة result السابقة، يزيد revision، ويلغي النتيجة القديمة.
3. `dc_doc_analyze(handle)` يشغل القواعد والنحو، ويستعمل `dedupe_indices()` كي لا يستنسخ `Vec<RuleMatch>` وسلاسله لحل التعارض.
4. `dc_doc_result_ptr/len` يعيدان view غير مالكة لجدول ثنائي مملوك للوثيقة؛ لا تخصيص أو نسخ أو `dc_free` للـresponse على جهة JavaScript.
5. الجسر يكتب النص مباشرةً في input arena قابلة للنمو عبر `TextEncoder.encodeInto()`؛ لا ينشئ `Uint8Array` وسيطاً في كل فحص.

بقيت دوال الصرف/التجزئة/الـparse العامة القديمة متوافقة مع عقد JSON الحالي، لكن `check()` والواجهة التفاعلية انتقلا كلياً إلى packed ABI ولا يستدعيان `dc_check` القديم. أبقي `dc_check` لتشغيل قياس A/B متطابق داخل الثنائية نفسها، لا كمسار إنتاجي للتدقيق.

## صيغة `dhad-packed-diagnostics-v1`

- Header ثابت 56 بايت: magic/version/أحجام الجداول، أعداد raw/resolved، offsets، الطول الكلي، وrevision.
- Record ثابت 80 بايت: أربعة مراجع UTF-8، offset/length بوحدات Unicode scalar، confidence `f64`، priority `i32`، أربعة string-list spans، severity مرمّزة، وautofix.
- List entry ثابت 8 بايت يشير إلى string table موحّد؛ raw records تسبق resolved records.
- يفحص جسر JS كل حدود الجداول والمراجع قبل decoding، ويعرض `recordsBytes` و`stringsBytes` كـTypedArray views مباشرة.
- صلاحية view تنتهي عند update/analyze/destroy أو تغير جيل view. `dispose()` حتمي، وWeakRef/FinalizationRegistry شبكة أمان عند إسقاط wrapper دون إنهاء.

اختبار `packed_abi.rs` يثبت magic/version/layout، UTF-8 العربي، الإزاحة والطول، `f64`/priority، severity/autofix، البدائل المتعددة، تطابق raw/resolved، revision، update، destroy، ورفض المقبض القديم. واختبار `packed_bridge_test.mjs` يثبت view المباشر، invalidation، ثبات scratch document، وعدم تسريب الوثائق.

## الحجم

كان السبب الأكبر للحجم JSON صرفياً خاماً حجمه 3,822,108 بايت داخل قسم data. أصبح exporter يولد zlib deterministic بحجم 131,925 بايت، يُفك مرة واحدة أثناء `dc_warmup()` وتغطي اختبارات الصرف والنحو تكافؤه.

| المسار | قبل `wasm-opt` | النهائي | gzip-9 | التحسين |
|---|---:|---:|---:|---:|
| fast: LTO + `opt-level=3` + strip + panic abort + `wasm-opt -O3` | 1,705,309 B | 1,570,968 B | 660,747 B | 71.69% أصغر من 5,548,349 B |
| small: LTO + `opt-level=z` + strip + panic abort + `wasm-opt -Oz` | 1,476,766 B | 1,321,133 B | 579,870 B | 76.19% أصغر من 5,548,349 B |

ملف `dhad_core.wasm` هو fast، وتُحفظ النسختان صراحةً في `dhad_core.fast.wasm` و`dhad_core.small.wasm`. سكربت البناء يرفض غياب `wasm-opt`، يتحقق بـ`WebAssembly.validate`، ويفرض حد fast أقل من 2MB وأن يكون small أصغر منه.

## الكمون: A/B داخل الثنائية نفسها

المنهجية: تشغيل packed وJSON القديم بالتناوب في كل iteration، بعد warmup، على الثنائية المحسنة نفسها، مع `deepEqual` كامل للنتائج قبل القياس.

| corpus | packed p50 | JSON p50 | تحسن p50 | packed p95 | JSON p95 |
|---|---:|---:|---:|---:|---:|
| جملة، 55 scalar | 0.0930 ms | 0.1011 ms | 8.03% | 0.1772 ms | 0.1812 ms |
| فقرة، 440 scalar | 0.6335 ms | 0.7335 ms | 13.63% | 0.8134 ms | 0.9267 ms |
| وثيقة، 9,900 scalar | 14.3784 ms | 16.5929 ms | 13.35% | 14.9621 ms | 17.2245 ms |

البيانات الخام في `web_demo/abi-benchmark.json`، وقياسات البناء في `web_demo/wasm-build-metrics.json`.

## بوابات الجودة

- Python: `1767 passed, 1 skipped` مع تحويل التحذيرات إلى أخطاء.
- Rust: 16 اختباراً خضراء؛ `cargo fmt --check` و`cargo clippy --all-targets -- -D warnings` نظيفان.
- JavaScript/WASM: lifecycle/parity للـpacked ABI، وتكافؤ 10/10 مع golden Python، وعقود الصرف والنحو وUnicode scalar خضراء.
- المتصفح الحقيقي: تحميل artifact النهائي بلا أخطاء console، ظهور 130 قاعدة و6 ملاحظات، وتطبيق تصحيح فعلي خفّض العدد إلى 5 وحدّث النص.
- البناء: fast وsmall يمران `WebAssembly.validate` بعد Binaryen، مع بوابات حجم صريحة.
