<div dir="rtl">

# تقرير Dhad vMAX — المرحلة الرابعة: البنية التعاونية الآمنة والقابلة للتوسع

**التاريخ:** 2026-07-22  
**الحالة:** مقبولة محلياً وفق بوابات الاختبار المذكورة أدناه. لم يُنفذ نشر إنتاجي أو اختبار Redis حقيقي متعدد العقد في هذه البيئة.

## النتيجة

استُبدل CRDT الحرفي المخصص كلياً بمحرك `pycrdt` المبني على Rust/Yrs وبروتوكول Yjs الثنائي. أصبحت الوثيقة تنتج state vectors وmissing updates وfull-state updates وsticky indexes متوافقة مع Yjs، مع تفعيل garbage collection في Yrs. أثبت اختبار متبادل أن Python/Yrs يطبق update أنشأه Yjs وأن Yjs يطبق update أنشأه Dhad. يولّد Yrs `client_id` مستقلاً لكل replica حتى لو تشابه `site_id`، وبقيت إزاحات Dhad العامة بوحدات Unicode scalar عبر حد تحويل صريح.

أضيف مهاجر أحادي الاتجاه لحالات RGA القديمة: يحفظ النص المرئي من snapshot القديمة ثم يعيد إنشاء Yjs state، ويرفض أي snapshot تحتوي pending operations حتى لا يفقد تعارضاً بصمت. لا تبقى خوارزمية RGA القديمة في مسار التحرير أو الدمج.

## Redis والتعافي

- `RedisSyncBackend` يكتب كل frame إلى Redis Stream قبل نشرها عبر Pub/Sub.
- Pub/Sub هو مسار الكمون المنخفض بين workers/nodes؛ Stream هو سجل at-least-once ومصدر resume cursors.
- latest encrypted snapshot محفوظة بصورة مستقلة، ويُستأنف tail بعدها عند غياب cursor أو تقادمها.
- الاسترداد paged ولا يحمّل journal كاملة في الذاكرة.
- إذا انقطع Pub/Sub، يحتفظ listener بآخر cursor وصل إلى الغرفة، يستعيد الفجوة من Stream، ثم يعيد الاشتراك مع exponential backoff وjitter.
- أضيف Redis 8 إلى Compose مع AOF `everysec` وhealthcheck وvolume دائمة، ويُختار Redis تلقائياً عند وجود `DHAD_REDIS_URL`.
- أوقف Gunicorn `preload_app` كي تُنشأ موارد Redis/async locks بعد fork داخل كل worker.

## بروتوكول WebSocket والمرونة

انتقل wire protocol إلى binary v4. يقرأ الخادم magic/version/kind والـcursor/مرسل المضافين منه فقط؛ document updates وsnapshots تبقى bytes معتمة ولا تُحوّل إلى JSON أو Base64. رسائل JSON النصية الخاصة بالعمليات القديمة تُرفض. key announcements العامة الموقعة هي استثناء bootstrap غير سري؛ مفاتيح الغرفة نفسها تُرسل داخل envelopes مشفرة.

لكل peer mailbox محدودة وwriter task مستقلة مع send timeout. fanout يضع frame في الطوابير من دون انتظار socket I/O، ويُسقط peer بطيئاً وحده عند امتلاء طابوره. توجد حدود bytes والغرفة، token bucket لكل اتصال، فحص Origin، ومصادقة WebSocket بمفتاح API عند تفعيل مفاتيح الخادم. يحتفظ العميل بآخر Redis cursor ويعيد الاتصال بـfull-jitter exponential backoff.

## E2EE وإدارة epochs

