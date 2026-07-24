# سياسة الأمان | Security Policy

<div dir="rtl">

## الإصدارات المدعومة

| الإصدار | الدعم الأمني |
| --- | --- |
| `1.0.x` (بما فيها `1.0.0-rc1`) | ✅ مدعوم — تصحيحات أمنية فورية |
| `0.13.x` | ⚠️ تصحيحات حرجة فقط حتى صدور `1.0.0` المستقر |
| أقدم من `0.13.0` | ❌ غير مدعوم — يُرجى الترقية |

## الإبلاغ عن ثغرة

**لا تفتح مسألة (Issue) علنية لأي ثغرة أمنية.**

1. استخدم خاصية **GitHub Private Vulnerability Reporting** على مستودع المشروع (Security ‹ Report a vulnerability)، أو راسل المشرفين عبر البريد المذكور في صفحة المشروع مع البادئة `[SECURITY]`.
2. ضمّن: وصف الثغرة، خطوات إعادة الإنتاج، الإصدار المتأثر، التأثير المتوقع، وأي إثبات مفهوم (PoC).
3. ستتلقى إقرارًا بالاستلام خلال **72 ساعة**، وتقييمًا أوليًا خلال **7 أيام**.
4. نلتزم بالإفصاح المنسّق: لن نعلن التفاصيل قبل توفر تصحيح، ونطلب منك المثل. يُنسب الاكتشاف للمبلّغ ما لم يطلب خلاف ذلك.

## النطاق

يشمل النطاق: مكتبة `dhad` بايثون، خادم REST (`dhad serve` / Docker / Gunicorn)، خادم LSP، إضافة المتصفح، مشغّل سطح المكتب، وخط أنابيب القواعد YAML.

خارج النطاق: نماذج LLM الخارجية الاختيارية (Ollama / خوادم OpenAI-متوافقة) وبنيتها التحتية، وهجمات تتطلب وصولًا فيزيائيًا أو صلاحيات جذر مسبقة على جهاز الضحية.

## الضمانات المعمارية الحالية (v1.0.0-rc1)

- **محلي أولًا:** الخادم يستمع افتراضيًا على `127.0.0.1` فقط؛ لا يُرسَل نص المستخدم إلى أي طرف ثالث.
- **قناع PII محافظ على الإزاحات:** البريد والهاتف وURL تُقنَّع قبل جميع طبقات التحليل وتُستعاد بعده؛ لا تصل إلى أي backend عصبي.
- **صفر تسجيل لأجسام الطلبات:** سياسة تسجيل بلا محتوى، مع مرشّح دفاعي لتسرب PII في السجلات.
- **حدود صارمة:** سقف 50,000 حرف للنص، 256KB لجسم الطلب، ومُحدِّد معدل token-bucket غير متزامن (120 طلبًا/60 ثانية افتراضيًا).
- **مصادقة اختيارية:** مفاتيح API عبر `DHAD_API_KEYS` (رؤوس `X-API-Key` أو `Bearer`).
- **WebSocket مقيد:** المصادقة متسقة مع HTTP، وتُطبّق حدود المعدل على إطارات النص والبيانات، مع سقوف صريحة للحجم وbackpressure في العميل.
- **HTTP framing صارم:** تُرفض قيم `Content-Length` السالبة أو المتعارضة، وتُفك مفاتيح المصادقة بترميز UTF-8 صارم دون قبول صامت لبيانات تالفة.
- **دورة حياة async مراقبة:** مهام fan-out والتنظيف متتبعة، والاستثناءات تُسجل، والإغلاق يلغي المستمعين والمهام المتبقية بصورة حتمية.
- **حاوية مقواة:** مستخدم غير جذر (uid 10001)، نظام ملفات للقراءة فقط، إسقاط جميع capabilities، و`no-new-privileges`.
- **ترويسات أمان:** CSP، HSTS، COOP/CORP، Permissions-Policy، وحماية الإطارات؛ رفض CORS بالبدل (`*`).
- **إصلاح آمن فقط:** لا يُطبَّق أي تصحيح تلقائيًا إلا ما اجتاز سياسة Safe Autofix الحتمية.

## القيود المعلنة

التحديد الحالي للمعدل في الذاكرة لكل عامل (غير موزّع)؛ مفاتيح API أسرار بيئة ثابتة لا هوية متعددة المستأجرين؛ قناع PII يغطي البريد/الهاتف/URL وليس نظام DLP شاملًا؛ لم يُجرَ اختبار اختراق مستقل بعد. هذه القيود موثقة في `RELEASE_MANIFEST.json` وتُعالَج في خارطة v2.0.

</div>

---

## English Summary

**Do not open public issues for vulnerabilities.** Use GitHub Private Vulnerability Reporting on the repository (or e-mail the maintainers with a `[SECURITY]` prefix), including reproduction steps, affected version, and impact. Acknowledgement within 72 hours, initial assessment within 7 days, coordinated disclosure thereafter.

Supported: `1.0.x` (full), `0.13.x` (critical fixes only), older (unsupported). In scope: the Python library, REST server, LSP server, browser extension, desktop launcher, and YAML rule pipeline. Out of scope: optional third-party LLM backends and attacks requiring pre-existing root/physical access.

Current guarantees in `1.0.0-rc1`: loopback-only default binding, offset-preserving PII masking before every analysis layer, zero request-body logging, strict HTTP framing, size and rate limits, consistent API-key/Bearer authentication for HTTP and WebSocket, bounded browser WebSocket frames and buffered bytes, tracked asynchronous sync tasks, a hardened non-root read-only container, strict security headers, and a deterministic safe-autofix-only policy. Known limitations (per-worker in-memory rate limiting, static API keys, pattern-based PII masking, no third-party pentest yet) are documented in `RELEASE_MANIFEST.json` and scheduled in the v2.0 roadmap.
