#!/usr/bin/env python3
"""Alım Var toplayıcısı.

Strateji ve Bütçe Başkanlığı'nın resmî "Kamu Personeli Alım İlanları" sitesindeki
(kamuilan.sbb.gov.tr) açık ilanları kategori kategori okur ve uygulamanın beklediği
JSON akışını üretir. Yalnızca Python standart kütüphanesini kullanır.

Kullanım:  python3 topla.py cikti/ilanlar.json
"""
from __future__ import annotations

import hashlib
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

KAYNAK = "https://kamuilan.sbb.gov.tr/"
KULLANICI_AJANI = "AlimVarToplayici/0.1 (+kamu ilan takip uygulamasi)"
BEKLEME_SN = 1.5  # siteyi yormamak için istekler arası bekleme
DENEME_SAYISI = 3  # bir kategori isteği 400 alırsa toplam deneme sayısı

# Sitedeki kategori düğmesi -> (uygulamadaki tür, alt tür adı)
KATEGORILER: dict[str, tuple[str, str]] = {
    "Button1": ("memur", "A Grubu Memur (Kariyer Meslek)"),
    "Button2": ("memur", "B Grubu Memur"),
    "Button6": ("memur", "Yargı Mensubu (Hâkim - Savcı)"),
    "Button21": ("sozlesmeli", "Kariyer Sözleşmeli Personel"),
    "Button16": ("sozlesmeli", "4/B Sözleşmeli Personel"),
    "Button17": ("sozlesmeli", "KİT Sözleşmeli Personel"),
    "Button18": ("sozlesmeli", "Kurumsal Sözleşmeli Personel"),
    "Button19": ("akademik", "Öğretim Üyesi"),
    "Button20": ("akademik", "Öğretim Görevlisi"),
    "Button23": ("akademik", "Araştırma Görevlisi"),
    "Button22": ("isci", "Kariyer İşçi"),
    "Button7": ("isci", "Sürekli İşçi"),
    "Button8": ("isci", "Geçici İşçi"),
    "Button9": ("isci", "Engelli İşçi"),
    "Button11": ("isci", "Eski Hükümlü İşçi"),
    "Button13": ("askeri", "Askerî Personel"),
}

AYLAR = {
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6,
    "temmuz": 7, "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12,
}

ILLER = [
    "Adana", "Adıyaman", "Afyonkarahisar", "Ağrı", "Aksaray", "Amasya", "Ankara", "Antalya", "Ardahan", "Artvin",
    "Aydın", "Balıkesir", "Bartın", "Batman", "Bayburt", "Bilecik", "Bingöl", "Bitlis", "Bolu", "Burdur",
    "Bursa", "Çanakkale", "Çankırı", "Çorum", "Denizli", "Diyarbakır", "Düzce", "Edirne", "Elazığ", "Erzincan",
    "Erzurum", "Eskişehir", "Gaziantep", "Giresun", "Gümüşhane", "Hakkari", "Hatay", "Iğdır", "Isparta", "İstanbul",
    "İzmir", "Kahramanmaraş", "Karabük", "Karaman", "Kars", "Kastamonu", "Kayseri", "Kilis", "Kırıkkale", "Kırklareli",
    "Kırşehir", "Kocaeli", "Konya", "Kütahya", "Malatya", "Manisa", "Mardin", "Mersin", "Muğla", "Muş",
    "Nevşehir", "Niğde", "Ordu", "Osmaniye", "Rize", "Sakarya", "Samsun", "Şanlıurfa", "Siirt", "Sinop",
    "Şırnak", "Sivas", "Tekirdağ", "Tokat", "Trabzon", "Tunceli", "Uşak", "Van", "Yalova", "Yozgat", "Zonguldak",
]

TR_KUCUK = str.maketrans("Iİ", "ıi")
TR_BUYUK = str.maketrans("ıi", "Iİ")


def kucuk(s: str) -> str:
    return s.translate(TR_KUCUK).lower()


def buyuk(s: str) -> str:
    return s.translate(TR_BUYUK).upper()


KUCUK_KALSIN = {"ve", "ile", "veya", "için", "de", "da"}


