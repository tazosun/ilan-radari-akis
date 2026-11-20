# Alım Var — ilan akışı

Kamu personel alım ilanlarını T.C. Cumhurbaşkanlığı Strateji ve Bütçe Başkanlığı'nın resmî
ilan sitesinden ([kamuilan.sbb.gov.tr](https://kamuilan.sbb.gov.tr)) okuyup tek bir JSON
dosyasında toplar.

- `toplayici/topla.py` — toplayıcı (yalnızca Python standart kütüphanesi)
- `akis/ilanlar.json` — üretilen akış
- `sunucu/calistir.sh` ve `sunucu/cron` — Türkiye'deki sunucuda saatte bir çalışır, ilanlar değiştiyse akışı gönderir
- `.github/workflows/ilan-topla.yml` — yalnızca elle deneme; kaynak site GitHub sunucularını engelliyor (403)

Elle çalıştırmak için:

```bash
python3 toplayici/topla.py akis/ilanlar.json
```

Bu proje hiçbir kamu kurumunu temsil etmez. İlanların doğruluğu için resmî kaynağa bakın.
