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
## Iteration 4 (Haziran 2026)
- Real XLSX (openpyxl) + PDF (reportlab, bundled Noto Sans fonts for ₺/Turkish chars) exports: GET /api/reports/export?period=&format=xlsx|pdf. Includes summary, cash reconciliation, product performance, all sales & expense records.
- Removed all frontend demo/fallback data; empty states everywhere; real current date; real 7-day chart from /api/dashboard `weekly`.
- Dashboard metrics now today-only; all day boundaries use Europe/Istanbul timezone.
- Tested: iteration_4.json (only ₺ PDF glyph bug — fixed).

## Backlog
- P1: Split App.js into components
- P2: Authentication (user deferred), record edit/delete in UI, date-range custom report filter

## Iteration 5 (Haziran 2026)
- Edit/delete for all lists (PUT/DELETE /api/{collection}/{id}), RowActions with confirm.
- Custom date range reports (period=custom&start&end) + exports.
- Stock deduction on sale: product recipe (inventory_id, amount) or same-name inventory fallback (Turkish-aware match); applied moves stored on sale (stock_moves) and reversed on edit/delete.
- Gün sonu e-postası: Gmail SMTP (mailer.py, GMAIL_USERNAME / GMAIL_APP_PASSWORD), recipient REPORT_RECIPIENT, cron .emergent/crons.yml 23:59 Europe/Istanbul -> POST /api/cron/daily-report (Bearer WEBHOOK_CRON_SECRET), manual POST /api/email/send-now, GET /api/email/status.
- Tested: iteration_5.json; fixes applied for 502->200 failed status, empty cron body, negative profit color, sticky mobile actions, rounding.

## Iteration 6 (Haziran 2026)
- Stock movement log (stock_movements collection, GET /api/stock-movements) for initial, sale, sale edit/delete, manual count, item delete; UI panel in Stok Sayımı with filter.
- Nightly email body + PDF include Kritik Stok list.
- Turkish calendar date picker (shadcn Calendar, tr locale, dd.MM.yyyy) for custom report range.
- Tested iteration_6.json: no functional bugs; design nits fixed.
- PENDING: valid 16-letter Gmail app password (current GMAIL_APP_PASSWORD rejected by Gmail).

## Iteration 7 (Haziran 2026)
- Inventory: unit_cost, target, supplier. GET /api/order-list (critical items grouped by supplier, suggested = target - qty or 2×min - qty) with copy/WhatsApp share UI.
- Recipe cost auto-calculation (cost_from_recipe), recomputed on inventory changes; sales fill unit_cost from product if missing.
- Gmail app password fixed: manual send verified (status sent). Nightly cron 23:59 Europe/Istanbul active.
- Tested iteration_7.json: all passed; minor nits fixed.

## Iteration 8 (Haziran 2026)
- Weekly summary email (Mon 09:00 Istanbul, cron weekly-summary -> /api/cron/weekly-summary), manual send ?kind=weekly.
- Purchase expenses add stock + update unit_cost + log 'Alış'; auto amount; edit/delete reverse.
- Suggested menu price (target_margin, default 65%).
- Suppliers directory (/api/suppliers), WhatsApp order button opens supplier phone (TR normalization).
- Tested iteration_8.json; edit-amount recompute + validation fixed.

## Iteration 9 (Haziran 2026)
- Supplier monthly spending (/api/suppliers/spending), expense supplier field.
- Price change alerts (>=10% increase via purchase) with affected product margins; dismiss.
- Bulk apply suggested prices (/api/products/apply-suggested) with confirm dialog.
- Weekly shift calendar (shifts collection, CRUD /api/shifts).
- Tested iteration_9.json: all passed; shift validation + delete confirm added.

## Iteration 10 (Haziran 2026)
- Staff hourly_wage + weekly pay/payroll in shift calendar; copy previous week (/api/shifts/copy-week).
- Ingredient price history chart + supplier price comparison (/api/inventory/{id}/prices).
- Tested iteration_10.json: all passed; UI nits fixed.

## Iteration 11 (Haziran 2026)
- Monthly payroll (/api/payroll, /api/payroll/export xlsx), overtime >45h/week at 1.5×.
- Smart order list: groups by cheapest supplier from purchase history, saving vs assigned.
- Staff phone + per-person WhatsApp weekly plan link.
- Backend pytest (15) passed; frontend verified via Playwright script. Testing agent run was interrupted (credits).
- Backlog: split server.py into routers (~640 lines).

## Iteration 12 (Haziran 2026)
- Leaves (leaves collection, 5 types, annual_leave_days default 14, balance in calendar).
- Salary advances (advances collection) subtracted in payroll (net_pay), Excel 'Avanslar' sheet.
- Bulk WhatsApp plan dialog (sequential per-person send).
- Order history (orders collection) auto-saved from order list copy/WhatsApp; status toggle.
- Tested iteration_12.json: all passed; UI nits fixed.

## Iteration 13 (Haziran 2026)
- Conflict warnings (shift on leave day / overlapping shifts / leave on shift day) via confirm.
- Pay slip PDF per staff (/api/payroll/{id}/slip).
- Personal leave request link (/izin/{token}, public API /api/public/leave/{token}), manager approve/reject panel, pending chips in calendar.
- Order delivered -> auto expense 'Sipariş teslimi' + stock add; revert removes.
- Tested iteration_13.json; fixed stale data after order toggle, PDF escaping, date picker min.
- Backlog: split server.py (~800 lines) into routers.