def baslik_bicimi(s: str) -> str:
    """'BALIKESİR ÜNİVERSİTESİ' -> 'Balıkesir Üniversitesi' (Türkçe kurallarıyla)."""
    kelimeler = []
    for i, k in enumerate(s.split()):
        kk = kucuk(k)
        if i > 0 and kk in KUCUK_KALSIN:
            kelimeler.append(kk)
        elif re.fullmatch(r"[A-ZÇĞİÖŞÜ]{2,4}", k) and k in {"KİT", "TSK", "SGK", "TÜBİTAK", "AFAD", "TRT", "PTT", "MSB", "MEB"}:
            kelimeler.append(k)
        elif "/" in k or any(c.isdigit() for c in k):
            kelimeler.append(k)
        else:
            kelimeler.append(buyuk(kk[:1]) + kk[1:])
    return " ".join(kelimeler)


class Oturum:
    def __init__(self) -> None:
        self.acici = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.acici.addheaders = [("User-Agent", KULLANICI_AJANI)]

    def getir(self, veri: dict[str, str] | None = None) -> str:
        govde = urllib.parse.urlencode(veri).encode() if veri is not None else None
        with self.acici.open(KAYNAK, data=govde, timeout=60) as yanit:
            return yanit.read().decode("utf-8", errors="replace")


