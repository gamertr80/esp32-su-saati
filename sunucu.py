import os
import io
import base64
import hashlib
import urllib.parse

import requests

from flask import Flask, request, jsonify, send_file
from PIL import Image


# =====================================================
# FLASK
# =====================================================

app = Flask(__name__)

app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024


# =====================================================
# ENVIRONMENT VARIABLES
# =====================================================

GEMINI_API_KEY = os.getenv(
    "GEMINI_API_KEY",
    ""
).strip().strip('"').strip("'")

BLYNK_AUTH_TOKEN = os.getenv(
    "BLYNK_AUTH_TOKEN",
    ""
).strip().strip('"').strip("'")


# =====================================================
# GEMINI MODEL (En güncel hızlı model)
# =====================================================

GEMINI_MODEL = "gemini-3.6-flash"

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/"
    "v1beta/models/"
    + GEMINI_MODEL
    + ":generateContent"
)

# =====================================================
# DOSYA & DEĞİŞKENLER
# =====================================================

LAST_IMAGE_PATH = "latest_meter.jpg"

LAST_IMAGE_HASH = None

LAST_READING_VALUE = "Henüz Okunamadı"


# =====================================================
# BAŞLANGIÇ LOG
# =====================================================

print("")
print("====================================")
print("ESP32 SU SAATI SERVER")
print("====================================")

print(
    "Gemini API Key:",
    "VAR" if GEMINI_API_KEY else "YOK"
)

print(
    "Blynk Token:",
    "VAR" if BLYNK_AUTH_TOKEN else "YOK"
)

print(
    "Gemini Model:",
    GEMINI_MODEL
)

print(
    "===================================="
)

print("")


# =====================================================
# BLYNK INTEGRATION
# =====================================================

