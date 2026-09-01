import os
from flask import Flask, request, jsonify, send_file
import google.generativeai as genai
from PIL import Image
import io

app = Flask(__name__)

# API Anahtarını Çek ve Boşlukları/Tırnakları Temizle
raw_api_key = os.environ.get("GEMINI_API_KEY", "")
GEMINI_API_KEY = raw_api_key.strip().strip('"').strip("'")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
else:
    print("UYARI: GEMINI_API_KEY ortam degiskeni bulunamadi!")

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

        # 1. Fotoğrafı diske kaydet (Canlı izleme adresi için)
        with open(LAST_IMAGE_PATH, "wb") as f:
            f.write(image_bytes)

        if not GEMINI_API_KEY:
            return jsonify({"status": "partial_success", "message": "Resim kaydedildi ama API Key eksik!"}), 200

        # 2. Gemini AI ile Görseli Analiz Et
        image = Image.open(io.BytesIO(image_bytes))
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = "Bu bir su sayaci goruntusudur. Lutfen sadece siyah ve kirmizi carklardaki okunan sayisal indeksi yaz. Ekstra hicbir aciklama yapma, sadece sayilari don."
        response = model.generate_content([prompt, image])
        meter_reading = response.text.strip()

        print(f"--- OKUNAN SAYAÇ DEĞERİ: {meter_reading} ---")

        return jsonify({
            "status": "success",
            "reading": meter_reading
        }), 200

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
