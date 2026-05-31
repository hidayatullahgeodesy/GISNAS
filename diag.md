# 🔍 Diagnosa: GISNAS OGC API ↔ QGIS v3

> **Tanggal**: 30 Mei 2026  
> **Subyek**: Kompatibilitas OGC API GISNAS dengan QGIS Desktop 3.x  
> **Fokus**: Copy-paste data, perbedaan kolom, dan pembuatan kolom baru

---

## 📋 Ringkasan Masalah

| # | Masalah | Severity |
|---|---------|----------|
| 1 | Tidak bisa copy-paste data dari SHP/KML/GPKG ke layer OGC API secara langsung | 🔴 **Tinggi** |
| 2 | Gagal paste jika kolom (field) sumber berbeda dengan kolom tujuan | 🔴 **Tinggi** |
| 3 | Tidak bisa membuat kolom baru langsung dari QGIS pada layer OGC API | 🟡 **Sedang** (sudah ada workaround plugin) |

---

## 1. Analisis Arsitektur Saat Ini

### 1.1 Stack GISNAS

```
┌──────────────────────────────────────────────────────┐
│                    QGIS Desktop 3.x                  │
│  (WFS / OGC API Features Provider)                   │
└──────────────────┬───────────────────────────────────┘
                   │ HTTP (GET/POST/PUT/PATCH/DELETE)
                   ▼
┌──────────────────────────────────────────────────────┐
│              GISNAS Backend (Go :8080)               │
│                                                      │
│  Endpoint:                                           │
│  /token/{token}/api/ogc/features/                    │
│  /token/{token}/api/ogc/features/conformance         │
│  /token/{token}/api/ogc/features/collections         │
│  /token/{token}/api/ogc/features/collections/{id}/   │
│     ├── items      (GET, POST)                       │
│     ├── items/{fid} (GET, PUT, PATCH, DELETE)         │
│     ├── queryables  (GET)                            │
│     └── columns     (GET, POST, DELETE) ← custom!    │
└──────────────────┬───────────────────────────────────┘
                   │ SQL
                   ▼
┌──────────────────────────────────────────────────────┐
│              PostGIS 15-3.3 (:5432)                  │
│  Tabel dinamis: ws{N}_data_{timestamp}               │
└──────────────────────────────────────────────────────┘
```

### 1.2 Conformance Classes yang Dideclare

```json
{
  "conformsTo": [
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/core",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/oas30",
    "http://www.opengis.net/spec/ogcapi-features-1/1.0/conf/geojson",
    "http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/create-replace-delete",
    "http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/update",
    "http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/features",
    "http://www.opengis.net/spec/ogcapi-features-4/1.0/conf/simple-transactions"
  ]
}
```

**Status**: ✅ QGIS seharusnya mengenali ini sebagai layer yang *editable* (CRUD).

---

## 2. Diagnosa Per-Masalah

### 2.1 🔴 Masalah: Tidak Bisa Copy-Paste dari SHP/KML/GPKG

#### Akar Masalah

Ini **bukan bug di GISNAS**, melainkan **limitasi fundamental dari QGIS Desktop** ketika bekerja dengan layer remote (WFS / OGC API Features):

| Aspek | Penjelasan |
|-------|------------|
| **Mekanisme Clipboard QGIS** | QGIS copy-paste (`Ctrl+C / Ctrl+V`) mencoba mencocokkan field **berdasarkan urutan kolom** (bukan nama). Jika kolom tidak cocok → atribut hilang / NULL / masuk kolom salah |
| **Tidak ada Field Mapper** | QGIS **tidak menyediakan dialog pemetaan field** saat paste. Ini berlaku untuk SEMUA layer tujuan (lokal maupun remote) |
| **Remote Provider** | Untuk layer OGC API, setiap feature yang di-paste akan dikirim via HTTP POST satu per satu. Jika ada mismatch → server menolak atau data incomplete |

#### Bukti di Kode GISNAS

