# Dhad vMAX Omni — Evolution Report

تقرير هندسي للإصدار `dhad-vMAX-Omni.zip`، أُنجز في 23 يوليو 2026. يصف هذا التقرير التغييرات المنفذة فعلياً، ولا يحوّل القيود البيئية أو الاختبارات غير المنفذة إلى ادعاءات نجاح.

## 1. Core, Rust, and WASM

- شُدّدت واجهة WASM الخام عبر `#![deny(unsafe_op_in_unsafe_fn)]`، مع حصر كل عملية `unsafe` داخل كتلة موثقة ومحددة النطاق.
- بقي ABI صفري الاعتماد على `wasm-bindgen` ومحافظاً على الذاكرة الخطية والأصول الثنائية الموقعة في `SHA256SUMS.txt`.
- بقيت ملفات Rust/WASM والـONNX الأصلية محفوظة بلا استبدال أو ضغط تحويلي.
- فحص workspace في التدقيق أصبح صريحاً: يمر عبر `cargo metadata` عند توفر Cargo، ويُسجل `skipped` بشفافية عند غيابه.

## 2. Neural Engine and Edge AI

- أصبحت تهيئة runtime ذرّية ومشتركة بين الطلبات المتزامنة؛ لا تُنشأ جلسات ONNX مكررة عند السباق.
- أُعيد بناء super-batching لتخصيص tensors النهائية مرة واحدة والكتابة إليها مباشرة، بدلاً من إنشاء دفعات وسيطة لكل طلب.
- أضيف كشف مبكر لمعرفات الطلبات المكررة والتحقق قبل التخصيص.
- أصبح تحميل الأصول الموقعة يدعم `AbortSignal` ويستخدم buffer مسبق الحجم عند توفر `Content-Length` الصحيح.
- إلغاء runtime أثناء التهيئة يوقف fetch الجاري، وtimeout أو crash للـWorker يعزل العامل وينظف pending operations ويُنشئ عاملاً جديداً للمحاولة التالية.
- صُنفت أخطاء الشبكة المؤقتة كحالات قابلة لإعادة المحاولة، بينما تبقى أخطاء integrity/contract دائمة وصريحة.

## 3. Backend, Sync, and Security

- أضيف حد توازي قابل للضبط للتحليل CPU-bound عبر `DHAD_MAX_CONCURRENT_ANALYSES` لمنع تضخم الذاكرة تحت burst traffic مع إبقاء event loop متجاوباً.
- أصبحت استعادة Redis Stream محدودة بعدد سجلات صريح عبر `DHAD_SYNC_MAX_RECOVERY_RECORDS`، مع close code ثابت عند تجاوز الحد.
- أضيف high-water cursor لكل peer لإسقاط الرسائل المكررة التي قد تصل من live fanout وstream recovery في الوقت نفسه.
- أصبحت مهام WebSocket والإغلاق cancellation-safe، ولا يتسرب `CancelledError` من الإغلاق الطبيعي.
- فُرض backpressure على الإدخال والإخراج و`bufferedAmount` في عميل WebSocket، وأصبحت معالجة frames متسلسلة حسب ترتيب السلك.
- لا يتقدم durable cursor إلا بعد نجاح المستهلك في commit الرسالة.
- أُغلقت حالات HTTP request smuggling برفض تكرار `Content-Length` ورفض جمعه مع `Transfer-Encoding`.
- أصبحت ذاكرة token-bucket rate limiter محدودة بعدد هويات قابل للضبط مع eviction حتمي.
- أُصلح مسار تجاوز حجم body الذي كان يستدعي error sender بمعاملات غير صحيحة.

## 4. CRDT, E2EE, and Storage

- أصبحت تسلسلات Yjs في IndexedDB تُخصص داخل transaction ذرّية مشتركة بين `settings` و`yjsUpdates`، فلا تعتمد على counter محلي للعملية.
- تستخدم قراءة outbox فهرس `nextAttemptAt` وحداً صريحاً للدفعة بدلاً من `getAll` الكامل.
- أصبحت سلسلة إرسال Yjs ذاتية التعافي بعد فشل مؤقت، ولا تسمّم كل الإرسالات اللاحقة أو تنتج unhandled rejection.
- أضيفت حدود صارمة لأحجام base64url، أطوال مفاتيح Ed25519/X25519 والتواقيع، وعدد وحجم key packages المعلقة.
- رفض epoch/sequence الصفرية يحدث قبل العمل التشفيري، وأخطاء replay/missing-key/epoch لها رموز مستقرة بدلاً من مطابقة النصوص.
- يُصفّر key material القديم قبل استبداله، وتُحد pending packages لمنع نمو الذاكرة غير المحدود.

## 5. PWA, Frontend, and Accessibility

- فُصل app shell وRust/rules عن الحزمة العصبية التي تتجاوز 150MB؛ تثبيت PWA لم يعد يفشل بسبب تنزيل النموذج الكامل دفعة واحدة.
- تُخزن الأصول العصبية عند الطلب ويمكن تدفئتها برسالة Service Worker مع نتيجة صريحة.
- أصبحت تحديثات Service Worker مرتبطة بدورة حياة fetch، مع canonical cache keys وإزالة caches القديمة.
- حافظ overlay على segmentation سريع، batching عبر animation frames، وvirtualization لقائمة الملاحظات.
- أضيفت حالات ARIA ديناميكية للمحرر، أوضاع العرض، المرشحات، التسجيل الصوتي، التنبيهات، ومربعات التفاصيل.
- أصبحت أخطاء استعادة IndexedDB عند عودة الاتصال مراقبة ومبلّغة وقابلة لمحاولة لاحقة.

## 6. Tests and Developer Experience

- أضيفت اختبارات انحدار للـdedup، recovery budgets، WebSocket close policy، queue ordering، cursor commit، worker crash/retry، abortable model loading، duplicate batch IDs، E2EE zero sequences، key zeroization، PWA asset tiers، وحدود IndexedDB.
- جرى تحديث التدقيق الحتمي إلى مخطط `dhad-vmax-omni-audit-v1`، مع inventory لكل ملف وحجمه وSHA-256 وتصنيفه.
- بقي Git LFS مفعلاً لملفات ONNX الكبيرة، وبقيت CI/Dependabot وبوابات Python/Rust/WASM/Web موجودة.

## 7. Declared Validation Boundary

- الاختبارات المتاحة محلياً اجتازت بالكامل كما هو موثق في `VMAX_OMNI_FINAL_VALIDATION.md`.
- لم يتوفر `cargo/rustc` في بيئة التغليف، لذلك لم يُدعَ أن Rust أُعيد تشغيله محلياً.
- لم تتوفر `pycrdt`, `fakeredis`, `yjs`, أو `fake-indexeddb` محلياً، ولذلك سُجلت suites التابعة لها كغير منفذة، مع بقائها في المستودع وCI.
- لا يشكل هذا التقرير تدقيق اختراق مستقل أو إثبات SLO إنتاجي متعدد العقد.
