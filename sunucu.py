import os
import hashlib
import urllib.parse

import requests

from flask import Flask, request, jsonify, send_file

from PIL import Image

from google import genai
from google.genai import types


# =====================================================
# FLASK
# =====================================================

app = Flask(__name__)

# Maksimum gelen fotoğraf boyutu
# 10 MB
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# =====================================================
# API KEYLER
# =====================================================

GEMINI_API_KEY = (
    os.environ.get("GEMINI_API_KEY", "")
    .strip()
    .strip('"')
    .strip("'")
)

BLYNK_AUTH_TOKEN = (
    os.environ.get("BLYNK_AUTH_TOKEN", "")
    .strip()
    .strip('"')
    .strip("'")
)


# =====================================================
# GEMINI CLIENT
# =====================================================

gemini_client = None

if GEMINI_API_KEY:

    try:

        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print("Gemini Client basariyla baslatildi.")

    except Exception as e:

        print(
            "Gemini Client baslatma hatasi:",
            str(e)
        )

else:

    print(
        "UYARI: GEMINI_API_KEY bulunamadi!"
    )


# =====================================================
# DOSYA
# =====================================================

LAST_IMAGE_PATH = "latest_meter.jpg"

LAST_IMAGE_HASH = None

LAST_READING_VALUE = "Henüz Okunamadı"


# =====================================================
# BLYNK
# =====================================================

def send_to_blynk(pin, value):

    if not BLYNK_AUTH_TOKEN:

        print(
            "UYARI: BLYNK_AUTH_TOKEN bulunamadi."
        )

        return False

    try:

        encoded_value = urllib.parse.quote(
            str(value)
        )

        url = (
            "https://blynk.cloud/external/api/update"
            f"?token={BLYNK_AUTH_TOKEN}"
            f"&{pin}={encoded_value}"
        )

        response = requests.get(
            url,
            timeout=10
        )

        if response.status_code == 200:

            print(
                f"--- BLYNK GUNCELLENDI "
                f"({pin}: {value}) ---"
            )

            return True

        print(
            "Blynk guncelleme hatasi: "
            f"HTTP {response.status_code}"
        )

        print(
            "Blynk cevabi:",
            response.text
        )

        return False

    except Exception as e:

        print(
            "Blynk baglanti hatasi:",
            str(e)
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
# HEALTH CHECK
# =====================================================

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "status": "online",
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
        print(
            "===== ESP32-CAM CANLI LOGLARI ====="
        )

        print(logs)

        print(
            "===================================="
        )

        return jsonify({
            "status": "success"
        }), 200

    except Exception as e:

        print(
            "Log alma hatasi:",
            str(e)
        )

        return jsonify({
            "status": "error",
            "error": str(e)
        }), 400


# =====================================================
# GEMINI SAYAÇ OKUMA
# =====================================================

def read_meter_with_gemini(image_bytes):

    if gemini_client is None:

        raise RuntimeError(
            "Gemini Client hazir degil. "
            "GEMINI_API_KEY Render Environment "
            "Variables icinde tanimli mi?"
        )


    # =================================================
    # IMAGE VALIDATION
    # =================================================

    try:

        image = Image.open(
            __import__("io").BytesIO(
                image_bytes
            )
        )

        image.verify()

    except Exception as e:

        raise RuntimeError(
            "Gonderilen dosya gecerli bir JPEG "
            f"degil: {str(e)}"
        )


    # =================================================
    # PROMPT
    # =================================================

    prompt = """
Sen bir su sayaci okuma sistemisin.

Gonderilen fotografi dikkatlice incele.

Su sayacinin mekanik gosterge rakamlarini oku.

Kurallar:

1. Siyah rakamlari soldan saga oku.
2. Kirmizi rakamlari soldan saga oku.
3. Gorunebilen rakamlari sirasiyla birlestir.
4. Ondalik nokta gorunuyorsa ekle.
5. Sadece sayac degerini yaz.
6. Aciklama yazma.
7. "m3" yazma.
8. "Sonuc:" yazma.
9. Markdown kullanma.
10. Kod blogu kullanma.

Ornek:
00123.45

veya:

1234

Eger rakamlar okunamayacak kadar karanlik,
bulanık veya goruntu uygun degilse:

OKUNAMADI

cevabini ver.

SADECE SAYI veya OKUNAMADI CEVABI VER.
""".strip()


    # =================================================
    # IMAGE PART
    # =================================================

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/jpeg"
    )


    # =================================================
    # GEMINI
    # =================================================

    response = gemini_client.models.generate_content(

        model="gemini-2.5-flash",

        contents=[
            prompt,
            image_part
        ],

        config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=30
        )
    )


    # =================================================
    # RESPONSE
    # =================================================

    if response is None:

        raise RuntimeError(
            "Gemini bos response dondurdu."
        )


    try:

        text = response.text

    except Exception:

        text = None


    if not text:

        raise RuntimeError(
            "Gemini cevap verdi fakat text "
            "alaninda sonuc bulunamadi."
        )


    return text.strip()