def send_to_blynk(pin, value):

    if not BLYNK_AUTH_TOKEN:

        print(
            "Blynk token bulunamadi."
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

        print(
            "Blynk HTTP:",
            response.status_code
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
# ANA SAYFA
# =====================================================

@app.route("/")
def home():

    return (
        "ESP32-CAM AI Su Saati Sunucusu "
        "Calisiyor!"
    )


# =====================================================
# HEALTH CHECK
# =====================================================

@app.route("/health")
def health():

    return jsonify({

        "status": "online",

        "gemini_key":
            bool(GEMINI_API_KEY),

        "blynk":
            bool(BLYNK_AUTH_TOKEN),

        "model":
            GEMINI_MODEL

    }), 200


# =====================================================
# ESP32 LOG
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
        print(
            "========== ESP32 LOG =========="
        )

        print(logs)

        print(
            "================================"
        )

        print("")

        return jsonify({
            "status": "success"
        }), 200

    except Exception as e:

        print(
            "Log alma hatasi:",
            repr(e)
        )

        return jsonify({

            "status":
                "error",

            "detail":
                repr(e)

        }), 400


# =====================================================
# GEMINI API CALL
# =====================================================

def ask_gemini(image_bytes):

    if not GEMINI_API_KEY:

        raise RuntimeError(
            "GEMINI_API_KEY Render "
            "Environment Variables icinde yok."
        )

    # Base64 dönüşümü
    image_base64 = base64.b64encode(
        image_bytes
    ).decode("utf-8")

    # Prompt
    prompt = """
Bu fotograf bir su sayacinin fotografidir.

Sayacin mekanik gosterge rakamlarini dikkatlice oku.

Sadece sayaç üzerinde görünen rakamları soldan sağa oku.

Kurallar:

1. Siyah rakamları oku.
2. Kırmızı rakamları oku.
3. Görünen bütün rakamları sırayla birleştir.
4. Ondalık nokta açıkça görünüyorsa ekle.
5. Sadece sayı döndür.
6. Açıklama yazma.
7. "m3" yazma.
8. "Sonuç" yazma.
9. Markdown kullanma.
10. Kod bloğu kullanma.

Örnek:
00123.45

Başka örnek:
1234

Eğer rakamlar karanlık, bulanık veya okunamayacak
durumdaysa sadece:

OKUNAMADI

yaz.

SADECE SAYI VEYA OKUNAMADI.
""".strip()

    payload = {

        "contents": [

            {

                "parts": [

                    {
                        "text": prompt
                    },

                    {

                        "inline_data": {

                            "mime_type":
                                "image/jpeg",

                            "data":
                                image_base64
                        }
                    }

                ]

            }

        ],

        "generationConfig": {

            "temperature": 0,

            "maxOutputTokens": 30

        }

    }

    headers = {

        "Content-Type":
            "application/json",

        "x-goog-api-key":
            GEMINI_API_KEY

    }

    print("")
    print(
        "Gemini API istegi gonderiliyor..."
    )

    print(
        "Model:",
        GEMINI_MODEL
    )

    print(
        "Fotograf:",
        len(image_bytes),
        "byte"
    )

    try:

        response = requests.post(

            GEMINI_URL,

            headers=headers,

            json=payload,

            timeout=60

        )

    except requests.exceptions.Timeout:

        raise RuntimeError(
            "Gemini API 60 saniye icinde "
            "cevap vermedi."
        )

    except requests.exceptions.RequestException as e:

        raise RuntimeError(
            "Gemini API baglanti hatasi: "
            + repr(e)
        )

    print(
        "Gemini HTTP:",
        response.status_code
    )

    response_text = response.text

    print(
        "Gemini cevabi:",
        response_text[:2000]
    )

    if response.status_code != 200:

        raise RuntimeError(

            "Gemini HTTP "
            + str(response.status_code)
            + ": "
            + response_text[:1500]

        )

    try:

        data = response.json()

    except Exception as e:

        raise RuntimeError(
            "Gemini JSON cevabi okunamadi: "
            + repr(e)
        )

    candidates = data.get(
        "candidates"
    )

    if not candidates:

        raise RuntimeError(
            "Gemini candidates dondurmedi: "
            + str(data)[:1500]
        )

    content = candidates[0].get(
        "content"
    )

    if not content:

        raise RuntimeError(
            "Gemini content dondurmedi: "
            + str(data)[:1500]
        )

    parts = content.get(
        "parts",
        []
    )

    result_text = ""

    for part in parts:

        if "text" in part:

            result_text += part["text"]

    result_text = result_text.strip()

    if not result_text:

        raise RuntimeError(
            "Gemini cevap verdi fakat "
            "text bulunamadi."
        )

    print(
        "Gemini ham sonuc:",
        repr(result_text)
    )

    return result_text


# =====================================================
# SAYAÇ SONUCUNU TEMİZLE
# =====================================================

def clean_meter_result(text):

    if not text:

        return None

    text = text.strip()

    if "OKUNAMADI" in text.upper():

        return "OKUNAMADI"

    text = text.replace(
        "```",
        ""
    )

    text = text.strip()

    result = ""

    decimal_found = False

    for char in text:

        if char.isdigit():

            result += char

        elif char in ".,":

            if not decimal_found:

                result += "."

                decimal_found = True

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
    print(
        "===================================="
    )

    print(
        "ESP32'DEN YENI FOTOGRAF"
    )

    print(
        "===================================="
    )

    try:

        image_bytes = request.get_data(
            cache=False
        )

        if not image_bytes:

            print(
                "HATA: Fotograf bos."
            )

            send_to_blynk(
                "v0",
                "HATA: Resim Yok"
            )

            return jsonify({

                "status":
                    "error",

                "error_type":
                    "empty_image",

                "message":
                    "Fotograf verisi bos."

            }), 400

        print(
            "Fotograf:",
            len(image_bytes),
            "byte"
        )

        # JPEG Doğrulama
        try:

            image = Image.open(
                io.BytesIO(
                    image_bytes
                )
            )

            image.verify()

            print(
                "JPEG OK."
            )

        except Exception as e:

            print(
                "JPEG HATASI:",
                repr(e)
            )

            return jsonify({

                "status":
                    "error",

                "error_type":
                    "invalid_image",

                "message":
                    "Gecerli JPEG degil.",

                "detail":
                    repr(e)

            }), 400

        # Hash kontrolü
        current_hash = hashlib.md5(
            image_bytes
        ).hexdigest()

        print(
            "Image hash:",
            current_hash
        )

        # Resmi kaydet
        try:

            with open(
                LAST_IMAGE_PATH,
                "wb"
            ) as f:

                f.write(
                    image_bytes
                )

            print(
                "Fotograf kaydedildi."
            )

        except Exception as e:

            print(
                "Fotograf kaydetme hatasi:",
                repr(e)
            )

        # Birebir aynı resim geldiyse Gemini çağrısı yapma
        if (

            current_hash ==
            LAST_IMAGE_HASH

            and

            LAST_READING_VALUE !=
            "Henüz Okunamadı"

        ):

            print(
                "Ayni fotograf algilandi."
            )

            print(
                "Gemini cagrisi atlanacak."
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

        # API Key kontrolü
        if not GEMINI_API_KEY:

            print(
                "HATA: GEMINI_API_KEY YOK!"
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
                    "GEMINI_API_KEY bulunamadi."

            }), 500

        # Gemini İsteği
        try:

            raw_result = ask_gemini(
                image_bytes
            )

        except Exception as e:

            error_text = repr(e)

            print("")
            print(
                "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
            )

            print(
                "GEMINI HATASI"
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

        # Sonuç Temizleme
        meter_reading = clean_meter_result(
            raw_result
        )

        print(
            "Temiz sonuc:",
            repr(meter_reading)
        )

        if meter_reading == "OKUNAMADI":

            LAST_IMAGE_HASH = current_hash

            LAST_READING_VALUE = "OKUNAMADI"

            send_to_blynk(
                "v0",
                "OKUNAMADI"
            )

            return jsonify({

                "status":
                    "unreadable",

                "reading":
                    "OKUNAMADI",

                "model":
                    GEMINI_MODEL

            }), 200

        if not meter_reading:

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
                    "Gemini sayaç degeri "
                    "uretemedi.",

                "raw":
                    raw_result

            }), 422

        # Başarılı Okuma Kaydı
        LAST_IMAGE_HASH = current_hash

        LAST_READING_VALUE = meter_reading

        blynk_ok = send_to_blynk(

            "v0",

            meter_reading

        )

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
                GEMINI_MODEL,

            "blynk":
                blynk_ok

        }), 200

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
# LATEST IMAGE ENDPOINT
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
            "Henuz fotograf yok."

    }), 404


# =====================================================
# 413 ERROR HANDLER
# =====================================================

@app.errorhandler(413)
def too_large(error):

    return jsonify({

        "status":
            "error",

        "error_type":
            "file_too_large",

        "message":
            "Fotograf 10 MB limitini asti."

    }), 413


# =====================================================
# APP START
# =====================================================

if __name__ == "__main__":

    port = int(
        os.getenv(
            "PORT",
            "5000"
        )
    )

    app.run(

        host="0.0.0.0",

        port=port

    )
