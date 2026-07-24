# ضاد لسطح المكتب

الإصدار v1.0.0-rc1 يقدّم مشغّلًا محليًا حقيقيًا فوق نفس واجهة الويب وREST API، من دون نسخ منطق NLP:

```bash
pip install "dhad[server,desktop]"
dhad-desktop
```

ترتيب الواجهات:

1. نافذة `pywebview` خاصة عند تثبيت الاعتماد الاختياري.
2. وضع التطبيق في Chrome أو Edge أو Chromium.
3. المتصفح الافتراضي مع خادم loopback يبقى نشطًا حتى `Ctrl+C`.

المشغّل يرفض الربط بواجهة شبكة عامة؛ ويستعمل `127.0.0.1` أو `localhost` أو `::1` فقط. يمكن تشغيل الخادم وحده لأغراض الحزم الأصلية:

```bash
dhad-desktop --backend server --port 8010
```

كما يمكن تثبيت واجهة ضاد مباشرة كتطبيق PWA من المتصفح. الـService Worker يخزّن ملفات الواجهة فقط، ولا يخزّن طلبات أو ردود التحليل التي تحتوي نص المستخدم.

## Tauri 2 native wrapper

The additive `src-tauri/` shell packages the same static `web_demo/` interface
for macOS and Windows. In a Tauri window, deterministic analysis and rewriting
are routed through Rust IPC; browser and PWA sessions continue to use the
existing WASM/WebWorker path.
