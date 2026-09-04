import os
import io
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

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# =====================================================
# ENVIRONMENT VARIABLES
# =====================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
BLYNK_AUTH_TOKEN = os.getenv("BLYNK_AUTH_TOKEN", "").strip()


# =====================================================
# GEMINI
# =====================================================

gemini_client = None

if GEMINI_API_KEY:

    try:
        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print("====================================")
        print("Gemini Client: HAZIR")
        print("====================================")

    except Exception as e:

        print("Gemini Client baslatilamadi:")
        print(repr(e))

else:

    print("UYARI: GEMINI_API_KEY bulunamadi!")


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

        print("BLYNK_AUTH_TOKEN bulunamadi.")
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

        print(
            f"Blynk HTTP: {response.status_code}"
        )

        if response.status_code == 200:

            print(
                f"Blynk guncellendi: "
                f"{pin} = {value}"
            )

            return True

        print(
            "Blynk cevabi:",
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "Blynk hatasi:",
            repr(e)
        )

        return False


# =====================================================
# HOME
# =====================================================

@app.route("/")
def home():

    return (
        "ESP32-CAM AI Su Saati Sunucusu "
        "Calisiyor!"
    )


# =====================================================
# HEALTH
# =====================================================

@app.route("/health")
def health():

    return jsonify({
        "status": "online",
        "gemini": gemini_client is not None,
        "blynk": bool(BLYNK_AUTH_TOKEN)
    }), 200


# =====================================================
# LOGS
# =====================================================

@app.route(
    "/logs",
    methods=["POST"]
)
def receive_logs():

    try:

        logs = request.data.decode(
            "utf-8",
            errors="replace"
        )

        print("")
        print("========== ESP32 LOG ==========")
        print(logs)
        print("================================")
        print("")

        return jsonify({
            "status": "success"
        }), 200

    except Exception as e:

        print(
            "Log hatasi:",
            repr(e)
        )

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400


# =====================================================
# GEMINI SAYAÇ OKUMA
# =====================================================

def read_meter_with_gemini(image_bytes):

    if gemini_client is None:

        raise RuntimeError(
            "Gemini Client hazir degil. "
            "GEMINI_API_KEY kontrol edilmeli."
        )


    # -------------------------------------------------
    # IMAGE KONTROL
    # -------------------------------------------------

    try:

        image = Image.open(
            io.BytesIO(image_bytes)
        )

        image.verify()

    except Exception as e:

        raise RuntimeError(
            "Gelen fotograf bozuk veya "
            f"gecersiz JPEG: {e}"
        )


    # -------------------------------------------------
    # GEMINI PROMPT
    # -------------------------------------------------

    prompt = """
Bu fotograf bir su sayacidir.

Sayacin mekanik rakamlarini dikkatlice oku.

Sadece sayaç üzerindeki gerçek rakamları soldan sağa yaz.

Kurallar:

- Siyah rakamları oku.
- Kırmızı rakamları oku.
- Görünen rakamları sırasıyla birleştir.
- Ondalık nokta açıkça görünüyorsa ekle.
- Rakamlar okunabiliyorsa yalnızca sayıyı döndür.
- Açıklama yazma.
- "m3" yazma.
- "Sonuç" yazma.
- Markdown kullanma.
- Kod bloğu kullanma.

Örnek cevap:
00123.45

Başka örnek:
1234

Eğer sayaç çok karanlık, bulanık veya rakamlar
okunamayacak durumdaysa yalnızca:

OKUNAMADI

yaz.

SADECE SAYI VEYA OKUNAMADI.
""".strip()


    # -------------------------------------------------
    # IMAGE PART
    # -------------------------------------------------

    image_part = types.Part.from_bytes(
        data=image_bytes,
        mime_type="image/jpeg"
    )


    # -------------------------------------------------
    # GEMINI REQUEST
    # -------------------------------------------------

    print(
        "Gemini API istegi baslatiliyor..."
    )

    response = gemini_client.models.generate_content(

        model="gemini-2.5-flash",

        contents=[
            image_part,
            prompt
        ],

        config=types.GenerateContentConfig(
            temperature=0,
            max_output_tokens=30
        )
    )


    # -------------------------------------------------
    # RESPONSE KONTROL
    # -------------------------------------------------

    if response is None:

        raise RuntimeError(
            "Gemini bos response dondurdu."
        )


    # response.text bazen hata verebilir
    try:

        text = response.text

    except Exception as e:

        raise RuntimeError(
            "Gemini response.text okunamadi: "
            f"{e}"
        )


    if not text:

        raise RuntimeError(
            "Gemini cevap verdi ancak metin "
            "dondurmedi."
        )


    print(
        "Gemini ham cevap:",
        repr(text)
    )

    return text.strip()


