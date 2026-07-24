# ضاد في المتصفح — WASM Demo

<div dir="rtl">

عرض ذاتي الاكتفاء للنواة الحتمية المحمولة (`dhad-core-rs`) داخل WebAssembly: ترميز، تجزئة جمل، تطبيع، و130 قاعدة حرفية بنفس دلالات حدود الكلمات في محرك بايثون، مع حلّ التعارضات بخوارزمية sweep-line المنقولة. يضيف المسار الاختياري نموذجًا عصبيًا كمّيًا داخل Web Worker. النموذج المثبت موجود محليًا داخل الحزمة، والنص لا يغادر المتصفح إطلاقًا.

## PWA والعمل دون اتصال

يسجّل التطبيق `service-worker.js` كوحدة ES ويثبت إصدارًا ذريًا واحدًا من app shell ومحرك WASM والقواعد والقاموس وONNX Runtime والنموذج الكمّي. تستعمل الأصول الكبيرة غير القابلة للتغيير CacheFirst، بينما تستعمل واجهة التطبيق StaleWhileRevalidate مع `offline.html` كخيار أخير للتنقل. بعد اكتمال التثبيت يعمل المحرك الحتمي والاستدلال العصبي WebGPU/WASM بلا شبكة.

يحفظ `storage/db.js` المستندات وتحديثات Yjs وoutbox والقواميس الشخصية والإعدادات في IndexedDB ذات مخطط مَنسوخ ومعاملات ذرية. يطلب التخزين الدائم، وينظف فقط السجلات المعلّمة بأنها compacted/acknowledged عند امتلاء الحصة، ثم يعيد المحاولة مرة واحدة. يستأنف `OutboxRecovery` الإرسال عند حدث `online` أو Background Sync.

انتقل التدقيق الحتمي الحي إلى `analysis/analysis-worker.js`. يبقى DOM المحرر نصيًا ثابتًا وتحمل `editor-overlay` العلامات في طبقة GPU composited؛ تُبنى القوائم الكبيرة على دفعات إطارات، ويصبح الشريط الجانبي افتراضيًا بعد 80 ملاحظة.

## الملفات

`dhad_core.wasm` مسار السرعة (`wasm-opt -O3`) · `dhad_core.small.wasm` مسار الحجم (`wasm-opt -Oz`) · `rules.json` حزمة القواعد · `dhad-core.js` الجسر اليدوي (بلا wasm-bindgen) · `manifest.json`/`service-worker.js` غلاف PWA · `storage/db.js` التخزين المحلي · `index.html`/`app.js` الواجهة · `bench.mjs` و`packed_bridge_test.mjs` بوابات التكافؤ والملكية · `abi_benchmark.mjs` قياس A/B مقابل جسر JSON السابق · `browser_proof.mjs` برهان Chromium حقيقي.

المسار الحار لـ`check()` لا يُنشئ JSON ولا ينسخ response: ينشئ الجسر وثيقة دائمة بمقبض ذي generation، ويكتب UTF-8 مباشرةً إلى ذاكرة WASM عبر `TextEncoder.encodeInto()`، ثم يقرأ سجلات `dhad-packed-diagnostics-v1` من `DataView` و`Uint8Array` مملوكين للوثيقة. يمكن للتكامل المتقدم استعمال `engine.createDocument(text).analyzeView()` للوصول إلى `recordsBytes` و`stringsBytes` مباشرةً. تصبح الـview قديمة بعد أي `update()` أو `analyzeView()` لاحق، ويجب إنهاء الوثيقة بـ`dispose()`؛ توجد `FinalizationRegistry` كشبكة أمان وليست بديلاً عن الإنهاء الصريح.

النواة المحمولة تشمل الآن التحليل الصرفي الكامل (المعجم، السوابق واللواحق، الأوزان والترتيب) والتحليل النحوي الحتمي (العلاقات، الإعراب المرشح، وفحوص المطابقة والحكم) عبر الدوال `analyze()` و`parse()` و`syntaxCheck()`. كما يضم `check()` الملاحظات النحوية تلقائيًا قبل حل تعارض المساحات.

كل الإزاحات الصادرة من المحرك هي إزاحات محارف Unicode scalar المطابقة لفهرسة Python وليست بايتات UTF-8 أو وحدات UTF-16. يوفر الجسر `scalarToUtf16()` و`utf16ToScalar()` عند التكامل المباشر مع DOM.

## الاستدلال العصبي الخاص

تنتقل بدائل التحليل الصرفي من Rust إلى `neural-worker.js` في دفعات متصلة لا تتجاوز 64 موضعًا. يشغّل العامل `onnxruntime-web` مع أولوية WebGPU واحتياط WASM SIMD، ويطبق WordPiece وmean pooling وcosine logits وstable softmax وبوابتي الثقة والهامش. لا يستطيع العامل توليد نص: النتيجة المقبولة يجب أن تحمل فهرسًا ومعرّفًا مطابقين تمامًا لأحد مرشحي Rust، وإلا يرفضها العميل. العتبة الإنتاجية `0.999`، ولذلك يكون الامتناع هو السلوك الافتراضي عند الشك.

راجع [`neural/README.md`](neural/README.md) لعقد النموذج، والتقطير teacher/student، وإعادة توليد fixture الاختباري.

## التشغيل

```bash
# عرض تفاعلي
python -m http.server -d web_demo 8080   # ثم افتح http://localhost:8080

# برهان التكافؤ والقياس (طرفية)
node web_demo/bench.mjs
node web_demo/packed_bridge_test.mjs
node web_demo/abi_benchmark.mjs
node web_demo/browser_proof.mjs

# اختبارات ONNX/Worker/الحراسة وإعادة تثبيت runtime المحلي
cd web_demo
npm install
npm run vendor:ort
npm test
```

لإعادة توليد حزمة الصرف، وتشغيل اختبارات Rust، وبناء WASM ونسخها إلى العرض:

```bash
rustup target add wasm32-unknown-unknown
brew install binaryen  # أو وفّر WASM_OPT لمسار wasm-opt
tools/build_wasm_core.sh
```

## إعادة البناء

```bash
DHAD_PYTHON=venv/bin/python tools/build_wasm_core.sh
```

بايثون يبقى المرجع: أي تغيير في القواعد أو `dhad/text.py` يستلزم إعادة توليد الذهبي وحزمة القواعد، و`cargo test` يضمن التكافؤ.

</div>
