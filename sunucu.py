import os
import hashlib
import requests
import urllib.parse

from flask import Flask, request, jsonify, send_file
from google import genai
from google.genai import types


# =====================================================
# FLASK
# =====================================================

app = Flask(__name__)


# =====================================================
# API ANAHTARLARI
# =====================================================

GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY", ""
).strip().strip('"').strip("'")

BLYNK_AUTH_TOKEN = os.environ.get(
    "BLYNK_AUTH_TOKEN", ""
).strip().strip('"').strip("'")


# =====================================================
# GEMINI CLIENT
# =====================================================

gemini_client = None

if GEMINI_API_KEY:
    try:
        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print("======================================")
        print("GEMINI CLIENT BASARIYLA OLUSTURULDU")
        print("======================================")

    except Exception as e:
        print("GEMINI CLIENT OLUSTURMA HATASI:")
        print(str(e))
        gemini_client = None
else:
    print("UYARI: GEMINI_API_KEY bulunamadi.")


# =====================================================
# DOSYA / CACHE
# =====================================================

LAST_IMAGE_PATH = "latest_meter.jpg"

LAST_IMAGE_HASH = None

LAST_READING_VALUE = "Henüz Okunamadı"


# =====================================================
# BLYNK
# =====================================================

def send_to_blynk(pin, value):
    """
    Blynk sanal pinine veri gönderir.
    Örnek:
        send_to_blynk("v0", "1234.56")
    """

    if not BLYNK_AUTH_TOKEN:
        print("UYARI: BLYNK_AUTH_TOKEN bulunamadi.")
        return False

    try:
        encoded_value = urllib.parse.quote(str(value))

        url = (
            "https://blynk.cloud/external/api/update"
            f"?token={BLYNK_AUTH_TOKEN}"
            f"&{pin}={encoded_value}"
        )

        response = requests.get(
            url,
            timeout=5
        )

        if response.status_code == 200:

            print(
                f"--- BLYNK GUNCELLENDI "
                f"({pin}: {value}) ---"
            )

            return True

        print(
            f"Blynk guncelleme hatasi: "
            f"HTTP {response.status_code}"
        )

        return False

    except Exception as error:

        print(
            "Blynk baglanti hatasi: "
            f"{str(error)}"
        )

        return False


# =====================================================
# ANA SAYFA
# =====================================================

@app.route("/", methods=["GET"])
def home():

    return (
        "ESP32-CAM AI Su Saati Sunucusu "
        "Bulutta Calisiyor!"
    )


# =====================================================
# SAGLIK KONTROLU
# =====================================================

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "ok",
        "gemini": gemini_client is not None,
        "blynk": bool(BLYNK_AUTH_TOKEN)
    }), 200


# =====================================================
# ESP32 LOG
# =====================================================

@app.route("/logs", methods=["POST"])
def receive_logs():

    try:

        logs = request.data.decode(
            "utf-8",
            errors="replace"
        )

        print("")
        print("======================================")
        print("ESP32-CAM CANLI LOGLARI")
        print("======================================")

        print(logs)

        print("======================================")
        print("")

        return jsonify({
            "status": "success"
        }), 200

    except Exception as error:

        print(
            "Log alma hatasi:",
            str(error)
        )

        return jsonify({
            "error": str(error)
        }), 400


# =====================================================
# GEMINI SAYAÇ OKUMA
# =====================================================