Pada `main.go` (handler `POST /items`), server hanya memasukkan kolom yang **ada di tabel database**:

```go
// main.go:1484-1491
for _, col := range columns {     // ← hanya kolom yang ada di tabel
    if val, ok := body.Properties[col]; ok {
        pCount++
        cols = append(cols, col)
        placeholders = append(placeholders, fmt.Sprintf("$%d", pCount))
        vals = append(vals, val)
    }
}
```

Artinya:
- ✅ Kolom yang cocok namanya → **masuk**
- ❌ Kolom dari SHP/KML yang **tidak ada** di tabel → **diabaikan diam-diam** (tidak error, tapi data hilang)
- ❌ Kolom tabel yang **tidak ada** di data sumber → **NULL**

#### Siapa yang Support?

| Fitur | QGIS Native | OGC API Standard | GISNAS Backend |
|-------|:-----------:|:-----------------:|:--------------:|
| Copy-paste (schema identik) | ✅ | ✅ (POST /items) | ✅ |
| Copy-paste (schema beda) | ❌ Tidak ada field mapper | N/A | ⚠️ Partial (diabaikan) |
| Bulk insert | ❌ Satu-satu via HTTP | ❌ Tidak di spec | ❌ |

---

### 2.2 🔴 Masalah: Kolom Berbeda Saat Copy-Paste

#### Akar Masalah

Ini adalah **gabungan limitasi** dari 3 sisi:

```
SHP/KML/GPKG (sumber)          OGC API Layer (tujuan)
┌──────────────────┐           ┌──────────────────┐
│ FID              │           │ id               │
│ nama_jalan  ────────────?────── name             │  ← Beda nama!
│ panjang_m   ────────────?────── (tidak ada)      │  ← Kolom tidak ada!
│ (tidak ada)  ────────────?────── kecamatan        │  ← Kolom baru di tujuan
│ geom             │           │ geom             │
└──────────────────┘           └──────────────────┘

QGIS: "Saya tidak tahu cara memetakan ini." → paste gagal / data hilang
```

#### Detail Teknis

1. **QGIS Clipboard** menggunakan format internal XML/GeoJSON tanpa metadata mapping
2. Saat paste ke layer OGC API:
   - QGIS mengirim `POST /collections/{id}/items` dengan `properties` dari clipboard
   - Properties menggunakan nama kolom **dari layer sumber** (misal `nama_jalan`)
   - Backend GISNAS hanya mencari kolom yang ada di tabel (`name`) → **tidak cocok → diabaikan**
3. **Tidak ada proses translasi field** di sisi manapun

#### Siapa yang Support?

| Fitur | QGIS Native | OGC API Standard | GISNAS Backend |
|-------|:-----------:|:-----------------:|:--------------:|
| Field mapping saat paste | ❌ | N/A (bukan scope) | ❌ |
| Auto-create kolom baru | ❌ | ❌ (bukan scope) | ❌ |
| Reject unknown fields | N/A | ✅ (recommended) | ⚠️ (diabaikan, bukan reject) |

---

### 2.3 🟡 Masalah: Tidak Bisa Buat Kolom Baru dari QGIS

#### Akar Masalah

| Layer | Bahasa Teknis | Penjelasan |
|-------|---------|------------|
| **Standar OGC API Features** | Tidak mendukung DDL | OGC API Features adalah standar **akses data** (DML), bukan **definisi skema** (DDL). Tidak ada endpoint standar untuk `ALTER TABLE ADD COLUMN` |
| **QGIS WFS Provider** | Read-only schema | Provider WFS/OGC di QGIS membaca skema saat layer dimuat. Tidak ada mekanisme untuk mengirim perintah "tambah kolom" ke server |
| **GISNAS** | Sudah punya solusi custom | GISNAS sudah menambahkan endpoint non-standar `/columns` (POST, DELETE) dan plugin QGIS `gisnas_schema_manager` |

#### Status Implementasi GISNAS

