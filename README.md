# Telegram Bot

المشروع يعمل على Windows وLinux من نفس الكود. استخدم Python 3.11 أو أحدث (يوصى بـ 3.12)، وأنشئ بيئة افتراضية مستقلة على كل نظام. لا تنسخ مجلد `.venv` بين ويندوز ولينكس.

## الإعداد على Windows

افتح PowerShell من داخل مجلد المشروع ثم نفّذ:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

املأ التوكنات و`ADMIN_IDS` في ملف `.env`، ثم تحقّق من البيئة وشغّل كل البوتات:

```powershell
.\start.ps1 -Check
.\start.ps1 all
```

لتشغيل بوت واحد فقط استخدم `admin` أو `main` أو `dev` بدل `all`.

إذا منع PowerShell تشغيل السكربت، نفّذه للجلسة الحالية فقط:

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1 all
```

## الإعداد على Linux

من داخل مجلد المشروع:

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
```

بعد تعبئة `.env`:

```bash
bash start.sh --check
bash start.sh all
```

يمكن كذلك استخدام المشغّل مباشرة على أي نظام:

```bash
python run.py --check
python run.py all
```

## ملاحظات التوافق

- المسارات الافتراضية لقاعدة البيانات والسجلات ثابتة بالنسبة لمجلد المشروع، لا بالنسبة لمجلد الطرفية الحالي. إذا استخدمت `DB_PATH` أو `ANALYTICS_DEAD_LETTER_PATH` في `.env`، فاستخدم مسارًا نسبيًا مثل `config/bot_structure.db`؛ الشرطة المائلة `/` صالحة على النظامين.
- يعتمد قياس الذاكرة على `psutil`، وهو مدعوم على Windows وLinux. لن يمنع غيابه المؤقت البوت من البدء، لكن تنبيهات الذاكرة ستتوقف حتى تثبيته.
- يتم تفعيل `uvloop` تلقائيًا على Linux عندما يكون متاحًا، ويُتخطى على Windows حيث يستخدم التطبيق حلقة asyncio الافتراضية المدعومة.
- يوجد فحص تلقائي على Ubuntu وWindows في GitHub Actions داخل `.github/workflows/cross-platform.yml`.

## النشر داخل حاوية Linux

قاعدة البيانات لا تُرفع مع الكود عمدًا (`config/*.db` ضمن `.gitignore`)؛ لذا أي حاوية جديدة تبدأ بقاعدة فارغة ما لم توفّر تخزينًا دائمًا. اربط قرصًا دائمًا من مزود الاستضافة إلى مسار مثل `/data` ثم اضبط متغيرات البيئة التالية:

```env
DB_PATH=/data/bot_structure.db
ANALYTICS_DEAD_LETTER_PATH=/data/analytics_dead_letters.jsonl
```

في أول نشر، استورد نسخة قاعدة البيانات الحالية إلى هذا القرص أو استعد نسخة النسخ الاحتياطي من خلال بوت الإدارة. التطبيق ينشئ قائمة `main` فارغة تلقائيًا عند غيابها كي لا يتوقف، لكن ذلك لا يعيد القوائم والمواد القديمة؛ استعادة النسخة الاحتياطية هي ما يعيد المحتوى.
