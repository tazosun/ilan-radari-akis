#!/usr/bin/env python3
"""ÖSYM KPSS merkezî yerleştirme (tercih) kılavuzlarını okur.

ÖSYM her dönem herkese açık PDF tablolar yayımlar: Tablo-1 (ortaöğretim), Tablo-2 (ön lisans),
Tablo-3 (lisans). Her satır bir kadrodur: kurum, unvan, il, adet ve "aranan nitelik" kodları.
Nitelik kodu dosyaları her kodun metnini ve hangi mezuniyet programlarını kapsadığını verir.

PDF'ler `pdftotext -layout` ile yazıya çevrilir (poppler-utils). Yalnızca standart kütüphane.

Kullanım (deneme):  python3 osym.py [kpss20261] > rehber.json
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import date

KULLANICI_AJANI = "AlimVarToplayici/0.1 (+kamu ilan takip uygulamasi)"
BEKLEME_SN = 1.0
DENEME_SAYISI = 4
SAYFA = ("https://osym.gov.tr/{donem}-bazi-kamu-kurum-ve-kuruluslarinin-kadro-ve-pozisyonlarina-"
         "yerlestirme-yapmak-icin-tercih-kilavuzu-ve-tablolar")
ONBELLEK = os.path.expanduser("~/osym-onbellek.json")

AYLAR = {"ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5, "haziran": 6, "temmuz": 7,
         "ağustos": 8, "eylül": 9, "ekim": 10, "kasım": 11, "aralık": 12}

# Tablo numarası -> öğrenim düzeyi (uygulamadaki Ogrenim adlarıyla aynı)
DUZEYLER = {"1": "lise", "2": "onlisans", "3": "lisans"}

ISTIHDAM = ("KİT SÖZLEŞMELİ PERSONEL", "SÖZLEŞMELİ PERSONEL", "MEMUR", "İŞÇİ", "SÜREKLİ İŞÇİ", "GEÇİCİ PERSONEL")
# Sütuna sığmayıp bölünen istihdam şekli ("KİT SÖZLEŞMELİ" üst satırda, "PERSONEL" ana satırda).
ISTIHDAM_PARCA = ("PERSONEL",)
ILLER = {
    "ADANA", "ADIYAMAN", "AFYONKARAHİSAR", "AĞRI", "AKSARAY", "AMASYA", "ANKARA", "ANTALYA", "ARDAHAN", "ARTVİN",
    "AYDIN", "BALIKESİR", "BARTIN", "BATMAN", "BAYBURT", "BİLECİK", "BİNGÖL", "BİTLİS", "BOLU", "BURDUR", "BURSA",
    "ÇANAKKALE", "ÇANKIRI", "ÇORUM", "DENİZLİ", "DİYARBAKIR", "DÜZCE", "EDİRNE", "ELAZIĞ", "ERZİNCAN", "ERZURUM",
    "ESKİŞEHİR", "GAZİANTEP", "GİRESUN", "GÜMÜŞHANE", "HAKKARİ", "HATAY", "IĞDIR", "ISPARTA", "İSTANBUL", "İZMİR",
    "KAHRAMANMARAŞ", "KARABÜK", "KARAMAN", "KARS", "KASTAMONU", "KAYSERİ", "KİLİS", "KIRIKKALE", "KIRKLARELİ",
    "KIRŞEHİR", "KOCAELİ", "KONYA", "KÜTAHYA", "MALATYA", "MANİSA", "MARDİN", "MERSİN", "MUĞLA", "MUŞ", "NEVŞEHİR",
    "NİĞDE", "ORDU", "OSMANİYE", "RİZE", "SAKARYA", "SAMSUN", "ŞANLIURFA", "SİİRT", "SİNOP", "ŞIRNAK", "SİVAS",
    "TEKİRDAĞ", "TOKAT", "TRABZON", "TUNCELİ", "UŞAK", "VAN", "YALOVA", "YOZGAT", "ZONGULDAK",
}
TESKILAT = {"MERKEZ", "TAŞRA", "YURTDIŞI", "YURT DIŞI"}
SATIR = re.compile(r"^\s*(\d{9})\s+(\d+)\s+(.*)$")
# Sayfa başlığı ve altı: taşan satır sanılmasın.
BASLIK = re.compile(r"KURUM ADI|KADRO-ÜNVAN|İSTİHDAM|HİZMET|SINIFI|ÖSYM KODU|ARANAN NİTELİK|Aranan Nitelikleri|"
                    r"TABLO-\d|KPSS \d{4}|Nit\d+")


# ---------------------------------------------------------------- indirme

def getir(url: str, ikili: bool = False) -> bytes | str:
    """ÖSYM sunucusu ara sıra boş yanıt döner; birkaç kez dener."""
    son: Exception | None = None
    for deneme in range(DENEME_SAYISI):
        try:
            istek = urllib.request.Request(url, headers={"User-Agent": KULLANICI_AJANI})
            with urllib.request.urlopen(istek, timeout=90) as y:
                veri = y.read()
            time.sleep(BEKLEME_SN)
            return veri if ikili else veri.decode("utf-8", "replace")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as e:
            son = e
            time.sleep(3 * (deneme + 1))
    raise RuntimeError(f"{url} indirilemedi: {son}")


def pdf_yazi(veri: bytes) -> str:
    with tempfile.TemporaryDirectory() as d:
        yol = os.path.join(d, "a.pdf")
        with open(yol, "wb") as f:
            f.write(veri)
        return subprocess.run(["pdftotext", "-layout", yol, "-"], capture_output=True,
                              text=True, check=True).stdout


# ---------------------------------------------------------------- yardımcılar

def parcalar(satir: str) -> list[tuple[int, str]]:
    """Satırı en az iki boşlukla ayrılmış parçalara böler: (başlangıç sütunu, metin)."""
    return [(m.start(), m.group()) for m in re.finditer(r"\S+(?: \S+)*", satir)]


def bosluk_bol(bosluklar: list[str], onceki_var: bool) -> tuple[list[str], list[str]]:
    """İki kayıt arasındaki taşan satırları böler: pdftotext çok satırlı hücreyi dikey ortalar,
    bu yüzden aradaki satırların ilk yarısı önceki kaydın altı, kalanı sonrakinin üstüdür."""
    if not onceki_var:
        return [], bosluklar
    yari = len(bosluklar) // 2
    return bosluklar[:yari], bosluklar[yari:]


def birlestir(*metinler: str) -> str:
    return re.sub(r"\s+", " ", " ".join(m for m in metinler if m)).strip()


# ---------------------------------------------------------------- kadro tabloları

def ana_satir_coz(govde: str) -> dict | None:
    """ÖSYM kodu ve SBB numarasından sonraki kısmı çözer."""
    # Sondaki sayılar: isteğe bağlı derece ("6" ya da "6,9"), adet ve 4 haneli nitelik kodları.
    # Aralarında bazen tek boşluk kalır ("1 4685"), bu yüzden sütunlara değil sözcüklere bakılır.
    m = re.match(r"^(.*?\S)((?:\s+\d+(?:,\d+)*)+)\s*$", govde)
    if not m:
        return None
    sayilar = m.group(2).split()
    kodlar: list[str] = []
    while sayilar and re.fullmatch(r"\d{4}", sayilar[-1]) and len(sayilar) > 1:
        kodlar.insert(0, sayilar.pop())
    if not sayilar or not re.fullmatch(r"\d+", sayilar[-1]):
        return None
    adet = int(sayilar.pop())
    metinler = [t for _, t in parcalar(m.group(1))]
    if not metinler:
        return None
    # Baştan: kurum ve istihdam şekli (uzun kurum adlarında aralarında tek boşluk kalabilir).
    kurum, istihdam, i = "", "", 0
    for i, t in enumerate(metinler):
        for ist in ISTIHDAM + ISTIHDAM_PARCA:
            if t == ist or (ist not in ISTIHDAM_PARCA and t.endswith(" " + ist)):
                kurum = birlestir(*metinler[:i], t[: -len(ist)])
                istihdam = ist
                break
        if istihdam:
            break
    if not istihdam:
        return None
    kalan = metinler[i + 1:]
    if not kalan:
        return None
    unvan = kalan.pop(0)
    # Unvan ile il arasında tek boşluk kalmışsa ("DAVA TAKİP MEMURU ADANA") ayır.
    if not (kalan and kalan[0] in ILLER):
        for il_adi in sorted(ILLER, key=len, reverse=True):
            if unvan.endswith(" " + il_adi):
                unvan, kalan = unvan[: -len(il_adi) - 1], [il_adi] + kalan
                break
    # Hizmet sınıfı (GİH, TH, SH…) ve teşkilat sondadır; il unvandan hemen sonra gelir.
    if kalan and re.fullmatch(r"[A-ZÇĞİÖŞÜ]{1,4}", kalan[-1]) and kalan[-1] not in TESKILAT:
        kalan.pop()
    if kalan and kalan[-1] in TESKILAT:
        kalan.pop()
    il = kalan.pop(0) if kalan else ""
    ilce = kalan[0] if kalan else ""
    # İl ile ilçe arasında tek boşluk kalmışsa ("KAHRAMANMARAŞ MERKEZ") ayır.
    if il not in ILLER:
        for il_adi in sorted(ILLER, key=len, reverse=True):
            if il.startswith(il_adi + " "):
                il, ilce = il_adi, il[len(il_adi) + 1:]
                break
    return {"kurum": kurum, "istihdam": istihdam, "unvan": unvan, "il": il, "ilce": ilce,
            "adet": adet, "nitelikler": kodlar}


def tablo_coz(yazi: str, duzey: str) -> list[dict]:
    satirlar = yazi.splitlines()
    kayitlar: list[tuple[int, dict, dict[str, int]]] = []  # (satır no, kayıt, sütun başları)
    for no, s in enumerate(satirlar):
        m = SATIR.match(s)
        if not m:
            continue
        govde_bas = m.start(3)
        k = ana_satir_coz(m.group(3))
        if not k:
            continue
        # Kurum ve unvan sütunlarının ekrandaki başlangıcı (taşan satırları eşlemek için).
        ps = parcalar(s)
        bas = {"kurum": govde_bas}
        for ad in ("istihdam", "unvan"):
            for p, t in ps:
                if p > max(bas.values()) and (t == k[ad] or t.endswith(" " + k[ad]) or t.startswith(k[ad])):
                    bas[ad] = p + (len(t) - len(k[ad]) if t.endswith(" " + k[ad]) else 0)
                    break
        k["kod"] = m.group(1)
        k["duzey"] = duzey
        kayitlar.append((no, k, bas))

    def ekle(k: dict, bas: dict[str, int], satir: str, once: bool) -> None:
        if BASLIK.search(satir):
            return
        for p, t in parcalar(satir):
            # Başlık, sayfa altı ve dipnot satırlarını atla.
            if re.search(r"Aranan Nitelikleri|TABLO-|KPSS \d{4}|ÖSYM KODU|^\d+$", t):
                continue
            hedef = min(bas, key=lambda a: abs(bas[a] - p))
            if abs(bas[hedef] - p) > 12:
                continue
            k[hedef] = birlestir(t, k[hedef]) if once else birlestir(k[hedef], t)
            if hedef == "istihdam" and k[hedef] not in ISTIHDAM:
                k[hedef] = next((i for i in ISTIHDAM if k[hedef].endswith(i)), k[hedef])

    sonuc: list[dict] = []
    onceki_no = -1
    for sira, (no, k, bas) in enumerate(kayitlar):
        # Taşan hücre satırları ana satırın üstünde kalır (ana satır hücrenin altına hizalı).
        ust = [satirlar[j] for j in range(onceki_no + 1, no) if satirlar[j].strip()]
        for s in reversed(ust):
            ekle(k, bas, s, once=True)
        onceki_no = no
        sonuc.append(k)
    for k in sonuc:
        if k["istihdam"] in ISTIHDAM_PARCA:
            k["istihdam"] = "SÖZLEŞMELİ PERSONEL"  # üst parça bulunamadıysa en yaygın biçim
    return sonuc


# ---------------------------------------------------------------- nitelik kodları

def nitelik_coz(yazi: str) -> dict[str, dict]:
    """Kod -> {metin, alanlar}. Kod, açıklama ve mezuniyet alanı kodları ayrı sütunlardadır;
    uzun açıklamalar kod satırının üstüne ve altına taşar (pdftotext dikey ortalar)."""
    satirlar = [s for s in yazi.splitlines() if s.strip()]
    baslik = re.compile(r"ARANAN NİTELİKLER|NİTELİKLER$|Mezuniyet Alanı|ÖĞRENİM KOŞUL|Nitelik Kodları|Nitelik Adı|"
                        r"^\s*(NİTELİK|Nitelik|KODU|Kodu)\b|Alan Kodu")
    kodlu: list[list] = []  # [satır no, kod, metin, alanlar, üst, alt]
    alan_sutunu = 10_000
    for no, s in enumerate(satirlar):
        m = re.match(r"^\s{0,3}(\d{4})\s{2,}", s)
        if not m or baslik.search(s):
            continue
        ps = [p for p in parcalar(s) if p[0] >= m.end() - 1]
        metin_ps, alanlar = [], []
        for p, t in ps:
            # Açıklama ile alan kodları arasında tek boşluk kalabilir: "… mezun olmak. 9253 5366"
            k = re.search(r"(?<=\S) ((?:\d{4} ?)+)$", t)
            if k and not alanlar and not re.fullmatch(r"[\d ]+", t):
                metin_ps.append(t[: k.start()])
                alanlar += k.group(1).split()
                alan_sutunu = min(alan_sutunu, p + k.start() + 1)
            elif re.fullmatch(r"\d{4}(?: \d{4})*", t):
                alanlar += t.split()
                alan_sutunu = min(alan_sutunu, p)
            elif not alanlar:
                metin_ps.append(t)
            # alan kodlarından sonraki dal no / alan adları yok sayılır
        kodlu.append([no, m.group(1), birlestir(*metin_ps), alanlar, [], []])

    def temiz(s: str) -> str:
        if baslik.search(s):
            return ""
        return birlestir(*[t for p, t in parcalar(s) if p < alan_sutunu - 2 and not re.fullmatch(r"[\d* ]+", t)])

    def tamam(b: list) -> bool:
        metin = birlestir(*b[4], b[2], *b[5])
        if metin.startswith("Bakınız") and b[2]:
            return True  # "Bakınız: Başvurma Özel Şartları - …" tek satırdır, nokta ile bitmez
        return bool(metin) and metin.rstrip().endswith((".", ".)", "olmak", "olmamak", "Olmak", "gerekmektedir",
                                                        "uygulanmaktadır"))

    for i, b in enumerate(kodlu):
        onceki_no = kodlu[i - 1][0] if i else -1
        arada = [t for j in range(onceki_no + 1, b[0]) if (t := temiz(satirlar[j]))]
        onceki = kodlu[i - 1] if i else None
        # Önceki açıklama bir cümle sonuna ("… mezun olmak.") ulaşana kadar satırlar ona aittir,
        # kalanlar bu kodun üstüne taşan kısmıdır.
        if onceki:
            yedek = list(arada)
            while arada and not tamam(onceki):
                onceki[5].append(arada.pop(0))
            if not tamam(onceki) and not b[2]:
                # Cümle sonu hiç gelmediyse (beklenmedik biçim) eski kurala dön: ortadan böl.
                onceki[5][len(onceki[5]) - (len(yedek) - len(arada)):] = []
                alt, arada = bosluk_bol(yedek, True)
                onceki[5].extend(alt)
        b[4].extend(arada)
    # Son kaydın altı
    if kodlu:
        son = kodlu[-1]
        for j in range(son[0] + 1, min(son[0] + 4, len(satirlar))):
            if tamam(son):
                break
            if t := temiz(satirlar[j]):
                son[5].append(t)

    sonuc: dict[str, dict] = {}
    for no, kod, metin, alanlar, ust, alt in kodlu:
        tam = birlestir(*ust, metin, *alt)
        if kod in sonuc:  # ortaöğretimde aynı kod her alan için ayrı satırda tekrarlanır
            sonuc[kod]["alanlar"] += [a for a in alanlar if a not in sonuc[kod]["alanlar"]]
            if not sonuc[kod]["metin"]:
                sonuc[kod]["metin"] = tam
        else:
            sonuc[kod] = {"metin": tam, "alanlar": alanlar}
    return sonuc


def program_coz(yazi: str) -> dict[str, str]:
    sonuc: dict[str, str] = {}
    for s in yazi.splitlines():
        m = re.match(r"^\s*(\d{4})\s{2,}(\S.*?)\s*$", s)
        if m and m.group(1) not in sonuc:
            sonuc[m.group(1)] = birlestir(m.group(2))
    return sonuc


# ---------------------------------------------------------------- kılavuz sayfası

def tercih_tarihleri(yazi: str) -> tuple[str, str] | None:
    """"Adaylar tercihlerini 9-16 Temmuz 2026 tarihleri arasında" → (2026-07-09, 2026-07-16)."""
    tek = birlestir(yazi)
    m = re.search(r"tercihlerini\s+(\d{1,2})\s*(\w+)?\s*-\s*(\d{1,2})\s+(\w+)\s+(\d{4})", tek, re.I)
    if not m:
        return None
    g1, a1, g2, a2, yil = m.groups()
    ay2 = AYLAR.get(a2.lower().replace("I", "ı"))
    ay1 = AYLAR.get(a1.lower()) if a1 else ay2
    if not ay1 or not ay2:
        return None
    y1 = int(yil) - (1 if ay1 > ay2 else 0)
    return date(y1, ay1, int(g1)).isoformat(), date(int(yil), ay2, int(g2)).isoformat()


def donem_oku(donem: str) -> dict | None:
    """Bir dönemin (ör. kpss20261) bütün tablolarını okuyup tek bir rehber kaydı üretir."""
    sayfa_url = SAYFA.format(donem=donem)
    sayfa = getir(sayfa_url)
    pdfler = sorted(set(u.strip() for u in re.findall(
        r'href="(https://dokuman\.osym\.gov\.tr/pdfdokuman/\d{4}/KPSS/[^"]+?\.pdf)\s*"', sayfa)))
    tablolar = {DUZEYLER[m.group(1)]: u for u in pdfler if (m := re.search(r"/tablo(\d)_", u))}
    if not tablolar:
        return None
    # Aynı sayfada eski yıllara ait bağlantılar da olabiliyor; yalnızca tablolarla aynı klasöre bak.
    klasor = next(iter(tablolar.values())).rsplit("/", 1)[0]
    pdfler = [u for u in pdfler if u.rsplit("/", 1)[0] == klasor]
    kilavuz = next((u for u in pdfler if "kilavuz" in u.rsplit("/", 1)[1].lower()), None)
    tarihler = tercih_tarihleri(pdf_yazi(getir(kilavuz, True))) if kilavuz else None
    if not tarihler:
        print(f"{donem}: tercih tarihleri okunamadı", file=sys.stderr)
        return None

    kadrolar: list[dict] = []
    for duzey, url in tablolar.items():
        k = tablo_coz(pdf_yazi(getir(url, True)), duzey)
        print(f"{donem} {duzey}: {len(k)} kadro satırı", file=sys.stderr)
        kadrolar += k
    nitelikler: dict[str, dict] = {}
    programlar: dict[str, dict[str, str]] = {}

    def dosya_duzeyi(ad: str) -> str:
        if "onl" in ad:
            return "onlisans"
        if "ort" in ad or "alandal" in ad:
            return "lise"
        return "lisans"

    for u in pdfler:
        ad = u.rsplit("/", 1)[1].lower()
        if "tablo" in ad or "kilavuz" in ad or "yasakli" in ad:
            continue
        if "nitelik" in ad or "ozel" in ad:
            nitelikler.update(nitelik_coz(pdf_yazi(getir(u, True))))
        elif "mezun" in ad or "prg" in ad or "alandal" in ad:
            programlar[dosya_duzeyi(ad)] = program_coz(pdf_yazi(getir(u, True)))
    # Yalnızca tablolarda geçen nitelik kodlarını tut.
    kullanilan = {k for kd in kadrolar for k in kd["nitelikler"]}
    nitelikler = {k: v for k, v in nitelikler.items() if k in kullanilan}

    yil, no = donem[4:8], donem[8:]
    toplam = sum(k["adet"] for k in kadrolar)
    return {
        "id": "osym-" + donem,
        "baslik": f"KPSS-{yil}/{no} Merkezî Yerleştirme",
        "kurum": "ÖSYM",
        "tur": "memur",
        "altTur": "Merkezî Atama (KPSS Tercih)",
        "iller": [],
        "ogrenim": [],
        "puanTuru": None,
        "minPuan": None,
        "kadroSayisi": toplam,
        "duzeltme": False,
        "yayinTarihi": tarihler[0],
        "basvuruBaslangic": tarihler[0],
        "sonBasvuru": tarihler[1],
        "kaynakURL": sayfa_url,
        "sartlar": [],
        "minOgrenim": None,
        "sartNotu": (f"{len(kadrolar)} farklı kadroda toplam {toplam} kişi alınacak. Tercihler ÖSYM'nin "
                     "aday işlemleri sisteminden (ais.osym.gov.tr) yapılır. Puan türü öğrenim düzeyine "
                     "göredir: lise P94, ön lisans P93, lisans P3."),
        "siteSatiri": None,
        "rehber": {"donem": donem, "kadrolar": kadrolar, "nitelikler": nitelikler, "programlar": programlar},
    }


def donemler(bugun: date) -> list[str]:
    return [f"kpss{y}{n}" for y in (bugun.year - 1, bugun.year) for n in range(1, 6)]


def guncel_rehberler(bugun: date | None = None) -> list[dict]:
    """Tercih süresi bitmemiş rehberleri döner. Okunan dönemler önbelleğe alınır; tablolar
    yayımlandıktan sonra değişmediği için her dönem bir kez indirilir."""
    bugun = bugun or date.today()
    try:
        with open(ONBELLEK, encoding="utf-8") as f:
            onbellek = json.load(f)
    except (OSError, ValueError):
        onbellek = {}
    sonuc = []
    for donem in donemler(bugun):
        kayit = onbellek.get(donem)
        if kayit is None or (kayit == "yok" and onbellek.get(donem + "-denendi") != bugun.isoformat()):
            try:
                kayit = donem_oku(donem) or "yok"
            except Exception as e:  # tek dönemin hatası toplayıcıyı durdurmasın
                print(f"{donem}: {e}", file=sys.stderr)
                continue
            onbellek[donem] = kayit
            onbellek[donem + "-denendi"] = bugun.isoformat()
        # ALIMVAR_OSYM_TUMU=1: süresi geçmiş rehberleri de ver (uygulamayı denemek için).
        if isinstance(kayit, dict) and (kayit["sonBasvuru"] >= bugun.isoformat() or os.environ.get("ALIMVAR_OSYM_TUMU")):
            sonuc.append(kayit)
    try:
        with open(ONBELLEK, "w", encoding="utf-8") as f:
            json.dump(onbellek, f, ensure_ascii=False)
    except OSError:
        pass
    return sonuc


if __name__ == "__main__":
    if len(sys.argv) > 1:
        r = donem_oku(sys.argv[1])
        json.dump(r, sys.stdout, ensure_ascii=False, indent=1)
    else:
        json.dump(guncel_rehberler(), sys.stdout, ensure_ascii=False, indent=1)
