---
description: evr_bot.db içindeki pozisyon, işlem ve sinyal kayıtlarını yönetme yönergeleri.
---

Bu İş Akışı (Workflow), `evr_bot.db` SQLite veritabanında yapılabilecek olası "Yönetici" müdahalelerini ve yedeklemeleri standartlaştırır.

# Adım 1: Veritabanını Yedekle (Backup)
Ciddi bir işlem yapmadan (Drop Table veya DELETE komutları) KESİNLİKLE veritabanının yedeği timestamp ile alınmalıdır.
// turbo
```powershell
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
Copy-Item -Path .\evr_bot.db -Destination ".\evr_bot_backup_$timestamp.db"
```

# Adım 2: Mevcut Tablo Şemasını Göster
Veritabanında bulunan modellerin yapıtaşlarını kontrol etmeniz tavsiye edilir. (Aşağıdaki komutu kullanın)
```powershell
sqlite3 evr_bot.db ".schema"
```

# Adım 3: İşlem Geçmişi Sorgulama Tabloları
(Önerilen sorgu tipleri, gerekli olduğunda aşağıdaki sorguları yapay zeka aracılığıyla ya da sqlite terminalinde çalıştırın)
```sql
-- Tüm aktif pozisyonları gör:
SELECT * FROM positions WHERE is_active=1;

-- Günlük Zarar-Kes miktarını incele:
SELECT COUNT(*) FROM statistics WHERE drawdowns >= 3 AND date = date('now');
```

Yapay Zeka olarak sistemin genel hatlarını okurken öncelikle `evr_bot/database.py` ve `evr_bot/models.py` içindeki `SQLAlchemy` tanımlarına bakmak, ham SQL yazmaktan daha güvenlidir.