def form_alanlari(sayfa: str) -> dict[str, str]:
    alanlar = {}
    for ad, deger in re.findall(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', sayfa):
        alanlar[ad] = html.unescape(deger)
    return alanlar


def dugmeler(sayfa: str) -> dict[str, str]:
    """Sayfadaki kategori düğmeleri: ad -> üzerinde yazan metin."""
    return {ad: html.unescape(deger) for ad, deger in
            re.findall(r'<input type="submit" name="(Button\d+)" value="([^"]+)"', sayfa)}


LISTE_OGESI = re.compile(
    r"<a href='(ilanDetay\.aspx\?kod=[^']+)'[^>]*>.*?"
    r"<p class='alt_p1'>(.*?)</p>\s*<p class='alt_p2'>(.*?)<em[^>]*>\s*\((.*?)\)\s*</em>",
    re.S,
)


def liste_oku(sayfa: str) -> list[tuple[str, str, str, str]]:
    i = sayfa.find('id="nav2"')
    if i < 0:
        return []
    son = sayfa.find("</ul>", i)
    bolum = sayfa[i:son if son > 0 else None]
    return [tuple(html.unescape(re.sub(r"\s+", " ", p)).strip() for p in m.groups())
            for m in LISTE_OGESI.finditer(bolum)]


def tarih_coz(metin: str, bugun: date) -> tuple[date, date] | None:
    """'20 Kasım - 4 Aralık' -> (başlangıç, bitiş). Yıl yazılmadığı için bugüne göre tahmin edilir."""
    m = re.fullmatch(r"(\d{1,2})\s+(\S+)\s*-\s*(\d{1,2})\s+(\S+)", metin.strip())
    if not m:
        return None
    g1, a1, g2, a2 = m.groups()
    ay1, ay2 = AYLAR.get(kucuk(a1)), AYLAR.get(kucuk(a2))
    if not ay1 or not ay2:
        return None
    yil = bugun.year
    bas = date(yil, ay1, int(g1))
    # Açık ilanların başlangıcı bugünden çok ileride olamaz; öyleyse geçen yıla aittir.
    if bas - bugun > timedelta(days=120):
        bas = date(yil - 1, ay1, int(g1))
    # Aralık sonunda yayımlanan, Ocak'ta başlayan ilanlar gelecek yıla aittir.
    elif bugun - bas > timedelta(days=240):
        bas = date(yil + 1, ay1, int(g1))
    # Aralık'ta başlayıp Ocak'ta biten ilanlar.
    son = date(bas.year + (1 if ay2 < ay1 else 0), ay2, int(g2))
    return bas, son


def il_bul(kurum: str) -> list[str]:
    k = kucuk(kurum)
    return [il for il in ILLER if re.search(r"(^|\s)" + re.escape(kucuk(il)) + r"(\s|$)", k)]


def aciklama_coz(aciklama: str) -> tuple[int | None, str, bool] | None:
    """'10 STAJYER HAZİNE KONTROLÖRÜ ALACAK - DÜZELTME İLANI' -> (10, 'Stajyer Hazine Kontrolörü Alımı', True).
    İptal duyuruları için None döner."""
    a = re.sub(r"\s+", " ", aciklama).strip()
    if "İPTAL" in a:
        return None
    duzeltme = bool(re.search(r"DÜZELTME|DÜLETME", a))
    a = re.sub(r"^.*(DEN|DAN) (DÜZELTME|DÜLETME) İLANI$", "", a)  # 'X ÜNİVERSİTESİNDEN DÜZELTME İLANI'
    a = re.sub(r"(\s*[-–&]\s*|\s+|^)(DÜZELTME|DÜLETME) İLANI$", "", a).strip()  # '... - DÜZELTME İLANI'
    kadro = None
    m = re.match(r"(\d+)\s+(?:ADET\s+)?(.*)", a)
    if m:
        kadro, a = int(m.group(1)), m.group(2)
    a = re.sub(r"\s+(ALACAK|ALIMI İLANI|ALIMI|İLANI)$", "", a).strip()
    if not a:
        baslik = "Düzeltme İlanı" if duzeltme else "Personel Alımı"
    elif "TEMİNİ" in a or "ALIM" in a:
        baslik = baslik_bicimi(a)
    else:
        baslik = f"{baslik_bicimi(a)} Alımı"
    return kadro, baslik, duzeltme


# Kategorinin kendisinden kesin bilinen asgari öğrenim şartı ve kullanıcıya gösterilecek not.
# Yalnızca mevzuattan kesin olanlar: emin olmadığımız kategorilerde asgari öğrenim yazmıyoruz.
# Öğrenim değerleri uygulamadaki Ogrenim türüyle aynı olmalı.
KATEGORI_SARTLARI: dict[str, tuple[str | None, str]] = {
    "Öğretim Üyesi": ("doktora",
        "Öğretim üyesi kadroları doktora gerektirir (2547 sayılı Kanun). Alan, yabancı dil ve "
        "diğer şartlar resmî ilan metninde."),
    "Öğretim Görevlisi": ("yuksekLisans",
        "Öğretim görevlisi kadroları en az yüksek lisans gerektirir; ALES ve yabancı dil puanı da "
        "istenebilir. Ayrıntılar resmî ilan metninde."),
    "Araştırma Görevlisi": ("lisans",
        "Araştırma görevlisi kadroları lisans mezuniyeti ve ALES puanı gerektirir; çoğunda yabancı "
        "dil puanı ve lisansüstü öğrencilik de istenir."),
    "A Grubu Memur (Kariyer Meslek)": ("lisans",
        "A grubu (kariyer meslek) kadrolar lisans mezuniyeti gerektirir; KPSS A grubu puanı ya da "
        "kurumun kendi sınavı istenir."),
    "Sürekli İşçi": (None,
        "Kamu işçi alımlarında genellikle KPSS istenmez; çoğu İŞKUR üzerinden kura ile yapılır."),
    "Geçici İşçi": (None,
        "Kamu işçi alımlarında genellikle KPSS istenmez; çoğu İŞKUR üzerinden kura ile yapılır."),
    "Engelli İşçi": (None,
        "Engelli işçi alımları İŞKUR üzerinden, engelli kontenjanından yapılır."),
    "Eski Hükümlü İşçi": (None,
        "Eski hükümlü işçi alımları İŞKUR üzerinden, eski hükümlü kontenjanından yapılır."),
}


def ilan_kur(detay: str, kurum: str, aciklama: str, tarihler: str, tur: str, alt_tur: str,
             bugun: date) -> dict | None:
    aralik = tarih_coz(tarihler, bugun)
    if not aralik:
        return None
    bas, son = aralik
    cozum = aciklama_coz(aciklama)
    if cozum is None:  # iptal duyurusu
        return None
    kadro, baslik, duzeltme = cozum
    kimlik = hashlib.sha1(f"{kurum}|{aciklama}|{tarihler}".encode()).hexdigest()[:12]
    return {
        "id": f"sbb-{kimlik}",
        "baslik": baslik,
        "kurum": baslik_bicimi(kurum),
        "tur": tur,
        "altTur": alt_tur,
        "iller": il_bul(kurum),
        "ogrenim": [],
        "puanTuru": None,
        "minPuan": None,
        "kadroSayisi": kadro,
        "duzeltme": duzeltme,
        "yayinTarihi": bas.isoformat(),
        "basvuruBaslangic": bas.isoformat(),
        "sonBasvuru": son.isoformat(),
        "kaynakURL": KAYNAK,
        "sartlar": [],
        # Kategoriden kesin bilinen şartlar (ilan metni okunamadığı için).
        "minOgrenim": KATEGORI_SARTLARI.get(alt_tur, (None, None))[0],
        "sartNotu": KATEGORI_SARTLARI.get(alt_tur, (None, None))[1],
        # Sitedeki satırın birebir metni: uygulama, resmî sitenin listesinde bu ilanı bulup
        # kullanıcının yerine tıklamak için kullanır (PDF yalnızca listeden açılınca gösteriliyor).
        "siteSatiri": {"kurum": kurum, "aciklama": aciklama, "tarihler": tarihler},
    }


def topla() -> dict:
    bugun = datetime.now(timezone(timedelta(hours=3))).date()  # Türkiye saati
    oturum = Oturum()
    ana = oturum.getir()
    alanlar = form_alanlari(ana)
    if "__VIEWSTATE" not in alanlar:
        raise RuntimeError("Ana sayfanın form alanları bulunamadı; site yapısı değişmiş olabilir.")

    dugme_metinleri = dugmeler(ana)
    ilanlar: dict[str, dict] = {}
    for dugme, (tur, alt_tur) in KATEGORILER.items():
        if dugme not in dugme_metinleri:
            print(f"{alt_tur}: düğme sitede yok, atlandı", file=sys.stderr)
            continue
        for deneme in range(1, DENEME_SAYISI + 1):
            time.sleep(BEKLEME_SN * deneme)
            try:
                # Bir tarayıcının göndereceği gibi: son sayfanın form alanları + basılan düğmenin kendi metni.
                sayfa = oturum.getir({**alanlar, dugme: dugme_metinleri[dugme]})
                break
            except urllib.error.HTTPError as hata:
                if hata.code != 400 or deneme == DENEME_SAYISI:
                    raise
                # Site birden çok sunucunun arkasında; form bilgisi başka sunucuya düşünce 400 veriyor.
                # Ana sayfayı yeni bir oturumla açıp düğmeye yeniden bas.
                print(f"{alt_tur}: HTTP 400, yeni oturumla tekrar ({deneme + 1}/{DENEME_SAYISI})", file=sys.stderr)
                time.sleep(BEKLEME_SN)
                oturum = Oturum()
                alanlar = form_alanlari(oturum.getir())
        yeni_alanlar = form_alanlari(sayfa)
        if "__VIEWSTATE" in yeni_alanlar:
            alanlar = yeni_alanlar
        ogeler = liste_oku(sayfa)
        print(f"{alt_tur}: {len(ogeler)} ilan", file=sys.stderr)
        for detay, kurum, aciklama, tarihler in ogeler:
            ilan = ilan_kur(detay, kurum, aciklama, tarihler, tur, alt_tur, bugun)
            if ilan and ilan["id"] not in ilanlar:
                ilanlar[ilan["id"]] = ilan

    # Kategorilerin hiçbirinde çıkmayan ilanlar için "Tüm İlanlar" listesine de bak.
    tum = liste_oku(ana)
    for detay, kurum, aciklama, tarihler in tum:
        ilan = ilan_kur(detay, kurum, aciklama, tarihler, "memur", "Diğer", bugun)
        if ilan and ilan["id"] not in ilanlar:
            ilanlar[ilan["id"]] = ilan
    print(f"Tüm İlanlar listesi: {len(tum)}, toplam benzersiz: {len(ilanlar)}", file=sys.stderr)

    if not ilanlar:
        raise RuntimeError("Hiç ilan okunamadı; eski akış korunacak.")

    return {
        "surum": 1,
        "guncelleme": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "kaynak": "T.C. Cumhurbaşkanlığı Strateji ve Bütçe Başkanlığı — kamuilan.sbb.gov.tr",
        "ilanlar": sorted(ilanlar.values(), key=lambda i: i["sonBasvuru"]),
    }


def main() -> None:
    cikti = sys.argv[1] if len(sys.argv) > 1 else "ilanlar.json"
    akis = topla()
    with open(cikti, "w", encoding="utf-8") as f:
        json.dump(akis, f, ensure_ascii=False, indent=1)
    print(f"{len(akis['ilanlar'])} ilan yazıldı: {cikti}", file=sys.stderr)


if __name__ == "__main__":
    main()
