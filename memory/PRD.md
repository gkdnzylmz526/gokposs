# Restoran Asistanı — PRD

## Orijinal İstek
“yeni restorant müdürü oldum herşeyde bana yardım edecek bir uygulama yap zai alış satış sayım felan herşey”

## Kullanıcı ve Amaç
- Bir restoran müdürü, günlük operasyonları tek ekrandan yönetmek istiyor.
- Uygulama şimdilik tek kullanıcı için, giriş gerektirmeden doğrudan açılır.
- Para birimi TL’dir.

## Mimari Kararlar
- React + FastAPI + MongoDB yapısı korunmuştur.
- Frontend API çağrıları `REACT_APP_BACKEND_URL`, backend veritabanı bağlantısı mevcut `MONGO_URL` ile çalışır.
- MongoDB kayıtlarında `_id` response dışında tutulur; kayıt modelleri Pydantic ile tanımlanır.
- İlk kullanım için frontend’de DEMO/fallback verileri bulunur; gerçek API ve MongoDB kayıtları olduğunda bunlar önceliklidir.

## Statik Gereksinimler
- Günlük satış ve ciro takibi
- Alış ve gider kaydı
- Stok/malzeme sayımı ve kritik stok uyarıları
- Personel vardiya ve görev takibi
- Kasa açılış/kapanış özeti
- Günlük, haftalık ve aylık rapor görünümü
- En çok satan ürünler ve gider/kâr tahmini için rapor altyapısı
- Responsive kullanım ve her etkileşimli öğede benzersiz test kimliği

## Uygulananlar
- 2026-11-23: Dashboard, metrik kartları, haftalık performans grafiği, hızlı işlemler ve kasa özeti tamamlandı.
- 2026-11-23: Satış, gider, stok, personel, kasa CRUD endpoint’leri ve dashboard endpoint’i eklendi.
- 2026-11-23: Satışlar, Alış & Giderler, Stok Sayımı, Ekip & Vardiya, Kasa ve Raporlar görünümleri eklendi.
- 2026-11-23: Yeni kayıt modalları, TL formatı, demo fallback verileri ve responsive mobil menü tamamlandı.
- 2026-11-23: Backend testleri ve frontend build doğrulandı; tablo hizalama regresyonu giderildi.

## Öncelikli Backlog
### P0
- Gerçek restoran menüsü/ürün bazlı satış detayları ve en çok satan ürün raporu
- Kasa kapanışında satış ve giderlerden otomatik gün sonu mutabakatı

### P1
- Raporlarda gerçek tarih aralığı seçimi ve MongoDB tarih filtreleri
- Excel/PDF dışa aktarma
- Personel görev durumunu aktif/tamamlandı olarak güncelleme

### P2
- Çoklu restoran/şube desteği
- Yetkilendirme ve işletme sahibi görünümü
- Bildirimler ve tedarikçi bazlı satın alma geçmişi

## Sonraki Görevler
1. Ürün kataloğu ve ürün bazlı satış girişini ekle.
2. Gerçek haftalık/aylık tarih filtrelerini bağla.
3. Kasa kapanışını otomatik ciro-gider mutabakatına dönüştür.