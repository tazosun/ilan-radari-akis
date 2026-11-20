# İlan Radarı — ilan akışı

Kamu personel alım ilanlarını T.C. Cumhurbaşkanlığı Strateji ve Bütçe Başkanlığı'nın resmî
ilan sitesinden ([kamuilan.sbb.gov.tr](https://kamuilan.sbb.gov.tr)) okuyup tek bir JSON
dosyasında toplar.

- `toplayici/topla.py` — toplayıcı (yalnızca Python standart kütüphanesi)
- `akis/ilanlar.json` — üretilen akış
- `.github/workflows/ilan-topla.yml` — saatte bir çalıştırır, ilanlar değiştiyse kaydeder

Elle çalıştırmak için:

```bash
python3 toplayici/topla.py akis/ilanlar.json
```

Bu proje hiçbir kamu kurumunu temsil etmez. İlanların doğruluğu için resmî kaynağa bakın.