```
✅ Endpoint custom:
   POST   /collections/{table}/columns     → ALTER TABLE ADD COLUMN
   DELETE /collections/{table}/columns?name= → ALTER TABLE DROP COLUMN
   GET    /collections/{table}/columns     → information_schema query

✅ Plugin QGIS: gisnas_schema_manager
   - Bisa list kolom
   - Bisa tambah kolom baru (VARCHAR, INT, REAL, DATE, dll)
   - Bisa hapus kolom
   - Auto-refresh layer di QGIS setelah perubahan skema

⚠️ Limitasi plugin saat ini:
   - Harus remove + re-add layer (karena QGIS cache skema)
   - Tidak bisa rename kolom
   - Tidak bisa ubah tipe kolom
```

#### Siapa yang Support?

| Fitur | QGIS Native | OGC API Standard | GISNAS Backend | GISNAS Plugin |
|-------|:-----------:|:-----------------:|:--------------:|:-------------:|
| Tambah kolom | ❌ | ❌ | ✅ custom | ✅ |
| Hapus kolom | ❌ | ❌ | ✅ custom | ✅ |
| Rename kolom | ❌ | ❌ | ❌ | ❌ |
| Ubah tipe kolom | ❌ | ❌ | ❌ | ❌ |

---

## 3. Matriks Kompatibilitas Lengkap

### QGIS ↔ GISNAS OGC API

| Operasi | Status | Catatan |
|---------|:------:|---------|
| **Koneksi ke OGC API** | ✅ | Via WFS/OGC API Features connection |
| **Baca data (GET items)** | ✅ | Termasuk pagination, BBox filter |
| **Tambah feature baru (digitize)** | ✅ | POST /items → `201 Created` |
| **Edit feature (ubah geometri/atribut)** | ✅ | PUT/PATCH /items/{id} → `204 No Content` |
| **Hapus feature** | ✅ | DELETE /items/{id} → `204 No Content` |
| **Copy-paste (schema identik)** | ⚠️ | Bisa, tapi lambat (satu-satu via HTTP) |
| **Copy-paste (schema beda)** | ❌ | Data hilang, tidak ada field mapper |
| **Tambah kolom dari QGIS** | ❌🔧 | Tidak native, tapi bisa via plugin GISNAS |
| **Hapus kolom dari QGIS** | ❌🔧 | Tidak native, tapi bisa via plugin GISNAS |
| **Import SHP langsung ke layer** | ❌ | Harus via workaround |
| **Import KML langsung ke layer** | ❌ | Harus via workaround |
| **Import GPKG langsung ke layer** | ❌ | Harus via workaround |

---

## 4. Bug / Kelemahan di Kode GISNAS

Selain limitasi QGIS, ada beberapa hal di kode GISNAS yang perlu diperbaiki:

### 4.1 🐛 Geometry Tidak Di-Transform ke SRID yang Benar Saat GET Items

```go
// main.go:1534 — Selalu output as-is tanpa transform ke 4326
selectCols := []string{"ST_AsGeoJSON(geom) as geom_geojson"}
```

**Masalah**: OGC API Features mengharuskan output dalam **CRS84 (EPSG:4326)** secara default. Jika tabel menyimpan data di SRID lain (misal EPSG:32749), geometry yang dikirim ke QGIS akan **salah posisi**.

**Fix yang disarankan**:
```go
selectCols := []string{"ST_AsGeoJSON(ST_Transform(geom, 4326)) as geom_geojson"}
```

### 4.2 🐛 Tidak Ada Pagination (`limit` / `offset`)

```go
// main.go:1537 — Mengambil SEMUA data tanpa limit
query := fmt.Sprintf("SELECT %s FROM %s", strings.Join(selectCols, ", "), tableName)
```

**Masalah**: Jika tabel punya 100.000+ rows, response akan sangat besar dan QGIS akan hang/timeout. OGC API spec mengharuskan pagination default dengan `limit` dan `next` link.

### 4.3 🐛 `numberMatched` Menggunakan `len(features)` Setelah Query

