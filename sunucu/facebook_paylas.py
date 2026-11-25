#!/usr/bin/env python3
"""Alım Var Facebook sayfasına ilan paylaşır: her ilan ayrı bir gönderi.

Her sabah 06:00'da (Türkiye saati) GitHub Actions ile çalışır (.github/workflows/facebook.yml).
Daha önce paylaşılmamış ve başvurusu hâlâ açık ilanları paylaşır; bir çalışmada en
fazla ENFAZLA ilan paylaşılır, kalanlar ertesi sabaha kalır.

Sayfa kimliği ve erişim anahtarı ortam değişkenlerinden gelir (GitHub'da "secret" olarak saklanır):
    ALIMVAR_FB_SAYFA, ALIMVAR_FB_ANAHTAR
Paylaşılanların kaydı: akis/facebook-paylasilanlar.json (iş akışı depoya geri yazar).

Kullanım:
    python3 facebook_paylas.py            # paylaş
    python3 facebook_paylas.py --deneme   # paylaşmadan gönderileri yazdır
    python3 facebook_paylas.py --deneme 1 # ilk gönderiyi yazdır
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

DEPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AKIS = os.path.join(DEPO, "akis", "ilanlar.json")
KAYIT = os.path.join(DEPO, "akis", "facebook-paylasilanlar.json")
GRAPH = "https://graph.facebook.com/v21.0"
APP_STORE = "https://apps.apple.com/tr/app/id6837452333"
ENFAZLA = 15          # bir sabahta en fazla gönderi
ARALIK_SN = 45        # gönderiler arası bekleme (Facebook'a art arda yüklenmemek için)
TR = timezone(timedelta(hours=3))

TURLER = {
    "memur": ("🏛", "Memur", "#memuralımı"),
    "sozlesmeli": ("📄", "Sözleşmeli personel", "#sözleşmelipersonel"),
    "isci": ("🛠", "Kamu işçisi", "#kamuişçisi"),
    "akademik": ("🎓", "Akademik personel", "#akademikpersonel"),
    "askeri": ("🛡", "Askerî personel", "#askerîpersonel"),
}
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def tarih_yazi(s):
    d = date.fromisoformat(s[:10])
    return f"{d.day} {AYLAR[d.month - 1]} {d.year}"


def gonderi(ilan, bugun):
    simge, tur_adi, etiket = TURLER.get(ilan.get("tur"), ("📢", "Kamu personeli", "#personelalımı"))
    satirlar = [f"📢 {ilan['baslik']}", f"{ilan['kurum']}", ""]
    bilgi = [f"{simge} {ilan.get('altTur') or tur_adi}"]
    if ilan.get("kadroSayisi"):
        bilgi.append(f"👥 {ilan['kadroSayisi']} kadro")
    iller = ilan.get("iller") or []
    bilgi.append("📍 " + (", ".join(iller[:3]) + (" ve diğer iller" if len(iller) > 3 else "") if iller else "İl belirtilmemiş"))
    satirlar.append(" · ".join(bilgi))
    son = date.fromisoformat(ilan["sonBasvuru"][:10])
    kalan = (son - bugun).days
    ek = " (son gün!)" if kalan == 0 else f" ({kalan} gün kaldı)" if kalan <= 7 else ""
    if ilan.get("basvuruBaslangic") and date.fromisoformat(ilan["basvuruBaslangic"][:10]) > bugun:
        satirlar.append(f"🗓 Başvuru: {tarih_yazi(ilan['basvuruBaslangic'])} ile {tarih_yazi(ilan['sonBasvuru'])} arası")
    else:
        satirlar.append(f"🗓 Son başvuru: {tarih_yazi(ilan['sonBasvuru'])}{ek}")
    if ilan.get("minPuan") and ilan.get("puanTuru"):
        satirlar.append(f"📊 Taban puan: {ilan['puanTuru']} {ilan['minPuan']}")
    satirlar += [
        "",
        "Sana uygun ilanları kaçırmamak için ücretsiz Alım Var uygulaması: öğrenimine ve KPSS puanına uyan ilanları ayırır, yeni ilan çıkınca haber verir.",
        f"📲 {APP_STORE}",
        "",
        "ℹ️ Kaynak: kamuilan.sbb.gov.tr. Başvuru şartlarını resmî ilan metninden teyit edin. Alım Var hiçbir kamu kurumunu temsil etmez.",
        "",
        f"#kamuilanları {etiket} #kpss #alımvar",
    ]
    return "\n".join(satirlar)


def oku(yol, varsayilan):
    try:
        with open(yol, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return varsayilan


def yaz(yol, veri):
    gecici = yol + ".tmp"
    with open(gecici, "w", encoding="utf-8") as f:
        json.dump(veri, f, ensure_ascii=False, indent=1)
    os.replace(gecici, yol)


def paylas(sayfa_id, anahtar, mesaj):
    veri = urllib.parse.urlencode({"message": mesaj, "link": APP_STORE, "access_token": anahtar}).encode()
    istek = urllib.request.Request(f"{GRAPH}/{sayfa_id}/feed", data=veri, method="POST")
    with urllib.request.urlopen(istek, timeout=60) as y:
        return json.load(y).get("id")


def main():
    deneme = "--deneme" in sys.argv
    sinir = int(sys.argv[sys.argv.index("--deneme") + 1]) if deneme and len(sys.argv) > sys.argv.index("--deneme") + 1 else ENFAZLA
    bugun = datetime.now(TR).date()
    ilanlar = oku(AKIS, {}).get("ilanlar", [])
    kayit = oku(KAYIT, {})
    adaylar = [i for i in ilanlar
               if i["id"] not in kayit and date.fromisoformat(i["sonBasvuru"][:10]) >= bugun]
    # Son başvurusu en yakın olan önce: okuyan başvurmaya yetişsin.
    adaylar.sort(key=lambda i: (i["sonBasvuru"], i["id"]))
    secilen = adaylar[:sinir]
    print(f"=== {datetime.now(TR):%Y-%m-%d %H:%M} · {len(adaylar)} paylaşılmamış ilan, {len(secilen)} paylaşılacak ===")
    if deneme:
        for i in secilen:
            print("-" * 40); print(gonderi(i, bugun))
        return
    ayar = {"sayfa_id": os.environ.get("ALIMVAR_FB_SAYFA", ""), "anahtar": os.environ.get("ALIMVAR_FB_ANAHTAR", "")}
    if not ayar["anahtar"] or not ayar["sayfa_id"]:
        sys.exit("ALIMVAR_FB_SAYFA ve ALIMVAR_FB_ANAHTAR tanımlı değil.")
    # GitHub zamanlayıcısı erken başlatırsa 06:00'yı bekle.
    simdi = datetime.now(TR)
    hedef = simdi.replace(hour=6, minute=0, second=0, microsecond=0)
    if "--bekle" in sys.argv and simdi < hedef and (hedef - simdi).total_seconds() < 3600:
        time.sleep((hedef - simdi).total_seconds())
    for n, ilan in enumerate(secilen):
        if n:
            time.sleep(ARALIK_SN)
        try:
            gid = paylas(ayar["sayfa_id"], ayar["anahtar"], gonderi(ilan, bugun))
        except urllib.error.HTTPError as e:
            hata = e.read().decode(errors="replace")[:300]
            print(f"HATA {e.code} {ilan['id']}: {hata}")
            if e.code in (400, 401, 403) and ("OAuthException" in hata or "permission" in hata.lower()):
                sys.exit("Erişim anahtarı geçersiz ya da yetkisi yok; paylaşım durduruldu.")
            continue
        except Exception as e:  # ağ hatası vb.: bu ilanı yarın tekrar dene
            print(f"HATA {ilan['id']}: {e}")
            continue
        kayit[ilan["id"]] = {"gonderi": gid, "tarih": datetime.now(TR).isoformat(timespec="seconds")}
        yaz(KAYIT, kayit)
        print(f"Paylaşıldı: {ilan['kurum']} · {ilan['baslik']} -> {gid}")


if __name__ == "__main__":
    main()