# =====================================================
# SAAT SAYACI UPLOAD
# =====================================================

@app.route(
    "/upload-meter",
    methods=["POST"]
)
def upload_meter():

    global LAST_IMAGE_HASH
    global LAST_READING_VALUE


    print("")
    print(
        "===================================="
    )

    print(
        "YENI SAYAÇ FOTOĞRAFI ALINDI"
    )

    print(
        "===================================="
    )


    try:

        # =================================================
        # IMAGE BYTES
        # =================================================

        image_bytes = request.get_data(
            cache=False
        )


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
            "Alinan fotograf:",
            len(image_bytes),
            "byte"
        )


        # =================================================
        # JPEG KONTROL
        # =================================================

        try:

            image = Image.open(
                __import__("io").BytesIO(
                    image_bytes
                )
            )

            print(
                "Gorsel:",
                image.format,
                image.size,
                image.mode
            )

            if image.format != "JPEG":

                print(
                    "UYARI: Gelen dosya JPEG degil."
                )

        except Exception as e:

            print(
                "Gorsel acilamadi:",
                str(e)
            )

            return jsonify({
                "status": "error",
                "message": "Gecersiz JPEG.",
                "detail": str(e)
            }), 400


        # =================================================
        # HASH
        # =================================================

        current_hash = hashlib.md5(
            image_bytes
        ).hexdigest()


        print(
            "Image hash:",
            current_hash
        )


        # =================================================
        # AYNI FOTOĞRAF KONTROLÜ
        # =================================================

        if (
            current_hash == LAST_IMAGE_HASH
            and
            LAST_READING_VALUE != "Henüz Okunamadı"
        ):

            print(
                "AYNI FOTOĞRAF ALGILANDI."
            )

            print(
                "Gemini cagrisi yapilmayacak."
            )

            send_to_blynk(
                "v0",
                LAST_READING_VALUE
            )

            return jsonify({

                "status": "cached_success",

                "reading":
                    LAST_READING_VALUE,

                "message":
                    "Ayni fotograf oldugu icin "
                    "Gemini cagrisi yapilmadi."

            }), 200


        # =================================================
        # FOTOĞRAFI KAYDET
        # =================================================

        try:

            with open(
                LAST_IMAGE_PATH,
                "wb"
            ) as file:

                file.write(
                    image_bytes
                )

            print(
                "Fotograf kaydedildi:",
                LAST_IMAGE_PATH
            )

        except Exception as e:

            print(
                "Fotograf kaydetme hatasi:",
                str(e)
            )


        # =================================================
        # GEMINI KEY
        # =================================================

        if not GEMINI_API_KEY:

            print(
                "HATA: GEMINI_API_KEY eksik."
            )

            send_to_blynk(
                "v0",
                "HATA: Gemini API Key"
            )

            return jsonify({

                "status": "error",

                "message":
                    "GEMINI_API_KEY Render "
                    "Environment Variables icinde yok."

            }), 500


        # =================================================
        # GEMINI OKUMA
        # =================================================

        print(
            "Gemini 2.5 Flash cagriliyor..."
        )


        try:

            meter_reading = (
                read_meter_with_gemini(
                    image_bytes
                )
            )

        except Exception as e:

            error_message = str(e)

            print("")
            print(
                "===================================="
            )

            print(
                "GEMINI HATASI:"
            )

            print(
                error_message
            )

            print(
                "===================================="
            )

            print("")

            send_to_blynk(
                "v0",
                "HATA: Gemini"
            )

            # Artık ESP32 500 aldığında
            # gerçek hatayı görebilecek.

            return jsonify({

                "status": "error",

                "error_type":
                    "gemini_error",

                "message":
                    "Gemini API istegi basarisiz.",

                "detail":
                    error_message

            }), 502


        # =================================================
        # GEMINI SONUCU
        # =================================================

        meter_reading = (
            meter_reading
            .replace("```", "")
            .strip()
        )


        print(
            "------------------------------------"
        )

        print(
            "OKUNAN SAYAÇ DEGERİ:"
        )

        print(
            meter_reading
        )

        print(
            "------------------------------------"
        )


        # =================================================
        # BASIT TEMIZLEME
        # =================================================

        if meter_reading != "OKUNAMADI":

            cleaned = ""

            for char in meter_reading:

                if (
                    char.isdigit()
                    or char == "."
                    or char == ","
                ):

                    cleaned += char


            cleaned = cleaned.replace(
                ",",
                "."
            )


            if cleaned:

                meter_reading = cleaned


        # =================================================
        # OKUNAMADI
        # =================================================

        if meter_reading == "OKUNAMADI":

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
                    "OKUNAMADI"

            }), 200


        # =================================================
        # CACHE
        # =================================================

        LAST_IMAGE_HASH = current_hash

        LAST_READING_VALUE = meter_reading


        # =================================================
        # BLYNK
        # =================================================

        blynk_result = send_to_blynk(
            "v0",
            meter_reading
        )


        # =================================================
        # BAŞARILI
        # =================================================

        print(
            "Sayaç islemi basariyla tamamlandi."
        )


        return jsonify({

            "status": "success",

            "reading":
                meter_reading,

            "model":
                "gemini-2.5-flash",

            "blynk":
                blynk_result

        }), 200


    # =====================================================
    # GENEL SUNUCU HATASI
    # =====================================================

    except Exception as e:

        error_message = str(e)

        print("")
        print(
            "===================================="
        )

        print(
            "GENEL SUNUCU HATASI:"
        )

        print(
            error_message
        )

        print(
            "===================================="
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

            "error_type":
                "server_error",

            "message":
                "Sunucuda beklenmeyen hata.",

            "detail":
                error_message

        }), 500


# =====================================================
# SON FOTOĞRAF
# =====================================================

@app.route(
    "/latest-image",
    methods=["GET"]
)
def get_latest_image():

    if os.path.exists(
        LAST_IMAGE_PATH
    ):

        return send_file(
            LAST_IMAGE_PATH,
            mimetype="image/jpeg"
        )


    return jsonify({

        "status": "error",

        "message":
            "Henuz yuklenmis bir fotograf yok."

    }), 404


# =====================================================
# MAX SIZE HATASI
# =====================================================

@app.errorhandler(413)
def request_too_large(error):

    return jsonify({

        "status": "error",

        "message":
            "Fotograf 10 MB limitini asiyor."

    }), 413


# =====================================================
# START
# =====================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    print(
        "===================================="
    )

    print(
        "ESP32 SU SAATI SUNUCUSU"
    )

    print(
        "Port:",
        port
    )

    print(
        "Gemini:",
        "HAZIR"
        if gemini_client
        else "HAZIR DEGIL"
    )

    print(
        "Blynk:",
        "HAZIR"
        if BLYNK_AUTH_TOKEN
        else "HAZIR DEGIL"
    )

    print(
        "===================================="
    )


    app.run(
        host="0.0.0.0",
        port=port
    )