```go
// main.go:1647-1648
"numberMatched":  len(features),
"numberReturned": len(features),
```

**Masalah**: `numberMatched` seharusnya menunjukkan **total jumlah feature** di collection (bukan hanya yang dikembalikan di halaman ini). QGIS menggunakan ini untuk progress bar.

### 4.4 ⚠️ Kolom `create_gn` / `update_gn` Terekspos ke QGIS

Kolom internal `create_gn` dan `update_gn` muncul di QGIS sebagai field biasa. Saat paste dari SHP yang tidak punya kolom ini:
- `create_gn` → NULL (tapi ada DEFAULT, jadi aman)
- `update_gn` → NULL (tapi ada DEFAULT, jadi aman)

**Saran**: Filter kolom ini dari response `queryables` dan `items` agar tidak membingungkan user QGIS.

### 4.5 ⚠️ SQL Injection Risk pada `tableName`

```go
// Beberapa tempat di main.go menggunakan string formatting langsung:
query := fmt.Sprintf("SELECT %s FROM %s", selectCols, tableName)
```

`tableName` berasal dari URL path tanpa validasi terhadap `datasets` table terlebih dahulu (sudah ada di beberapa handler, tapi tidak konsisten).

---

## 5. Solusi & Rekomendasi

### 5.1 Untuk Copy-Paste dari SHP/KML/GPKG (Schema Berbeda)

Karena ini adalah **limitasi QGIS**, ada 3 pendekatan:

#### Opsi A: Workaround di QGIS (Tanpa Ubah Kode)

```
Alur kerja:
1. Buka SHP/KML/GPKG di QGIS
2. Buka Processing Toolbox → "Refactor Fields"
3. Mapping kolom sumber → nama kolom yang ada di layer OGC API
4. Jalankan → dapat temporary layer dengan schema yang cocok
5. Copy dari temporary layer → Paste ke layer OGC API

Kelebihan: Tidak perlu ubah backend
Kekurangan: Manual, harus tahu nama kolom tujuan, lambat untuk data besar
```

#### Opsi B: Tambah Endpoint Import di Backend GISNAS (Direkomendasikan)

```
Endpoint baru:
POST /api/ogc/features/collections/{table}/import?token=xxx

Body (multipart/form-data):
- file: file SHP/KML/GPKG
- field_mapping: JSON { "kolom_sumber": "kolom_tujuan", ... }
- create_missing_columns: true/false

Alur:
1. Backend menerima file
2. Parse geometry & attributes dari file (pakai ogr2ogr atau library Go)
3. Jika create_missing_columns=true → ALTER TABLE ADD COLUMN
4. Map field sesuai field_mapping
5. Bulk INSERT ke PostGIS

Kelebihan: Cepat, reliable, bisa handle schema beda
Kekurangan: Perlu development backend + UI frontend
```

#### Opsi C: Upgrade Plugin GISNAS untuk Copy-Paste dengan Field Mapper

```
Tambahkan fitur di plugin gisnas_schema_manager:
1. User pilih layer sumber (SHP/KML di QGIS) dan layer tujuan (OGC API)
2. Plugin menampilkan dialog mapping kolom (dropdown)
3. User bisa pilih "Buat kolom baru" untuk kolom yang belum ada
4. Plugin melakukan:
   a. POST /columns untuk kolom baru (jika ada)
   b. Iterasi setiap feature di sumber
   c. Build GeoJSON dengan field mapping yang benar
   d. POST /items untuk setiap feature

Kelebihan: Pengalaman terbaik di QGIS, visual
Kekurangan: Lambat untuk data besar (HTTP per feature), development effort besar
```

### 5.2 Untuk Pembuatan Kolom Baru

**Status saat ini**: ✅ Sudah solved via plugin `gisnas_schema_manager`

**Improvement yang bisa dilakukan**:

