# 🗺️ GISNAS - Project Roadmap

Dokumen ini berisi daftar tugas (*checklist*) untuk pengembangan aplikasi WebGIS **GISNAS**.
## ☕ Donasi

Jika proyek ini bermanfaat, Anda dapat mendukung pengembangan selanjutnya melalui:

[![Donasi via Ko-fi](https://img.shields.io/badge/Support%20me-Ko--fi-FF5E5B?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/gisnas)

https://ko-fi.com/gisnas

## 1. QGIS Plugin
- [x] Gunakan gisnas_sketsa.zip lalu Install plugin melalui Install from ZIP

## 1. Inisialisasi Proyek & Infrastruktur
- [x] Setup `docker-compose.yml`
- [x] Setup container PostGIS
- [x] Inisialisasi kerangka Backend (Go + Dockerfile)
- [x] Inisialisasi kerangka Frontend (ReactJS + Vite + Dockerfile)
- [x] Konfigurasi volume & environment variables untuk production (VPS)

## 2. Frontend (ReactJS)
- [x] Setup Routing (React Router)
- [x] **Halaman Login & Daftar**
- [x] **Halaman Dashboard Utama**
- [x] **Komponen Map Preview**
  - [x] Integrasi peta dasar (MapLibre GL JS )
  - [x] Mode *Private* (Harus login)
- [x] **Fitur Upload SHP / Bikin Baru**
  - [x] UI untuk *drag-and-drop* file ZIP (.shp)
- [x] **Fitur Manajemen Data**
- [x] **Fitur Styling Peta**
  - [x] UI untuk mengubah warna/simbol layer
- [x] **Halaman Konfigurasi OGC API**
  - [x] Menampilkan URL OGC API
  - [x] Manajemen Token: Generate, Start (Running), Stop (Revoke akses)

## 3. Backend (Go)
- [x] Setup koneksi ke PostGIS (pgx/gorm)
- [x] Autentikasi JWT (Endpoint `/login`, `/register`)
- [x] API untuk mengunggah dan mengekstrak file SHP
- [x] Integrasi alat pemrosesan spasial (menyimpan SHP ke PostGIS)
- [x] API Manajemen Tabel (Menambah/Mengedit kolom secara dinamis)
- [x] API untuk menyimpan konfigurasi *Styling*
- [x] **Endpoint OGC API Features** (Sesuai standar OGC)
  - [x] Middleware Otentikasi (Cek Header/Token Query Param)
  - [x] Validasi status token (Hanya izinkan akses jika status = "Running")
  - [x] Mendukung operasi CRUD Edit (Create, Update, Delete) langsung dari QGIS

## 4. Database (PostGIS)
- [x] Desain skema tabel `users`
- [x] Desain skema tabel `datasets` (metadata)
- [x] Desain skema tabel `api_tokens` (id, token, status: running/stopped)
- [x] Desain struktur penyimpanan *styling*

---

## 📄 Lisensi

Proyek ini dilisensikan di bawah **Apache License 2.0** – lihat file [LICENSE](LICENSE) untuk detail.

```
Copyright 2026 Hidayatullah
```



