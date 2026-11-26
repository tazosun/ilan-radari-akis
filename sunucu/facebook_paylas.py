#!/usr/bin/env python3
"""Alım Var Facebook sayfasına ilan paylaşır: her ilan ayrı bir gönderi.

Günde bir ilan, saat 06:00'da (Türkiye saati). Betik her gün GitHub Actions ile çalışır
(.github/workflows/facebook.yml) ve yeni ilanları Facebook'un kendi zamanlayıcısıyla ileriki
günlerin 06:00'sına planlar. Yayın gününde başvurusunun bitmesine 15 günden fazla kalan ilanlar alınır.

Sayfa kimliği ve erişim anahtarı ortam değişkenlerinden gelir (GitHub'da "secret" olarak saklanır):
    ALIMVAR_FB_SAYFA, ALIMVAR_FB_ANAHTAR
Paylaşılanların kaydı: akis/facebook-paylasilanlar.json (iş akışı depoya geri yazar).

Kullanım:
    python3 facebook_paylas.py            # planla (bugünün gönderisi yoksa birini hemen paylaşır)
    python3 facebook_paylas.py --deneme   # paylaşmadan planı yazdır
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone

DEPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AKIS = os.path.join(DEPO, "akis", "ilanlar.json")
KAYIT = os.path.join(DEPO, "akis", "facebook-paylasilanlar.json")
GRAPH = "https://graph.facebook.com/v21.0"
APP_STORE = "https://apps.apple.com/tr/app/id6837452333"
ENFAZLA = int(os.environ.get("ALIMVAR_FB_ADET") or 30)  # bir çalışmada en fazla planlanacak gönderi
KALAN_GUN = 15       # yayın gününde başvurunun bitmesine bundan fazla gün kalmış olmalı
UFUK_GUN = 25        # en fazla bu kadar gün sonrasına planla (Facebook sınırı 30 gün)
ARALIK_SN = 5         # istekler arası bekleme
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


def paylas(sayfa_id, anahtar, mesaj, zaman=None):
    """Gönderiyi hemen yayınlar; zaman verilirse Facebook'ta o ana planlar."""
    alanlar = {"message": mesaj, "link": APP_STORE, "access_token": anahtar}
    if zaman is not None:
        alanlar.update(published="false", scheduled_publish_time=str(int(zaman.timestamp())))
    veri = urllib.parse.urlencode(alanlar).encode()
    istek = urllib.request.Request(f"{GRAPH}/{sayfa_id}/feed", data=veri, method="POST")
    with urllib.request.urlopen(istek, timeout=60) as y:
        return json.load(y).get("id")


def plan_yap(ilanlar, kayit, simdi):
    """Her güne bir ilan: kayıttaki son günden sonraki günlere 06:00 yerleştirir.

    Bir ilan ancak yayın gününde başvurusunun bitmesine KALAN_GUN'den fazla varsa alınır.
    Son başvurusu yakın olan önce gelir. Bugün gönderi yoksa bugünkü ilan hemen paylaşılır
    (06:00 geçmediyse 06:00'ya planlanır)."""
    bugun = simdi.date()
    dolu = {date.fromisoformat(k["tarih"][:10]) for k in kayit.values() if k.get("tarih")}
    gun = max([bugun] + [d + timedelta(days=1) for d in dolu if d >= bugun])
    adaylar = sorted((i for i in ilanlar if i["id"] not in kayit),
                     key=lambda i: (i["sonBasvuru"], i["id"]))
    plan = []
    for ilan in adaylar:
        if (gun - bugun).days > UFUK_GUN:
            break
        son = date.fromisoformat(ilan["sonBasvuru"][:10])
        if (son - gun).days <= KALAN_GUN:
            continue  # o gün yayınlansa bitmesine 15 günden az kalır
        saat = datetime.combine(gun, dtime(6, 0), TR)
        plan.append((ilan, None if saat <= simdi + timedelta(minutes=15) else saat, gun))
        gun += timedelta(days=1)
    return plan


def main():
    deneme = "--deneme" in sys.argv
    simdi = datetime.now(TR)
    ilanlar = oku(AKIS, {}).get("ilanlar", [])
    kayit = oku(KAYIT, {})
    plan = plan_yap(ilanlar, kayit, simdi)[:ENFAZLA]
    print(f"=== {simdi:%Y-%m-%d %H:%M} · {len(plan)} ilan planlanacak (günde 1, saat 06:00) ===")
    for ilan, saat, gun in plan:
        print(f"{gun} {'hemen' if saat is None else '06:00'} · son başvuru {ilan['sonBasvuru'][:10]} · {ilan['kurum']} · {ilan['baslik']}")
    if deneme:
        if plan:
            print("-" * 40); print(gonderi(plan[0][0], plan[0][2]))
        return
    sayfa, anahtar = os.environ.get("ALIMVAR_FB_SAYFA", ""), os.environ.get("ALIMVAR_FB_ANAHTAR", "")
    if not sayfa or not anahtar:
        sys.exit("ALIMVAR_FB_SAYFA ve ALIMVAR_FB_ANAHTAR tanımlı değil.")
    for n, (ilan, saat, gun) in enumerate(plan):
        if n:
            time.sleep(ARALIK_SN)
        try:
            gid = paylas(sayfa, anahtar, gonderi(ilan, gun), saat)
        except urllib.error.HTTPError as e:
            hata = e.read().decode(errors="replace")[:300]
            print(f"HATA {e.code} {ilan['id']}: {hata}")
            if e.code in (400, 401, 403) and ("OAuthException" in hata or "permission" in hata.lower()):
                sys.exit("Erişim anahtarı geçersiz ya da yetkisi yok; paylaşım durduruldu.")
            break  # sıradaki günler kaymasın: kalanlar bir sonraki çalışmada planlanır
        except Exception as e:  # ağ hatası vb.
            print(f"HATA {ilan['id']}: {e}")
            break
        kayit[ilan["id"]] = {"gonderi": gid, "tarih": (saat or datetime.now(TR)).isoformat(timespec="seconds"),
                             "durum": "paylaşıldı" if saat is None else "planlandı"}
        yaz(KAYIT, kayit)
        print(f"{'Paylaşıldı' if saat is None else 'Planlandı ' + gun.isoformat()}: {ilan['kurum']} · {ilan['baslik']} -> {gid}")


if __name__ == "__main__":
    main()