| Enhancement | Priority | Effort |
|-------------|:--------:|:------:|
| Tambah fitur rename kolom (endpoint + plugin UI) | Sedang | Kecil |
| Tambah fitur ubah tipe kolom | Rendah | Sedang |
| Auto-detect schema saat user paste → suggest create kolom | Tinggi | Besar |
| Batch column operations (tambah banyak kolom sekaligus) | Rendah | Kecil |

---

## 6. Perbandingan dengan Solusi Lain

| Fitur | GISNAS (Custom) | GeoServer WFS-T | pygeoapi | QGIS Server |
|-------|:---------------:|:----------------:|:--------:|:-----------:|
| CRUD via OGC API | ✅ | ✅ | ✅ | ✅ |
| Copy-paste dari QGIS (sama schema) | ✅ | ✅ | ✅ | ✅ |
| Copy-paste (beda schema) | ❌* | ❌* | ❌* | ❌* |
| Tambah kolom via QGIS | ✅ Plugin | ❌ | ❌ | ❌ |
| Import file langsung | ❌ | ✅ (REST API) | ❌ | ❌ |
| Pagination | ❌ | ✅ | ✅ | ✅ |
| CRS Transform | ⚠️ Partial | ✅ | ✅ | ✅ |

> \*Copy-paste dengan beda schema adalah **limitasi QGIS**, bukan server

**Kesimpulan**: Untuk fitur **tambah kolom**, GISNAS justru **lebih maju** dari GeoServer, pygeoapi, dan QGIS Server karena punya custom endpoint + plugin. Untuk fitur lain (pagination, CRS), GISNAS perlu improvement.

---

## 7. Prioritas Perbaikan

| # | Item | Impact | Effort | Prioritas |
|---|------|:------:|:------:|:---------:|
| 1 | Tambah pagination (`limit`/`offset`) di GET /items | 🔴 Tinggi | Kecil | **P0** |
| 2 | Fix ST_Transform ke 4326 di GET /items & GET /items/{id} | 🔴 Tinggi | Kecil | **P0** |
| 3 | Endpoint import file dengan field mapping | 🔴 Tinggi | Besar | **P1** |
| 4 | Filter kolom internal (create_gn, update_gn) dari OGC response | 🟡 Sedang | Kecil | **P1** |
| 5 | Upgrade plugin: Field Mapper dialog untuk copy-paste | 🟡 Sedang | Besar | **P2** |
| 6 | Hitung `numberMatched` terpisah (COUNT) | 🟡 Sedang | Kecil | **P2** |
| 7 | Validasi `tableName` dari URL path secara konsisten | 🟡 Sedang | Kecil | **P2** |
| 8 | Rename/alter kolom endpoint + UI | 🟢 Rendah | Sedang | **P3** |

---

## 8. Kesimpulan

### Apa yang SUDAH bekerja baik:
- ✅ Koneksi QGIS ke OGC API GISNAS berjalan
- ✅ CRUD feature (create, read, update, delete) dari QGIS berfungsi
- ✅ Manajemen kolom (tambah/hapus) via plugin custom — ini **fitur unik** GISNAS

### Apa yang TIDAK BISA di-solve (limitasi QGIS):
- ❌ QGIS **tidak punya** field mapper saat copy-paste — ini berlaku untuk SEMUA server OGC, bukan cuma GISNAS
- ❌ QGIS **tidak bisa** mengirim perintah DDL (ALTER TABLE) ke server — standar OGC tidak mendukung ini

### Apa yang BISA di-improve di sisi GISNAS:
- 🔧 Tambah endpoint **import file + field mapping** di backend
- 🔧 Tambah **pagination** agar data besar tidak hang
- 🔧 Fix **CRS transform** agar geometry selalu dalam EPSG:4326
- 🔧 Upgrade plugin dengan **Field Mapper dialog** untuk copy-paste antar layer

> **TL;DR**: Masalah copy-paste dan field mapping adalah **limitasi desain QGIS**, bukan bug GISNAS. Solusi terbaik adalah membuat endpoint import + field mapper di sisi server/plugin, karena tidak mungkin mengubah perilaku QGIS itu sendiri.