- هوية طويلة الأجل Ed25519؛ يجب أن يزود التطبيق provider ببصمات الأعضاء الموثوقة.
- X25519 لكل epoch وHKDF-SHA-256 لاشتقاق مفاتيح AES-256-GCM اتجاهية.
- قائد الغرفة يولد group epoch key عشوائية ويوزعها لكل عضو داخل قناة X25519 موثقة.
- updates وsnapshots تُشفّر مرة واحدة بمفتاح مشتق لكل مرسل، وتُوقّع Ed25519 لمنع عضو يملك group key من انتحال عضو آخر.
- nonce فريد من `(epoch, sequence)`، وAAD يربط الغرفة والمرسل والمستلم/البث والـsequence.
- نافذة replay محدودة تسمح بوصول فريد خارج الترتيب وترفض التكرار؛ provider يتجاهل النسخ الموثقة الناتجة عن at-least-once قبل وصولها إلى Yjs.
- تغيير X25519 داخل epoch نفسه مرفوض، وإعادة الإعلان المطابقة idempotent ولا تصفر replay state.
- تدوير epoch يقوده العضو المثبت، ويجبر إعادة الإعلان وإعادة توزيع group key. ينشر القائد encrypted full-state checkpoint دورياً قبل تقليم Stream.

## بوابات القبول والأدلة

- Python الكامل مع التحذيرات أخطاء: `1788 passed, 1 skipped`.
- اختبارات Phase 4 المركزة: Yrs/Yjs convergence، state vectors، migration، Redis Streams/PubSub، استرداد gap، cross-node hubs، slow-peer eviction، rate limits، Origin/API auth، وASGI resume كلها خضراء.
- JavaScript/WASM: `37 passed`، منها X25519/AES-GCM/Ed25519، tamper/replay، group key، epoch rotation، secure Yjs provider، snapshots، backoff، مع بقاء اختبارات ONNX وpacked ABI خضراء.
- Rust: `16 passed`، و`cargo fmt --check` و`cargo clippy --all-targets -- -D warnings` نظيفان.
- Ruff: `ruff check .` نظيف، وملفات المرحلة تمر `ruff format --check`.
- الاعتماديات: `pip check` نظيف و`npm audit --omit=dev --audit-level=high` أعاد صفر ثغرات.
- بناء wheel وتثبيته في بيئة نظيفة نجحا، بما في ذلك Yrs وإنشاء FastAPI ومسار WebSocket v4.

## قياس التوسع المحلي

اختبار اصطناعي أنشأ 2,000 mailbox اتصال في غرفة واحدة ثم قاس enqueue لـ1,999 مستلماً مع ciphertext بحجم 1,024 بايت خلال 30 دورة:

| المقياس | النتيجة |
|---|---:|
| fanout enqueue p50 | 0.451 ms |
| fanout enqueue p95 | 0.465 ms |

هذا القياس يثبت أن hot fanout لا ينتظر socket I/O ويستوعب آلاف mailboxes داخل العملية في البيئة المرجعية. لا يشمل زمن الشبكة أو Redis أو التشفير، ولذلك ليس ادعاء throughput إنتاجي أو ضماناً عابراً للأجهزة.

## الحدود والمخاطر المفتوحة

- اختبارات Redis استعملت `fakeredis` لأن `redis-server` وDocker غير متاحين في البيئة الحالية؛ يلزم قبل الإنتاج اختبار chaos/load متعدد العقد على Redis حقيقي مع TLS/ACL وقياسات p95/p99.
- E2EE بلا key escrow: انضمام عضو جديد أو تدوير العضوية يحتاج قائداً موثوقاً متصلاً. مصدر العضوية والبصمات الموثوقة مسؤولية طبقة الهوية في التطبيق.
- X25519/Ed25519 مطلوبان من WebCrypto؛ العميل يفشل مغلقاً في runtime لا يدعمهما بدلاً من downgrade غير آمن.
- بروتوكول JSON القديم انتهى عمداً؛ العملاء يجب أن ينتقلوا إلى `dhad-sync-v4`. snapshots القديمة تُهاجر، لكن pending operations القديمة تُرفض وتحتاج تسوية قبل الترقية.

</div>
