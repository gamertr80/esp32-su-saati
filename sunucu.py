import os
import requests
from flask import Flask, request, jsonify, send_file
import google.generativeai as genai
from PIL import Image
import io
import urllib.parse

app = Flask(__name__)

# API Anahtarları
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")
BLYNK_AUTH_TOKEN = os.environ.get("BLYNK_AUTH_TOKEN", "").strip().strip('"').strip("'")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

LAST_IMAGE_PATH = "latest_meter.jpg"

def send_to_blynk(pin, value):
    """Verilen Blynk sanal pinine (v0, v1 vb.) güvenli şekilde veri gönderir."""
    if not BLYNK_AUTH_TOKEN:
        print("UYARI: BLYNK_AUTH_TOKEN bulunamadi.")
        return False

    try:
        # URL'deki özel karakterlerin (boşluk, özel semboller) HTTP 400 vermesini önlemek için quote kullanıyoruz
        encoded_val = urllib.parse.quote(str(value))
        url = f"https://blynk.cloud/external/api/update?token={BLYNK_AUTH_TOKEN}&{pin}={encoded_val}"
        
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            print(f"--- BLYNK GÜNCELLENDİ ({pin}: {value}) ---")
            return True
        else:
            print(f"Blynk guncelleme hatasi: HTTP {res.status_code}")
            return False
    except Exception as err:
        print(f"Blynk baglanti hatasi: {str(err)}")
        return False

@app.route('/')
def home():
    return "ESP32-CAM AI Su Saati Sunucusu Bulutta Çalışıyor!"

@app.route('/upload-meter', methods=['POST'])
def upload_meter():
    try:
        # 1. ESP32'den gelen pil parametresini al (% sembolü olmadan ham sayı gönderiyoruz)
        battery_level = request.args.get('battery', 'N/A')
        if battery_level != 'N/A':
            print(f"--- GELEN PİL YÜZDESİ: %{battery_level} ---")
            # % işaretini kaldırıp sadece sayı değerini v1 pinine gönderiyoruz (HTTP 400'ü engeller)
            send_to_blynk("v1", battery_level)

        image_bytes = request.data
        if not image_bytes:
            send_to_blynk("v0", "HATA: Resim Yok")
            return jsonify({"error": "Resim verisi alinamadi"}), 400

        # 2. Fotoğrafı diske kaydet
        with open(LAST_IMAGE_PATH, "wb") as f:
            f.write(image_bytes)

        if not GEMINI_API_KEY:
            send_to_blynk("v0", "HATA: API Key Eksik")
            return jsonify({"status": "partial_success", "message": "Resim kaydedildi ancak API Key eksik!"}), 200

        # 3. Görseli Yükle ve Analiz Et
        image = Image.open(io.BytesIO(image_bytes))

        prompt = (
            "Görseldeki su sayacının göstergesini incele. "
            "Siyah ve kırmızı çarklardaki rakamları sırasıyla yan yana yaz (Örn: 00123.45 veya 1234). "
            "Sadece ve sadece rakamları (ve varsa noktayı) çıktı olarak ver. "
            "Hiçbir açıklama, kelime, harf veya 'm3' gibi bir birim ekleme. "
            "Eğer sayaç paneli tamamen karanlıksa veya hiçbir rakam seçilemeyecek kadar bozuksa sadece OKUNAMADI yaz."
        )

        candidate_models = [
            'gemini-3.6-flash'
        ]

        response = None
        used_model = None

        for m_name in candidate_models:
            try:
                model = genai.GenerativeModel(m_name)
                res = model.generate_content([prompt, image])
                if res and res.text:
                    response = res
                    used_model = m_name
                    break
            except Exception as e:
                print(f"{m_name} modeli denenirken hata: {str(e)}")
                continue

        if response and response.text:
            meter_reading = response.text.strip()
            print(f"--- OKUNAN SAYAÇ DEĞERİ ({used_model}): {meter_reading} ---")

            send_to_blynk("v0", meter_reading)  # Blynk V0 Pinine Sayaç Değerini Gönder

            return jsonify({
                "status": "success",
                "reading": meter_reading,
                "battery": battery_level,
                "model": used_model
            }), 200
        else:
            send_to_blynk("v0", "HATA: AI Yanit Vermedi")
            return jsonify({"status": "error", "message": "Hiçbir Gemini modeli yanıt üretmedi."}), 500

    except Exception as e:
        print(f"Hata olustu: {str(e)}")
        send_to_blynk("v0", "HATA: Sunucu Hatasi")
        return jsonify({"error": str(e)}), 500

@app.route('/latest-image', methods=['GET'])
def get_latest_image():
    if os.path.exists(LAST_IMAGE_PATH):
        return send_file(LAST_IMAGE_PATH, mimetype='image/jpeg')
    else:
        return jsonify({"message": "Henuz yuklenmis bir fotograf yok."}), 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