def read_meter_with_gemini(image_bytes):

    if gemini_client is None:

        raise RuntimeError(
            "Gemini client hazir degil. "
            "GEMINI_API_KEY kontrol edilmeli."
        )


    # -------------------------------------------------
    # PROMPT
    # -------------------------------------------------

    prompt = """
Görseldeki su sayacının göstergesini dikkatlice incele.

Sayaç üzerindeki siyah ve kırmızı rakamları
soldan sağa doğru oku.

Çıktıda SADECE sayaç değerini ver.

Kurallar:

1. Sadece rakamları yaz.
2. Sayaçta ondalık nokta varsa noktayı koru.
3. "m3", "metreküp", "su sayacı" gibi açıklamalar yazma.
4. Cümle kurma.
5. Markdown kullanma.
6. Kod bloğu kullanma.
7. Rakamları tahmin etmeye çalışma.
8. Görsel okunamayacak kadar karanlık veya bozuksa sadece:
OKUNAMADI
yaz.

Örnek geçerli cevaplar:

1234
00123
1234.56
00123.45

Geçersiz cevap örnekleri:

Sayaç değeri 1234
1234 m3
Değer: 1234
```1234```
"""


    # -------------------------------------------------
    # IMAGE PART
    # -------------------------------------------------

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/jpeg"
    )


    # -------------------------------------------------
    # MODEL LİSTESİ
    # -------------------------------------------------

    candidate_models = [
        "gemini-3.7-flash",
        "gemini-3.6-flash",
        "gemini-3.5-flash",
    ]


    last_error = None


    # -------------------------------------------------
    # MODELLERİ DENE
    # -------------------------------------------------

    for model_name in candidate_models:

        try:

            print(
                f"Gemini modeli deneniyor: "
                f"{model_name}"
            )

            response = gemini_client.models.generate_content(

                model=model_name,

                contents=[
                    image_part,
                    prompt
                ]
            )


            if response is None:

                print(
                    f"{model_name}: "
                    "Bos response."
                )

                continue


            text = response.text


            if text:

                text = text.strip()

                print(
                    f"Gemini cevabi "
                    f"({model_name}): "
                    f"{text}"
                )

                return text, model_name


            print(
                f"{model_name}: "
                "Metin cevabi yok."
            )


        except Exception as error:

            last_error = error

            print(
                f"{model_name} hata verdi:"
            )

            print(str(error))

            continue


    # Hiçbir model çalışmadı
    if last_error:

        raise RuntimeError(
            "Gemini modellerinin hicbiri "
            f"calismadi: {str(last_error)}"
        )


    raise RuntimeError(
        "Gemini herhangi bir cevap vermedi."
    )


# =====================================================
# SAYAÇ FOTOĞRAFI
# =====================================================

