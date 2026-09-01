import os
from flask import Flask, request, jsonify, send_file
import google.generativeai as genai
from PIL import Image
import io

app = Flask(__name__)

# API Anahtarı Ayarı
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip().strip('"').strip("'")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

LAST_IMAGE_PATH = "latest_meter.jpg"

@app.route('/')
def home():
    return "ESP32-CAM AI Su Saati Sunucusu Bulutta Çalışıyor!"

@app.route('/upload-meter', methods=['POST'])
def upload_meter():
    try:
        image_bytes = request.data
        if not image_bytes:
            return jsonify({"error": "Resim verisi alinamadi"}), 400

        # 1. Fotoğrafı diske kaydet
        with open(LAST_IMAGE_PATH, "wb") as f:
            f.write(image_bytes)

        if not GEMINI_API_KEY:
            return jsonify({"status": "partial_success", "message": "Resim kaydedildi ancak API Key eksik!"}), 200

        # 2. Görsel Boyutunu Optimize Et (RAM ve Timeout için)
        image = Image.open(io.BytesIO(image_bytes))
        image.thumbnail((1024, 1024))

        prompt = "Bu bir su sayaci goruntusudur. Lutfen sadece siyah ve kirmizi carklardaki okunan sayisal indeksi yaz. Ekstra hicbir aciklama yapma, sadece sayilari don."

        # 3. Sırasıyla denenacak güncel model isimleri
        candidate_models = [
            'gemini-1.5-flash-latest',
            'gemini-2.5-flash',
            'gemini-1.5-flash-001',
            'gemini-1.5-flash-002',
            'gemini-1.5-pro'
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

        # Eğer liste sonuncusu da başarsız olursa hesaptaki kullanılabilir ilk vision modelini dinamik seç
        if not response:
            try:
                available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
                for m_name in available_models:
                    if 'flash' in m_name or 'pro' in m_name:
                        model = genai.GenerativeModel(m_name)
                        response = model.generate_content([prompt, image])
                        if response and response.text:
                            used_model = m_name
                            break
            except Exception as e:
                print(f"Dinamik model listeleme hatasi: {str(e)}")

        if response and response.text:
            meter_reading = response.text.strip()
            print(f"--- OKUNAN SAYAÇ DEĞERİ ({used_model}): {meter_reading} ---")
            return jsonify({
                "status": "success",
                "reading": meter_reading,
                "model": used_model
            }), 200
        else:
            return jsonify({"status": "error", "message": "Hiçbir Gemini modeli yanıt üretmedi."}), 500

    except Exception as e:
        print(f"Hata olustu: {str(e)}")
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
