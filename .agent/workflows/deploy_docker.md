---
description: Projeyi mevcut Dockerfile ve docker-compose yml üzerinden ayağa kaldırmak.
---

Bu iş akışı, EVR KMFG Ticaret Botu projesinin Docker aracılığıyla konteynerize edilip yerel ya da uzak sunucuda (VPS) ayağa kaldırılmasını standartlaştırır.

# Adım 1: Tüm kalıntıları temizle
Mevcut çalışan versiyonlar veya artık oluşturulmuş ağları temizleyerek taze başlangıç yap.
// turbo
```powershell
docker-compose down
```

# Adım 2: Görüntü (Image) Oluştur (Build)
Botun bağımlılıklarını kurup projeyi en güncel haliyle konteynıra dahil etmesini sağla.
// turbo
```powershell
docker-compose build --no-cache
```

# Adım 3: Hizmetleri Ayağa Kaldır
Bot işlemlerini arka planda (-d) çalıştıracak şekilde başlat.
// turbo
```powershell
docker-compose up -d
```

# Adım 4: Ayakta Kaldığını Doğrula
Servis loglarını takip ederek (özellikle `curl_cffi` içeren scraper loglarının) Cloudflare hataları almadığını konfirme et.
// turbo
```powershell
docker-compose logs -f --tail=100
```