@app.route("/upload-meter", methods=["POST"])
def upload_meter():

    global LAST_IMAGE_HASH
    global LAST_READING_VALUE


    try:

        print("")
        print("======================================")
        print("YENI SAYAÇ FOTOGRAFI ALINDI")
        print("======================================")


        # -------------------------------------------------
        # FOTOĞRAF
        # -------------------------------------------------

        image_bytes = request.data


        if not image_bytes:

            print(
                "HATA: Resim verisi bos."
            )

            send_to_blynk(
                "v0",
                "HATA: Resim Yok"
            )

            return jsonify({
                "status": "error",
                "message": "Resim verisi alinamadi."
            }), 400


        print(
            f"Alinan fotograf boyutu: "
            f"{len(image_bytes)} byte"
        )


        # -------------------------------------------------
        # HASH
        # -------------------------------------------------

        current_hash = hashlib.md5(
            image_bytes
        ).hexdigest()


        print(
            f"Fotograf hash: "
            f"{current_hash}"
        )


        # -------------------------------------------------
        # CACHE KONTROLÜ
        # -------------------------------------------------

        if (
            current_hash == LAST_IMAGE_HASH
            and
            LAST_READING_VALUE != "Henüz Okunamadı"
        ):

            print(
                "AYNI RESIM ALGILANDI."
            )

            print(
                "Gemini API cagrisi yapilmayacak."
            )

            print(
                f"Onceki deger: "
                f"{LAST_READING_VALUE}"
            )


            send_to_blynk(
                "v0",
                LAST_READING_VALUE
            )


            return jsonify({

                "status": "cached_success",

                "reading": LAST_READING_VALUE,

                "message":
                    "Gorsel degismedigi icin "
                    "Gemini API cagrisi yapilmadi."

            }), 200


        # -------------------------------------------------
        # FOTOĞRAFI KAYDET
        # -------------------------------------------------

        try:

            with open(
                LAST_IMAGE_PATH,
                "wb"
            ) as image_file:

                image_file.write(
                    image_bytes
                )

            print(
                "Fotograf diske kaydedildi."
            )

        except Exception as error:

            print(
                "Fotograf kaydetme hatasi:",
                str(error)
            )


        # -------------------------------------------------
        # GEMINI KONTROL
        # -------------------------------------------------

        if gemini_client is None:

            print(
                "HATA: Gemini client hazir degil."
            )

            send_to_blynk(
                "v0",
                "HATA: Gemini"
            )

            return jsonify({

                "status": "error",

                "message":
                    "Gemini client hazir degil. "
                    "GEMINI_API_KEY kontrol edin."

            }), 500


        # -------------------------------------------------
        # GEMINI
        # -------------------------------------------------

        try:

            meter_reading, used_model = (
                read_meter_with_gemini(
                    image_bytes
                )
            )


        except Exception as error:

            print("")
            print(
                "======================================"
            )
            print(
                "GEMINI API HATASI"
            )
            print(
                "======================================"
            )

            print(str(error))

            print(
                "======================================"
            )
            print("")


            send_to_blynk(
                "v0",
                "HATA: AI"
            )


            return jsonify({

                "status": "error",

                "message":
                    "Gemini API hata verdi.",

                "error":
                    str(error)

            }), 502


        # -------------------------------------------------
        # CEVABI TEMİZLE
        # -------------------------------------------------

        meter_reading = meter_reading.strip()


        # Gemini bazen ``` kullanabilir.
        # Güvenlik amaçlı temizliyoruz.

        meter_reading = (
            meter_reading
            .replace("```", "")
            .strip()
        )


        # -------------------------------------------------
        # OKUNAMADI
        # -------------------------------------------------

        if meter_reading.upper() == "OKUNAMADI":

            print(
                "Sayaç okunamadi."
            )

            send_to_blynk(
                "v0",
                "OKUNAMADI"
            )


            return jsonify({

                "status": "unreadable",

                "reading":
                    "OKUNAMADI",

                "model":
                    used_model

            }), 200


        # -------------------------------------------------
        # SADECE RAKAM / NOKTA KONTROLÜ
        # -------------------------------------------------

        cleaned_reading = ""

        for character in meter_reading:

            if (
                character.isdigit()
                or character == "."
                or character == ","
            ):

                cleaned_reading += character


        cleaned_reading = (
            cleaned_reading
            .replace(",", ".")
            .strip()
        )


        # -------------------------------------------------
        # GEÇERSİZ CEVAP
        # -------------------------------------------------

        if not cleaned_reading:

            print(
                "Gemini geçerli sayaç "
                "değeri döndürmedi."
            )

            print(
                f"Ham cevap: "
                f"{meter_reading}"
            )


            send_to_blynk(
                "v0",
                "HATA: AI"
            )


            return jsonify({

                "status": "error",

                "message":
                    "Gemini geçerli bir "
                    "sayaç değeri döndürmedi.",

                "raw_response":
                    meter_reading

            }), 502


        # -------------------------------------------------
        # CACHE GÜNCELLE
        # -------------------------------------------------

        LAST_IMAGE_HASH = current_hash

        LAST_READING_VALUE = cleaned_reading


        # -------------------------------------------------
        # BLYNK
        # -------------------------------------------------

        blynk_ok = send_to_blynk(
            "v0",
            cleaned_reading
        )


        # -------------------------------------------------
        # BAŞARILI
        # -------------------------------------------------

        print("")
        print("======================================")
        print("SAYAÇ OKUMA BAŞARILI")
        print("======================================")

        print(
            f"Model: {used_model}"
        )

        print(
            f"Okunan değer: "
            f"{cleaned_reading}"
        )

        print(
            f"Blynk: "
            f"{'OK' if blynk_ok else 'HATA'}"
        )

        print("======================================")
        print("")


        return jsonify({

            "status": "success",

            "reading":
                cleaned_reading,

            "model":
                used_model,

            "blynk":
                blynk_ok

        }), 200


    # =================================================
    # GENEL HATA
    # =================================================

    except Exception as error:

        print("")
        print(
            "======================================"
        )
        print(
            "GENEL SUNUCU HATASI"
        )
        print(
            "======================================"
        )

        print(str(error))

        print(
            "======================================"
        )
        print("")


        try:

            send_to_blynk(
                "v0",
                "HATA: Sunucu"
            )

        except Exception:
            pass


        return jsonify({

            "status": "error",

            "message":
                "Sunucu tarafinda hata olustu.",

            "error":
                str(error)

        }), 500


# =====================================================
# SON FOTOĞRAF
# =====================================================

@app.route(
    "/latest-image",
    methods=["GET"]
)
def get_latest_image():

    try:

        if os.path.exists(
            LAST_IMAGE_PATH
        ):

            return send_file(
                LAST_IMAGE_PATH,
                mimetype="image/jpeg"
            )


        return jsonify({

            "message":
                "Henuz yuklenmis "
                "bir fotograf yok."

        }), 404


    except Exception as error:

        return jsonify({

            "error":
                str(error)

        }), 500


# =====================================================
# SERVER
# =====================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )


    print("")
    print(
        "======================================"
    )

    print(
        "ESP32-CAM AI SU SAYACI SUNUCUSU"
    )

    print(
        f"PORT: {port}"
    )

    print(
        f"GEMINI: "
        f"{'HAZIR' if gemini_client else 'YOK'}"
    )

    print(
        f"BLYNK: "
        f"{'HAZIR' if BLYNK_AUTH_TOKEN else 'YOK'}"
    )

    print(
        "======================================"
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
