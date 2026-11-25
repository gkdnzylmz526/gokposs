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

## Iteration 14 (Haziran 2026)
- Emergent-managed Clerk auth (email+password). Admin-only dashboard (roles admin/member, ADMIN_EMAIL=gkdnzylmz5261@gmail.com), Users page, router-level guard; public /izin and cron excluded.
- Leave request email notification; monthly summary email (cron 1st 09:00 Istanbul).
- Tested iteration_14.json: 32/32 auth tests + regressions pass; minor UI fixes.

## Iteration 15 (Haziran 2026)
- 'staff' role: mobile StaffApp (sales entry + stock count only), server-enforced allowlist & price override.
- Audit log (audit_logs) for all CRUD + key actions; panel on Kullanıcılar page.
- PWA: manifest, icons, service worker, iOS meta.
- Tested iteration_15.json; fixed sale quantity validation, staff toasts, audit user filter.

## Iteration 16 (Haziran 2026)
- Payment types (Nakit/Kart/Yemek kartı) on sales; report breakdown; reconciliation uses cash only.
- Cash closing reminder cron 23:30 (cash-reminder).
- Waste log (waste collection) with stock deduction + cost in reports.
- Staff "Bugün sattıklarım" (sales.created_by).
- Public QR menu (/menu, /api/public/menu) + QR card on Menü page.
- Tested iteration_16.json; fixed dashboard waste key, atomic waste PUT, required select defaults.

## Iteration 17–18 (Haziran 2026)
- Multi-restaurant: Florya Taşfırın / Etiler Marmaris / Dürümtır (backend/scope.py ScopedDB + contextvar, header X-Restaurant, 'all' = read-only union). Menu (products) & suppliers shared; all other data per restaurant. Existing data migrated to florya-tasfirin on startup.
- Recipes shared: ingredient resolved by same name in selling restaurant; sale cost uses that restaurant's prices; product.cost = average.
- Staff users bound to one restaurant + optional staff record (PATCH /api/users/{id}/assignment).
- Masalar: tables CRUD, /api/tables-view, items/close/cancel; close creates sales + stock + tip.
- Bahşiş: tips collection + /api/tips/distribution (hours from attendance or shifts).
- Giriş-çıkış: attendance collection, /api/attendance/me|clock (staff), payroll uses real hours (hours_source).
- Ürün Maliyeti page (/api/product-costs) with per-restaurant costs + cost calculator; restaurant summary cards (/api/restaurants/summary).
- Cash reminder per restaurant. Tested iteration_17/18: all pass. Redeploy requested.

## Backlog
- P1: Per-restaurant sections in nightly/weekly e-mails (now combined)
- P2: Kitchen display, SKT (expiry) alerts, loyalty, split bill per table

## Iteration 19 (Haziran 2026)
- Nightly report per restaurant: full_report in all/None mode adds report["restaurants"] (ciro, gider, kâr, payments, kasa) + combined reconciliation; PDF/Excel 'Restoran Bazlı Özet'; email body per-restaurant blocks.
- Kitchen screen: kitchen_tickets (scoped), Yeni→Hazırlanıyor→Hazır→Teslim edildi; admin nav 'Mutfak' + staff tab; table tile 'Hazır' badge; 8s polling + beep.
- Split bill: POST /api/tables/{id}/pay (full / amount with equal split / items); pending payments, proportional sales on finalize ('bölünmüş hesap' note); pending remove; cancel blocked after payments.
- Stock transfers: /api/stock-transfers POST/GET/DELETE(undo), same-name match or create in target; movements both sides.
- Tested: backend 15/15 + regression; frontend iteration_19 ~95% -> pending-remove bug fixed. Redeploy requested.

## Iteration 20 (Haziran 2026)
- Product wizard ("Sorularla ürün ekle", ProductWizard.jsx) on Menü Ürünleri & Ürün Maliyeti: name → category → ingredient loop (known from stock or new: unit + price) → amount (gr/kg, ml/lt toggle) → target margin → sale price → summary; live recap cost.
- POST /api/products/wizard: new ingredients created in all 3 restaurants (qty 0, same price), zero-price items filled, duplicate name 409.
- Fixes: picking current restaurant no longer stuck loading; wizard mobile width; category dedupe; copied ingredient keeps original name. Tested iteration_20 (backend 100%, frontend 95% → fixed). Redeploy requested.

## Iteration 21 (Haziran 2026)
- User runs a separate ordering POS; goal = cost calculation + manual revenue entry. Product-based sales (Satışlar/Masalar/Mutfak) hidden by default via settings.product_sales (Kullanıcılar > switch).
- Kasa > Manuel kayıtlar (CashBook.jsx): Gelirler (incomes: date, amount, payment Nakit/Kart/Yemek kartı/Havale, category, note), Giderler (expense.payment; only Nakit expenses reduce cash), Faturalar (invoices with due date, VAT, pay/unpay → linked expense, overdue/due-soon tiles, photo/PDF upload via Emergent object storage storage.py, /api/files/{id}).
- Incomes count in revenue, payments, dashboard, reconciliation, exports (Gelir Kayıtları, Havale column).
- Existing products: "Sorularla tarif ekle" wizard (/api/products/{id}/wizard-recipe). Printable cost cards (single + all) on Ürün Maliyeti.
- Tested iteration_21 (100%); minor UX fixes applied after. Redeploy requested.

## Iteration 22–23 (Haziran 2026)
- Fixed costs in product cost: /api/overhead (manual monthly items: kira, elektrik, su, maaş…; monthly revenue manual or last-30-day auto, one ratio for 3 restaurants). Product cost page shows overhead share (price × ratio), full cost, net margin, suggested price incl. overhead; calculator, product card suggestion, bulk price apply and print cards all overhead-aware.
- Product photos: POST/DELETE /api/products/{id}/photo (client downscale to JPEG ≤1200px), public /api/public/photos/{id}; QR menu shows thumbnails + zoom + product description field.
- Tested iteration_22/23 (backend 100%, frontend 100%); minor follow-ups fixed. Redeploy requested.

## Iteration 24 (Haziran 2026)
- QR menu: categories auto-grouped (Turkish case/space-insensitive, first-letter capitalised), category cards (cover = first product photo, item count) → tap shows products with sticky category tabs, back button / phone back. Verified via screenshot + API. Redeploy requested.
- Iteration 25: QR menu header rebranded 'Florya Dürüm Tır · MENÜ' (Bebas Neue + Playfair italic), storefront photo hero (user upload made public), GÖKBOSS removed from customer menu. Redeploy requested.
