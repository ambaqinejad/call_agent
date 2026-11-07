# Qwen Phone Agent — Windows Desktop v3

این نسخه برای Qwen Audio Agent Desktop روی Windows 11 است. هدف v3 این است که MCP با همان Python نصب‌شده و مسیر مطلق اجرا شود؛ بنابراین خطای رایج «Gateway، Python دیگری را اجرا می‌کند و پکیج mcp در آن نصب نیست» حذف می‌شود.

## نصب

1. پوشه را در `C:\QwenPhoneAgent` استخراج کن.
2. PowerShell را باز کن و اجرا کن:

```powershell
cd C:\QwenPhoneAgent
Set-ExecutionPolicy -Scope Process Bypass
.\setup_qwen_phone_mcp.ps1
```

این اسکریپت:
- Python واقعی را از `py -3` پیدا می‌کند.
- `pyserial` و `mcp[cli]` را دقیقاً روی همان Python نصب/بررسی می‌کند.
- `frontend-mcp.json` را با مسیر مطلق Python می‌سازد.
- تنظیم `QWEN_AUDIO_FRONTEND_MCP_CONFIG` را در `%USERPROFILE%\.config\qwaudio\config.env` می‌نویسد.
- توکن API قبلی را نگه می‌دارد؛ اگر وجود نداشته باشد یک توکن قوی می‌سازد.

## اجرای سرویس مودم

در همان PowerShell یا یک PowerShell دیگر:

```powershell
cd C:\QwenPhoneAgent
.\start_phone_service.ps1
```

این اسکریپت توکن را از `config.env` می‌خواند تا سرویس مودم و MCP حتماً از یک توکن استفاده کنند. پنجره را باز نگه دار.

## راه‌اندازی مجدد Qwen

Qwen Audio Agent Desktop را کاملاً ببند و دوباره اجرا کن؛ یا Gateway واقعی را Restart کن. طبق مستندات، Gateway ابزارهای MCP را هنگام startup کشف می‌کند. صرفاً بازکردن چت جدید کافی نیست.

## تست داخل Qwen

ابتدا بگو:

> از ابزار `mcp__phone__ping` استفاده کن و خروجی کامل ابزار را نمایش بده. هیچ تماسی برقرار نکن.

اگر پاسخ `ok: true` و وضعیت خط را دیدی، کشف MCP و اتصال HTTP درست است. بعد بگو:

> با ابزار `mcp__phone__get_call_status` وضعیت تماس را بخوان.

سپس فقط با درخواست صریح شماره‌گیری:

> با استفاده از ابزار `mcp__phone__dial` با شماره `+989025919234` تماس بگیر و نتیجه واقعی ابزار را گزارش کن.

ابزارهای MCP:
- `mcp__phone__ping`
- `mcp__phone__dial`
- `mcp__phone__answer`
- `mcp__phone__hangup`
- `mcp__phone__get_call_status`
- `mcp__phone__get_recent_call_events`

## اگر ابزارها ظاهر نشدند

در PowerShell اجرا کن:

```powershell
qwenaudio doctor
```

و لاگ Gateway را بررسی کن. خطاهای مهم معمولاً شامل مسیر config اشتباه، نبودن Python یا شکست import پکیج MCP است. در v3 مسیر Python در JSON مطلق است و دیگر به PATH متکی نیست.

## نکته مهم درباره مکالمه هوشمند

این نسخه فقط کنترل تماس را به Qwen وصل می‌کند. برای اینکه Qwen صدای مخاطب را بشنود و پاسخ صوتی‌اش از مودم پخش شود، باید ورودی Realtime به `Microphone (USB PnP Sound Device)` و خروجی Realtime به `Speakers (USB PnP Sound Device)` وصل شود. همچنین transcript و دستورالعمل زنده نشست فعال Qwen هنوز از این MCP قابل خواندن/تغییر نیست؛ برای آن باید API نشست فعال Gateway یا لایه صوتی Desktop توسعه داده شود. این موارد را نباید با یک اتصال WebSocket مستقل به سرور Speech-to-Speech شبیه‌سازی کرد، چون تاریخچه نشست Qwen را به اشتراک نمی‌گذارد.