# =====================================================
# RESPONSE TEMIZLE
# =====================================================

def clean_meter_result(text):

    if not text:

        return None


    text = text.strip()

    text = text.replace(
        "```",
        ""
    )

    text = text.strip()


    if "OKUNAMADI" in text.upper():

        return "OKUNAMADI"


    result = ""

    for char in text:

        if char.isdigit():

            result += char

        elif char in ".,":

            result += "."


    # Birden fazla nokta varsa
    # ilk noktayı koru

    if result.count(".") > 1:

        first_dot = result.find(".")

        result = (
            result[:first_dot + 1]
            +
            result[first_dot + 1:].replace(
                ".",
                ""
            )
        )


    if not result:

        return None


    return result


# =====================================================
# UPLOAD METER
# =====================================================

@app.route(
    "/upload-meter",
    methods=["POST"]
)
def upload_meter():

    global LAST_IMAGE_HASH
    global LAST_READING_VALUE


    print("")
    print("====================================")
    print("ESP32'DEN FOTOGRAF GELDI")
    print("====================================")


    try:

        # =================================================
        # IMAGE
        # =================================================

        image_bytes = request.get_data(
            cache=False
        )


        if not image_bytes:

            print(
                "HATA: Fotograf verisi bos."
            )

            send_to_blynk(
                "v0",
                "HATA: Resim Yok"
            )

            return jsonify({
                "status": "error",
                "message": "Fotograf verisi bos."
            }), 400


        print(
            "Fotograf boyutu:",
            len(image_bytes),
            "byte"
        )


        # =================================================
        # IMAGE OPEN
        # =================================================

        try:

            image = Image.open(
                io.BytesIO(image_bytes)
            )

            print(
                "Format:",
                image.format
            )

            print(
                "Boyut:",
                image.size
            )

            print(
                "Mod:",
                image.mode
            )

            image.verify()

        except Exception as e:

            print(
                "JPEG KONTROL HATASI:",
                repr(e)
            )

            return jsonify({

                "status": "error",

                "error_type":
                    "invalid_image",

                "message":
                    "Gecerli bir JPEG degil.",

                "detail":
                    str(e)

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
        # AYNI RESİM
        # =================================================

        if (
            current_hash == LAST_IMAGE_HASH
            and
            LAST_READING_VALUE !=
            "Henüz Okunamadı"
        ):

            print(
                "AYNI FOTOGRAF."
            )

            print(
                "Gemini cagrisi yapilmiyor."
            )

            send_to_blynk(
                "v0",
                LAST_READING_VALUE
            )

            return jsonify({

                "status":
                    "cached_success",

                "reading":
                    LAST_READING_VALUE

            }), 200


        # =================================================
        # SAVE IMAGE
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
                "Fotograf kaydedildi."
            )

        except Exception as e:

            print(
                "Fotograf kaydetme uyarisi:",
                repr(e)
            )


        # =================================================
        # API KEY
        # =================================================

        if not GEMINI_API_KEY:

            print(
                "HATA: GEMINI_API_KEY yok!"
            )

            send_to_blynk(
                "v0",
                "HATA: API Key"
            )

            return jsonify({

                "status":
                    "error",

                "error_type":
                    "configuration",

                "message":
                    "GEMINI_API_KEY Render "
                    "Environment Variables icinde yok."

            }), 500


        # =================================================
        # GEMINI
        # =================================================

        try:

            raw_result = (
                read_meter_with_gemini(
                    image_bytes
                )
            )

        except Exception as e:

            error_text = repr(e)

            print("")
            print(
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
            )

            print(
                "GEMINI API HATASI"
            )

            print(
                error_text
            )

            print(
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
            )
            print("")


            send_to_blynk(
                "v0",
                "HATA: Gemini"
            )


            # Gemini hatasında 502
            # ve gerçek hata detayını döndür.

            return jsonify({

                "status":
                    "error",

                "error_type":
                    "gemini_api",

                "message":
                    "Gemini API istegi basarisiz.",

                "detail":
                    error_text

            }), 502


        # =================================================
        # TEMIZLE
        # =================================================

        meter_reading = clean_meter_result(
            raw_result
        )


        print(
            "Temizlenmis sonuc:",
            meter_reading
        )


        # =================================================
        # OKUNAMADI
        # =================================================

        if meter_reading == "OKUNAMADI":

            send_to_blynk(
                "v0",
                "OKUNAMADI"
            )

            return jsonify({

                "status":
                    "unreadable",

                "reading":
                    "OKUNAMADI"

            }), 200


        # =================================================
        # GEÇERSİZ SONUÇ
        # =================================================

        if not meter_reading:

            print(
                "Gemini anlamsiz cevap verdi."
            )

            send_to_blynk(
                "v0",
                "HATA: AI Sonucu"
            )

            return jsonify({

                "status":
                    "error",

                "error_type":
                    "invalid_ai_result",

                "message":
                    "Gemini okunabilir bir "
                    "sayaç degeri dondurmedi.",

                "raw":
                    raw_result

            }), 422


        # =================================================
        # CACHE
        # =================================================

        LAST_IMAGE_HASH = current_hash

        LAST_READING_VALUE = meter_reading


        # =================================================
        # BLYNK
        # =================================================

        blynk_ok = send_to_blynk(
            "v0",
            meter_reading
        )


        # =================================================
        # SUCCESS
        # =================================================

        print("")
        print(
            "===================================="
        )

        print(
            "SAYAÇ OKUMA BASARILI"
        )

        print(
            "Deger:",
            meter_reading
        )

        print(
            "Blynk:",
            blynk_ok
        )

        print(
            "===================================="
        )
        print("")


        return jsonify({

            "status":
                "success",

            "reading":
                meter_reading,

            "model":
                "gemini-2.5-flash",

            "blynk":
                blynk_ok

        }), 200


    # =================================================
    # GENEL HATA
    # =================================================

    except Exception as e:

        error_text = repr(e)

        print("")
        print(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
        )

        print(
            "GENEL SUNUCU HATASI"
        )

        print(
            error_text
        )

        print(
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
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

            "status":
                "error",

            "error_type":
                "server_error",

            "message":
                "Sunucuda beklenmeyen hata.",

            "detail":
                error_text

        }), 500


# =====================================================
# LATEST IMAGE
# =====================================================

@app.route(
    "/latest-image",
    methods=["GET"]
)
def latest_image():

    if os.path.exists(
        LAST_IMAGE_PATH
    ):

        return send_file(
            LAST_IMAGE_PATH,
            mimetype="image/jpeg"
        )


    return jsonify({

        "status":
            "error",

        "message":
            "Henuz fotograf yuklenmedi."

    }), 404


# =====================================================
# FILE TOO LARGE
# =====================================================

@app.errorhandler(413)
def file_too_large(error):

    return jsonify({

        "status":
            "error",

        "error_type":
            "file_too_large",

        "message":
            "Fotograf 10 MB'dan buyuk."

    }), 413


# =====================================================
# START
# =====================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    print("")
    print("====================================")
    print("ESP32 SU SAATI SERVER")
    print("Port:", port)
    print(
        "Gemini:",
        "HAZIR"
        if gemini_client
        else "YOK"
    )
    print(
        "Blynk:",
        "HAZIR"
        if BLYNK_AUTH_TOKEN
        else "YOK"
    )
    print("====================================")
    print("")

    app.run(
        host="0.0.0.0",
        port=port
    )
